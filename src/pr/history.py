"""PR timeline processing and history string generation."""

from datetime import datetime

from src.actors import HistoryEvent, classify_actor, iso_utc
from src.connection_paging import TRUNCATION_MARKER, is_truncated
from src.norms.model import COMMENT_MATCH_CHARS, Norms
from src.norms.store import get_repo_norms
from src.pr.models import ActionType, CIStatus, PRComment, PRInfo, PRState, TimelineEvent
from src.pr.reviewers import build_reviewers

# An AI actor's version of these events gets its own letter.
AI_CHARS = {
    ActionType.OPENED: "s",
    ActionType.REVIEW: "e",
    ActionType.APPROVED: "v",
    ActionType.COMMENT: "n",
}


def process_pr_data(pr_data: dict, reference_user: str) -> PRInfo:
    """Process raw PR data from GraphQL into PRInfo.

    Args:
        pr_data: Raw PR data from GraphQL query
        reference_user: User for determining action case (lowercase = this user)

    Returns:
        Processed PRInfo object
    """
    # Extract basic fields
    repo = pr_data["repository"]["nameWithOwner"]
    number = pr_data["number"]
    title = pr_data["title"]
    author = pr_data["author"]["login"] if pr_data["author"] else "ghost"
    created_at = _parse_datetime(pr_data["createdAt"])
    closed_at = _parse_datetime(pr_data["closedAt"]) if pr_data.get("closedAt") else None
    is_draft = pr_data.get("isDraft", False)

    # Count unresolved review threads
    unresolved_thread_count = _count_unresolved_threads(pr_data)

    # Determine state
    state = _determine_state(pr_data)

    # Determine CI status
    ci_status = _determine_ci_status(pr_data)

    # Process timeline into history string
    norms = get_repo_norms(repo)
    events = _extract_timeline_events(pr_data, author, reference_user, norms)
    history_events = _history_events(events, reference_user)
    history = _history_text(history_events, truncated=is_truncated(pr_data, "timelineItems"))

    # Find last activity time
    last_activity = _find_last_activity(events, created_at)

    return PRInfo(
        repo=repo,
        number=number,
        title=title,
        state=state,
        ci_status=ci_status,
        history=history,
        created_at=created_at,
        closed_at=closed_at,
        last_activity=last_activity,
        author=author,
        is_draft=is_draft,
        unresolved_thread_count=unresolved_thread_count,
        head_sha=pr_data.get("headRefOid"),
        review_decision=pr_data.get("reviewDecision"),
        merge_state=pr_data.get("mergeStateStatus"),
        mergeable=pr_data.get("mergeable"),
        events=history_events,
        reviewers=build_reviewers(pr_data, reference_user, norms),
        reviewers_truncated=is_truncated(pr_data, "reviewRequests")
        or is_truncated(pr_data, "latestReviews"),
        labels=tuple(n["name"] for n in (pr_data.get("labels") or {}).get("nodes", []) if n),
        checks_state=_rollup_state(pr_data),
        comments=_comment_records(pr_data, reference_user, norms),
        timeline_truncated=is_truncated(pr_data, "timelineItems"),
    )


def _parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string from GitHub."""
    # Handle both with and without microseconds
    dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)


def _count_unresolved_threads(pr_data: dict) -> int:
    """Count unresolved review threads."""
    threads = pr_data.get("reviewThreads", {}).get("nodes", [])
    return sum(1 for t in threads if t and not t.get("isResolved", True))


def _determine_state(pr_data: dict) -> PRState:
    """Determine PR state from GraphQL data."""
    state = pr_data["state"]
    if state == "MERGED":
        return PRState.MERGED
    elif state == "CLOSED":
        return PRState.CLOSED
    else:
        return PRState.OPEN


def _rollup_state(pr_data: dict) -> str | None:
    commits = pr_data.get("commits", {}).get("nodes", [])
    rollup = commits[-1].get("commit", {}).get("statusCheckRollup") if commits else None
    return rollup.get("state") if rollup else None


def _determine_ci_status(pr_data: dict) -> CIStatus:
    """Determine CI status from mergeable state and check rollup."""
    # Check for merge conflicts first (takes precedence)
    mergeable = pr_data.get("mergeable")
    if mergeable == "CONFLICTING":
        return CIStatus.CONFLICT

    # Check status rollup
    commits = pr_data.get("commits", {}).get("nodes", [])
    if commits:
        last_commit = commits[-1]
        rollup = last_commit.get("commit", {}).get("statusCheckRollup")
        if rollup:
            state = rollup.get("state")
            if state == "SUCCESS":
                return CIStatus.GREEN
            elif state in ("FAILURE", "ERROR"):
                return CIStatus.RED
            elif state in ("PENDING", "EXPECTED"):
                return CIStatus.PENDING

    return CIStatus.NONE


def _extract_timeline_events(
    pr_data: dict, pr_author: str, reference_user: str, norms: Norms | None
) -> list[TimelineEvent]:
    """Extract and sort timeline events from PR data."""
    events: list[TimelineEvent] = []

    # Add the "opened" event
    created_at = _parse_datetime(pr_data["createdAt"])
    events.append(
        TimelineEvent(
            action=ActionType.OPENED,
            actor=pr_author,
            timestamp=created_at,
            actor_class=classify_actor(pr_author, reference_user, norms, pr_data.get("body")),
        )
    )

    # Track whether we've seen any review (for determining if commits are "fixes")
    timeline_items = pr_data.get("timelineItems", {}).get("nodes", [])

    for item in timeline_items:
        if not item:
            continue

        typename = item.get("__typename")
        event = _parse_timeline_item(typename, item, pr_author, reference_user, norms)
        if event:
            events.append(event)

    # Sort by timestamp
    events.sort(key=lambda e: e.timestamp)

    return events


def _login(node: dict | None, default: str = "ghost") -> str:
    """Return node's login; GitHub reports deleted accounts as a null author/actor."""
    return (node or {}).get("login") or default


def _parse_timeline_item(
    typename: str,
    item: dict,
    pr_author: str,
    reference_user: str,
    norms: Norms | None,
) -> TimelineEvent | None:
    """Parse a single timeline item into an event."""
    event = _parse_event(typename, item, pr_author)
    if event is None:
        return None
    event.actor_class = classify_actor(event.actor, reference_user, norms, item.get("body"))
    return event


def _parse_event(typename: str, item: dict, pr_author: str) -> TimelineEvent | None:
    if typename == "PullRequestReview":
        actor = _login(item.get("author"))
        timestamp = _parse_datetime(item["createdAt"])
        state = item.get("state")
        has_inline_comments = item.get("comments", {}).get("totalCount", 0) > 0

        if state == "APPROVED":
            action = ActionType.APPROVED
        elif state == "CHANGES_REQUESTED":
            action = ActionType.REVIEW
        elif state == "COMMENTED":
            # Treat as REVIEW if it has inline code comments, otherwise COMMENT
            action = ActionType.REVIEW if has_inline_comments else ActionType.COMMENT
        else:
            return None

        return TimelineEvent(action=action, actor=actor, timestamp=timestamp)

    elif typename == "IssueComment":
        actor = _login(item.get("author"))
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=ActionType.COMMENT, actor=actor, timestamp=timestamp)

    elif typename == "PullRequestCommit":
        commit = item.get("commit", {})
        git_actor = commit.get("author")
        actor = _login(git_actor.get("user") if git_actor else None, default=pr_author)
        timestamp = _parse_datetime(commit["committedDate"])
        # Note: We'll convert this to FIX later if it comes after a review
        return TimelineEvent(action=ActionType.FIX, actor=actor, timestamp=timestamp)

    elif typename == "ReviewRequestedEvent":
        actor = _login(item.get("actor"))
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=ActionType.HELP, actor=actor, timestamp=timestamp)

    elif typename == "MergedEvent":
        actor = _login(item.get("actor"))
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=ActionType.MERGED, actor=actor, timestamp=timestamp)

    elif typename == "ClosedEvent":
        # Only count as KILLED if not merged (check handled in caller context)
        actor = _login(item.get("actor"))
        timestamp = _parse_datetime(item["createdAt"])
        return TimelineEvent(action=ActionType.KILLED, actor=actor, timestamp=timestamp)

    return None


def _filter_timeline_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """Filter events that shouldn't appear in history.

    Removes:
    - Commits before any review (they're not "fixes")
    - Killed events after merged events
    """
    filtered: list[TimelineEvent] = []
    has_had_review = False
    is_merged = False

    for event in events:
        action = event.action

        # Skip commits before any review (they're not "fixes")
        if action == ActionType.FIX and not has_had_review:
            continue

        # Track if we've had a review
        if action in (ActionType.REVIEW, ActionType.APPROVED, ActionType.COMMENT):
            has_had_review = True

        # Track if merged (to skip the closed event)
        if action == ActionType.MERGED:
            is_merged = True

        # Skip killed if we already have merged
        if action == ActionType.KILLED and is_merged:
            continue

        filtered.append(event)

    return filtered


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


def _format_action(action: ActionType, actor: str, reference_user: str, *, ai: bool = False) -> str:
    """Convert action to case-appropriate character.

    Lowercase = action by reference_user
    Uppercase = action by someone else
    ``ai`` swaps in the AI actor's letter for opened, review, approval and comment.
    """
    char = AI_CHARS[action] if ai and action in AI_CHARS else action.value
    is_reference_user = actor.lower() == reference_user.lower()
    if not is_reference_user:
        char = char.upper()
    return char


def _history_events(events: list[TimelineEvent], reference_user: str) -> list[HistoryEvent]:
    """The events a history string shows, one per character."""
    deduped = _deduplicate_consecutive(_filter_timeline_events(events))
    return [
        HistoryEvent(
            char=_format_action(e.action, e.actor, reference_user, ai=e.actor_class.is_ai),
            action=e.action.name.lower(),
            actor=e.actor,
            actor_class=e.actor_class,
            at=iso_utc(e.timestamp),
        )
        for e in deduped
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
    - Reviews, approvals and comments by an AI actor use their own letters
    - Consecutive duplicates are collapsed
    - ``truncated`` appends a marker: events past the fetch cap are missing
    - Commits before any review are ignored (not "fixes")
    - If merged, don't also show killed
    """
    return _history_text(_history_events(events, reference_user), truncated)


def _comment_records(
    pr_data: dict, reference_user: str, norms: Norms | None
) -> tuple[PRComment, ...]:
    """The plain comments a ``[reports]`` marker could match, each with the head it was posted on.

    Empty when the repo defines no reports. The head is the last commit or
    force-push before the comment, in the order ``tkt pr show`` reads them.
    """
    if norms is None or not norms.reports:
        return ()
    stamped = []
    for item in pr_data.get("timelineItems", {}).get("nodes", []):
        if not item:
            continue
        typename = item.get("__typename")
        if typename == "PullRequestCommit":
            at = (item.get("commit") or {}).get("committedDate")
        elif typename in ("IssueComment", "HeadRefForcePushedEvent"):
            at = item.get("createdAt")
        else:
            continue
        if at:
            stamped.append((_parse_datetime(at), item))
    stamped.sort(key=lambda pair: pair[0])

    head: str | None = None
    comments: list[PRComment] = []
    for at, item in stamped:
        typename = item["__typename"]
        if typename == "PullRequestCommit":
            head = item["commit"].get("oid") or head
        elif typename == "HeadRefForcePushedEvent":
            head = (item.get("afterCommit") or {}).get("oid") or head
        else:
            body = item.get("body") or ""
            actor = _login(item.get("author"))
            comments.append(
                PRComment(
                    actor=actor,
                    actor_class=classify_actor(actor, reference_user, norms, body),
                    at=iso_utc(at),
                    text=body[:COMMENT_MATCH_CHARS],
                    head=head,
                )
            )
    return tuple(comments)


def _find_last_activity(events: list[TimelineEvent], created_at: datetime) -> datetime:
    """Find the timestamp of the most recent activity."""
    if not events:
        return created_at

    return max(e.timestamp for e in events)
