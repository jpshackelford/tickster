"""Issue timeline processing and history string generation."""

from dataclasses import dataclass
from datetime import datetime

from src.actors import ActorClass, HistoryEvent, classify_actor, iso_utc
from src.connection_paging import TRUNCATION_MARKER, is_truncated
from src.issue import dependencies
from src.issue.models import IssueActionType, IssueInfo, IssueState, TimelineEvent
from src.norms.model import Norms
from src.norms.store import get_repo_norms

# Preference when several PRs are linked: the one that landed, then the one in flight.
_PR_STATE_RANK = {"MERGED": 0, "OPEN": 1}


@dataclass(frozen=True)
class ClosingPr:
    """A PR whose closing keyword names the issue."""

    ref: str
    state: str
    created_at: datetime
    author: str


# An AI actor's opened and comment events get their own letters.
AI_CHARS = {IssueActionType.OPENED: "s", IssueActionType.COMMENT: "n"}


def process_issue_data(issue_data: dict, reference_user: str) -> IssueInfo:
    """Process raw issue data from GraphQL into IssueInfo.

    Args:
        issue_data: Raw issue data from GraphQL query
        reference_user: User for determining action case (lowercase = this user)

    Returns:
        Processed IssueInfo object
    """
    repo = issue_data["repository"]["nameWithOwner"]
    number = issue_data["number"]
    title = issue_data["title"]
    author = issue_data["author"]["login"] if issue_data["author"] else "ghost"
    created_at = _parse_datetime(issue_data["createdAt"])
    closed_at = _parse_datetime(issue_data["closedAt"]) if issue_data.get("closedAt") else None

    # Determine state
    state = IssueState.CLOSED if issue_data["state"] == "CLOSED" else IssueState.OPEN

    # Extract labels (alphabetically sorted)
    labels_data = issue_data.get("labels", {}).get("nodes", [])
    labels = sorted([lbl["name"] for lbl in labels_data if lbl])

    # Process timeline into history string and find linked PR
    events, linked_pr = _extract_timeline_events(
        issue_data, author, reference_user, get_repo_norms(repo)
    )
    history_events = _history_events(events, reference_user)
    history = _history_text(history_events, truncated=is_truncated(issue_data, "timelineItems"))

    # Find last activity time
    last_activity = _find_last_activity(events, created_at)

    return IssueInfo(
        repo=repo,
        number=number,
        title=title,
        state=state,
        history=history,
        linked_pr=linked_pr,
        labels=labels,
        created_at=created_at,
        closed_at=closed_at,
        last_activity=last_activity,
        author=author,
        events=history_events,
        open_blockers=dependencies.open_blockers(issue_data),
        blocking=dependencies.blocking_count(issue_data),
        parent=dependencies.parent_ref(issue_data),
        milestone=dependencies.milestone(issue_data),
    )


def _parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string from GitHub."""
    dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)


def closing_prs(issue_data: dict) -> list[ClosingPr]:
    """The PRs GitHub lists in ``closedByPullRequestsReferences``, in its order."""
    nodes = (issue_data.get("closedByPullRequestsReferences") or {}).get("nodes") or []
    return [
        ClosingPr(
            ref=f"{pr['repository']['nameWithOwner']}#{pr['number']}",
            state=pr["state"],
            created_at=_parse_datetime(pr["createdAt"]),
            author=pr["author"]["login"] if pr.get("author") else "ghost",
        )
        for pr in nodes
        if pr
    ]


def _extract_timeline_events(
    issue_data: dict, issue_author: str, reference_user: str, norms: Norms | None
) -> tuple[list[TimelineEvent], str | None]:
    """Extract timeline events and find linked PR.

    Returns:
        Tuple of (events, linked_pr_ref)
    """
    events: list[TimelineEvent] = []
    linked_prs: list[tuple[str, str]] = []  # (ref, state)

    # Add the "opened" event
    created_at = _parse_datetime(issue_data["createdAt"])
    events.append(
        TimelineEvent(
            action=IssueActionType.OPENED,
            actor=issue_author,
            timestamp=created_at,
            actor_class=classify_actor(issue_author, reference_user, norms, issue_data.get("body")),
        )
    )

    timeline_items = issue_data.get("timelineItems", {}).get("nodes", [])

    for item in timeline_items:
        if not item:
            continue

        typename = item.get("__typename")
        event = _parse_timeline_item(typename, item, reference_user, norms)
        if event:
            events.append(event)

        # Track cross-referenced PRs
        if typename == "CrossReferencedEvent":
            pr_ref = _extract_pr_reference(item)
            if pr_ref:
                linked_prs.append(pr_ref)

    # A closing keyword leaves no timeline item; a PR also found by cross-reference counts once.
    seen = {ref for ref, _ in linked_prs}
    for pr in closing_prs(issue_data):
        if pr.ref in seen:
            continue
        seen.add(pr.ref)
        linked_prs.append((pr.ref, pr.state))
        events.append(
            TimelineEvent(
                action=IssueActionType.PR_LINKED,
                actor=pr.author,
                timestamp=pr.created_at,
                actor_class=classify_actor(pr.author, reference_user, norms),
            )
        )

    # Sort by timestamp
    events.sort(key=lambda e: e.timestamp)

    linked_pr = _select_linked_pr(linked_prs)

    return events, linked_pr


def _parse_timeline_item(
    typename: str,
    item: dict,
    reference_user: str,
    norms: Norms | None,
) -> TimelineEvent | None:
    """Parse a single timeline item into an event."""
    event = _parse_event(typename, item)
    if event is None:
        return None
    event.actor_class = classify_actor(event.actor, reference_user, norms, item.get("body"))
    if event.action == IssueActionType.COMMENT and event.actor_class == ActorClass.BOT:
        event.action = IssueActionType.BOT_COMMENT
    return event


def _parse_event(typename: str, item: dict) -> TimelineEvent | None:
    if typename == "IssueComment":
        actor = item.get("author", {}).get("login", "ghost") if item.get("author") else "ghost"
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=IssueActionType.COMMENT, actor=actor, timestamp=timestamp)

    elif typename == "LabeledEvent":
        actor = item.get("actor", {}).get("login", "ghost") if item.get("actor") else "ghost"
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=IssueActionType.LABELED, actor=actor, timestamp=timestamp)

    elif typename == "ClosedEvent":
        actor = item.get("actor", {}).get("login", "ghost") if item.get("actor") else "ghost"
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=IssueActionType.CLOSED, actor=actor, timestamp=timestamp)

    elif typename == "ReopenedEvent":
        actor = item.get("actor", {}).get("login", "ghost") if item.get("actor") else "ghost"
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=IssueActionType.REOPENED, actor=actor, timestamp=timestamp)

    elif typename == "AssignedEvent":
        actor = item.get("actor", {}).get("login", "ghost") if item.get("actor") else "ghost"
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=IssueActionType.ASSIGNED, actor=actor, timestamp=timestamp)

    elif typename == "CrossReferencedEvent":
        # Check if source is a PR
        source = item.get("source")
        if source and source.get("__typename") == "PullRequest":
            actor = item.get("actor", {}).get("login", "ghost") if item.get("actor") else "ghost"
            timestamp = _parse_datetime(item["createdAt"])
            return TimelineEvent(action=IssueActionType.PR_LINKED, actor=actor, timestamp=timestamp)

    return None


def _extract_pr_reference(item: dict) -> tuple[str, str] | None:
    """Extract PR reference from CrossReferencedEvent."""
    source = item.get("source")
    if not source:
        return None

    # Only interested in PRs
    if source.get("__typename") != "PullRequest":
        return None

    number = source.get("number")
    repo_data = source.get("repository")
    state = source.get("state", "OPEN")

    if number and repo_data:
        repo = repo_data.get("nameWithOwner")
        if repo:
            return (f"{repo}#{number}", state)

    return None


def _select_linked_pr(prs: list[tuple[str, str]]) -> str | None:
    """Select the best linked PR from candidates.

    Prefers merged, then open, then closed; the first of its rank wins.
    """
    if not prs:
        return None
    return min(prs, key=lambda pr: _PR_STATE_RANK.get(pr[1], 2))[0]


def _is_ai(event: TimelineEvent) -> bool:
    return event.actor_class.is_ai and event.action in AI_CHARS


def _deduplicate_consecutive(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """Remove consecutive duplicates: the same action, by an AI actor or not."""
    if not events:
        return []

    result: list[TimelineEvent] = [events[0]]
    for event in events[1:]:
        last = result[-1]
        if event.action != last.action or _is_ai(event) != _is_ai(last):
            result.append(event)
    return result


def _format_action(
    action: IssueActionType, actor: str, reference_user: str, *, ai: bool = False
) -> str:
    """Convert action to case-appropriate character.

    - BOT_COMMENT is always uppercase "B"
    - Other actions: lowercase = reference_user, uppercase = others
    - ``ai`` swaps in the AI actor's letter for opened and comment
    """
    char = AI_CHARS[action] if ai and action in AI_CHARS else action.value

    # BOT_COMMENT is always uppercase
    if action == IssueActionType.BOT_COMMENT:
        return char

    is_reference_user = actor.lower() == reference_user.lower()
    if not is_reference_user:
        char = char.upper()
    return char


def _history_events(events: list[TimelineEvent], reference_user: str) -> list[HistoryEvent]:
    """The events a history string shows, one per character."""
    return [
        HistoryEvent(
            char=_format_action(e.action, e.actor, reference_user, ai=e.actor_class.is_ai),
            action=e.action.name.lower(),
            actor=e.actor,
            actor_class=e.actor_class,
            at=iso_utc(e.timestamp),
        )
        for e in _deduplicate_consecutive(events)
    ]


def _history_text(history_events: list[HistoryEvent], truncated: bool) -> str:
    history = "".join(e.char for e in history_events)
    return history + TRUNCATION_MARKER if truncated else history


def _build_history_string(
    events: list[TimelineEvent],
    reference_user: str,
    truncated: bool = False,
) -> str:
    """Build the compact history string from timeline events.

    Rules:
    - Lowercase = action by reference_user
    - Uppercase = action by someone else
    - BOT_COMMENT is always "B"; a comment by an AI actor is "n" (you) or "N" (others)
    - Consecutive duplicates are collapsed
    - ``truncated`` appends a marker: events past the fetch cap are missing
    """
    return _history_text(_history_events(events, reference_user), truncated)


def _find_last_activity(events: list[TimelineEvent], created_at: datetime) -> datetime:
    """Find the timestamp of the most recent activity."""
    if not events:
        return created_at

    return max(e.timestamp for e in events)
