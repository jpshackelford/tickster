"""Fetch one issue with the text of its comments, and turn it into a timeline."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.actors import classify_actor, iso_utc
from src.board.github_api import GitHubClient
from src.connection_paging import complete_connection, is_truncated
from src.issue.github_api import CLOSING_PRS_FIELD, ISSUE_LABELS, ISSUE_TIMELINE
from src.issue.history import (
    ClosingPr,
    _extract_pr_reference,
    _format_action,
    _parse_datetime,
    _parse_timeline_item,
    closing_prs,
    process_issue_data,
)
from src.issue.models import IssueActionType, TimelineEvent
from src.norms.model import Norms
from src.norms.store import get_repo_norms
from src.show.models import NO_CHAR, Entry, Show, trim_body

# A busy issue's whole timeline matters here, so the cap is far above the list commands'.
TIMELINE_CAP = 5000

# Events the history string ignores, which tell a reader a label or assignee is gone.
_EXTRA_EVENTS = {
    "UnlabeledEvent": ("unlabeled", "label"),
    "UnassignedEvent": ("unassigned", "assignee"),
}

ISSUE_SHOW_TIMELINE = replace(
    ISSUE_TIMELINE,
    args=ISSUE_TIMELINE.args.replace(
        "CROSS_REFERENCED_EVENT",
        "CROSS_REFERENCED_EVENT,\n        UNLABELED_EVENT,\n        UNASSIGNED_EVENT",
    ),
    selection=ISSUE_TIMELINE.selection
    + """
            ... on UnlabeledEvent {
                actor { login }
                label { name }
                createdAt
            }
            ... on UnassignedEvent {
                actor { login }
                assignee {
                    ... on User { login }
                    ... on Bot { login }
                    ... on Mannequin { login }
                }
                createdAt
            }""",
    cap=TIMELINE_CAP,
)

ISSUE_SHOW_QUERY = f"""
query($owner: String!, $name: String!, $number: Int!) {{
    repository(owner: $owner, name: $name) {{
        issue(number: $number) {{
            id
            number
            title
            body
            url
            state
            createdAt
            closedAt
            author {{ login }}
            repository {{ nameWithOwner }}
            assignees(first: 20) {{ nodes {{ login }} }}
            {ISSUE_LABELS.fragment_field()}
            {ISSUE_SHOW_TIMELINE.fragment_field()}
            {CLOSING_PRS_FIELD}
        }}
    }}
}}
"""


def fetch_issue_node(client: GitHubClient, repo: str, number: int) -> dict:
    """The raw issue with every connection followed to its cap."""
    owner, name = repo.split("/", 1)
    data = client.graphql(ISSUE_SHOW_QUERY, {"owner": owner, "name": name, "number": number})
    node = (data.get("repository") or {}).get("issue")
    if node is None:
        raise ValueError(f"issue not found: {repo}#{number}")
    complete_connection(client, node, ISSUE_SHOW_TIMELINE)
    complete_connection(client, node, ISSUE_LABELS)
    return node


def _pr_linked_fields(ref: str | None, state: str | None) -> tuple[str, str, dict]:
    return (
        "pr_linked",
        f"linked PR {ref} ({(state or '').lower()})",
        {"pr": ref, "pr_state": state},
    )


def _describe(event: TimelineEvent, raw: dict) -> tuple[str, str, dict]:
    """(kind, text, fields) for one issue timeline event."""
    action = event.action
    if action in (IssueActionType.COMMENT, IssueActionType.BOT_COMMENT):
        return "comment", "commented", {}
    if action == IssueActionType.LABELED:
        label = (raw.get("label") or {}).get("name")
        return "labeled", f"labeled {label}", {"label": label}
    if action == IssueActionType.ASSIGNED:
        assignee = (raw.get("assignee") or {}).get("login")
        return "assigned", f"assigned {assignee}", {"assignee": assignee}
    if action == IssueActionType.PR_LINKED:
        pr_ref = _extract_pr_reference(raw)
        ref, state = pr_ref if pr_ref else (None, None)
        return _pr_linked_fields(ref, state)
    return action.name.lower(), action.name.lower(), {}


def _entry(
    raw: dict, reference_user: str, norms: Norms | None, max_body: int
) -> tuple[datetime, Entry] | None:
    typename = raw["__typename"]
    event = _parse_timeline_item(typename, raw, reference_user, norms)
    if event is not None:
        kind, text, fields = _describe(event, raw)
        at, actor, actor_class = event.timestamp, event.actor, event.actor_class
        char = _format_action(event.action, actor, reference_user, ai=actor_class.is_ai)
    elif typename in _EXTRA_EVENTS:
        kind, field = _EXTRA_EVENTS[typename]
        what = (raw.get("label") or raw.get("assignee") or {}).get("name") or (
            raw.get("assignee") or {}
        ).get("login")
        text, fields = f"{kind} {what}", {field: what}
        at = _parse_datetime(raw["createdAt"])
        actor = (raw.get("actor") or {}).get("login") or "ghost"
        actor_class = classify_actor(actor, reference_user, norms)
        char = NO_CHAR
    else:
        return None
    body, more = trim_body(raw.get("body"), max_body)
    entry = Entry(
        at=iso_utc(at),
        kind=kind,
        char=char,
        actor=actor,
        actor_class=actor_class,
        text=text,
        body=body,
        more_chars=more,
        fields=fields,
    )
    return at, entry


def _closing_pr_entry(
    pr: ClosingPr, reference_user: str, norms: Norms | None
) -> tuple[datetime, Entry]:
    actor_class = classify_actor(pr.author, reference_user, norms)
    kind, text, fields = _pr_linked_fields(pr.ref, pr.state)
    entry = Entry(
        at=iso_utc(pr.created_at),
        kind=kind,
        char=_format_action(IssueActionType.PR_LINKED, pr.author, reference_user),
        actor=pr.author,
        actor_class=actor_class,
        text=text,
        fields=fields,
    )
    return pr.created_at, entry


def build_issue_show(node: dict, reference_user: str, max_body: int) -> Show:
    info = process_issue_data(node, reference_user)
    norms = get_repo_norms(info.repo)

    body, more = trim_body(node.get("body"), max_body)
    entries = [
        Entry(
            at=iso_utc(info.created_at),
            kind="opened",
            char=_format_action(IssueActionType.OPENED, info.author, reference_user),
            actor=info.author,
            actor_class=classify_actor(info.author, reference_user, norms, node.get("body")),
            text="opened",
            body=body,
            more_chars=more,
        )
    ]

    linked_prs: dict[str, str] = {}
    timed: list[tuple[datetime, Entry]] = []
    for raw in node["timelineItems"]["nodes"]:
        if not raw:
            continue
        timed_entry = _entry(raw, reference_user, norms, max_body)
        if timed_entry is not None:
            timed.append(timed_entry)
        pr_ref = _extract_pr_reference(raw) if raw["__typename"] == "CrossReferencedEvent" else None
        if pr_ref:
            linked_prs[pr_ref[0]] = pr_ref[1]
    for pr in closing_prs(node):
        if pr.ref not in linked_prs:
            linked_prs[pr.ref] = pr.state
            timed.append(_closing_pr_entry(pr, reference_user, norms))
    timed.sort(key=lambda t: t[0])
    entries.extend(entry for _, entry in timed)

    header = {
        "repo": info.repo,
        "number": info.number,
        "url": node.get("url"),
        "state": info.state.value,
        "author": info.author,
        "created_at": iso_utc(info.created_at),
        "last_activity": iso_utc(info.last_activity),
        "history": info.history,
        "labels": info.labels,
        "assignees": [a["login"] for a in node["assignees"]["nodes"] if a],
        "linked_pr": info.linked_pr,
        "linked_prs": [{"ref": ref, "state": state.lower()} for ref, state in linked_prs.items()],
    }
    return Show(
        kind="issue",
        repo=info.repo,
        number=info.number,
        title=info.title,
        header=header,
        entries=entries,
        truncated=is_truncated(node, "timelineItems"),
    )
