"""GitHub's issue dependency facts: blockers, blocked issues, parent and milestone."""

from __future__ import annotations

from datetime import UTC, datetime

from src.connection_paging import ConnectionSpec
from src.issue.models import Milestone

UNREADABLE_BLOCKER = "?"

_ISSUE_REF_SELECTION = "        number\n        state\n        repository { nameWithOwner }"

ISSUE_BLOCKED_BY = ConnectionSpec(
    type_name="Issue",
    field="blockedBy",
    selection=_ISSUE_REF_SELECTION,
    cap=500,
    first=50,
    total_count=True,
)
ISSUE_BLOCKING = ConnectionSpec(
    type_name="Issue",
    field="blocking",
    selection=_ISSUE_REF_SELECTION,
    cap=500,
    first=50,
    total_count=True,
)
PARENT_FIELD = "parent { number repository { nameWithOwner } }"
MILESTONE_FIELD = "milestone { title dueOn }"

DEPENDENCY_FIELDS = f"""{ISSUE_BLOCKED_BY.fragment_field()}
    {ISSUE_BLOCKING.fragment_field()}
    {PARENT_FIELD}
    {MILESTONE_FIELD}"""


def _ref(node: dict) -> str:
    return f"{node['repository']['nameWithOwner']}#{node['number']}"


def _readable(conn: dict | None) -> list[dict]:
    return [n for n in (conn or {}).get("nodes", []) if n]


def open_blockers(issue_data: dict) -> list[str]:
    """Refs of the open issues that block this one, sorted; one ``?`` per unreadable blocker.

    A blocker the token cannot read has no state, so it counts as open: the issue
    stays blocked until someone who can see it says otherwise.
    """
    conn = issue_data.get("blockedBy") or {}
    readable = _readable(conn)
    refs = sorted(
        (n["repository"]["nameWithOwner"], n["number"]) for n in readable if n["state"] != "CLOSED"
    )
    unreadable = max(0, conn.get("totalCount", len(readable)) - len(readable))
    return [f"{repo}#{number}" for repo, number in refs] + [UNREADABLE_BLOCKER] * unreadable


def blocking_count(issue_data: dict) -> int:
    """Number of readable open issues that this issue blocks."""
    return sum(1 for n in _readable(issue_data.get("blocking")) if n["state"] != "CLOSED")


def parent_ref(issue_data: dict) -> str | None:
    parent = issue_data.get("parent")
    return _ref(parent) if parent else None


def milestone(issue_data: dict) -> Milestone | None:
    raw = issue_data.get("milestone")
    if not raw:
        return None
    due = raw.get("dueOn")
    due_on = (
        datetime.fromisoformat(due.replace("Z", "+00:00"))
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
        if due
        else None
    )
    return Milestone(title=raw["title"], due_on=due_on)


def short_ref(ref: str, repo: str) -> str:
    """``#N`` for an issue in ``repo``, the full ref for one elsewhere, ``?`` as it is."""
    owner_repo, sep, number = ref.rpartition("#")
    return f"#{number}" if sep and owner_repo == repo else ref


def deps_line(
    open_blockers: list[str] | tuple[str, ...],
    blocking: int,
    parent: str | None,
    milestone: Milestone | None,
    repo: str,
) -> str | None:
    """One text line of the non-empty dependency facts, or None when there are none."""
    parts = []
    if open_blockers:
        parts.append("blocked by: " + ", ".join(short_ref(r, repo) for r in open_blockers))
    if blocking:
        parts.append(f"blocks: {blocking}")
    if parent:
        parts.append(f"parent: {short_ref(parent, repo)}")
    if milestone:
        parts.append(f"milestone: {milestone.title}")
    return "  ".join(parts) or None
