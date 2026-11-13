"""Replace the guessed reason on gone rows with the row's current state.

Behind `--diff-resolve`. The default diff makes no extra network calls; with
the flag, each `-` row is looked up by ref (one batched query per 20 rows, via
the list clients' `get_*_by_ref`) and its reason becomes a fact.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from enum import Enum
from typing import Protocol

from src.issue.models import IssueInfo
from src.snapshot.models import ChangeKind, DiffResult

REASON_NOT_FOUND = "not-found"
REASON_STILL_OPEN = "still-open"
REASON_PR_LINKED = "pr-linked"


class _HasState(Protocol):
    repo: str
    number: int

    @property
    def state(self) -> Enum: ...


FetchByRef = Callable[[list[str]], Iterable[_HasState]]


def resolve_removed(diff: DiffResult, fetch: FetchByRef) -> DiffResult:
    """Return `diff` with each REMOVED row's reason set to its current state.

    The reason becomes `closed`, `merged`, `still-open` (it is open but the
    filters no longer match it) or `not-found`. Under a `--no-pr` scope an open
    issue that now has a linked PR is `pr-linked`. Makes no call when no row is gone.
    """
    gone = [d.key for d in diff.deltas if d.kind is ChangeKind.REMOVED]
    if not gone:
        return diff
    no_pr_scope = diff.curr.scope.pr_filter == "no-pr"
    states: dict[str, str] = {}
    for item in fetch(gone):
        key = f"{item.repo}#{item.number}".lower()
        linked = no_pr_scope and isinstance(item, IssueInfo) and item.linked_pr is not None
        states[key] = (
            REASON_PR_LINKED if linked and item.state.value == "open" else item.state.value
        )
    deltas = tuple(
        replace(d, disappearance_reason=_reason(states.get(d.key.lower())))
        if d.kind is ChangeKind.REMOVED
        else d
        for d in diff.deltas
    )
    return replace(diff, deltas=deltas)


def _reason(state: str | None) -> str:
    if state is None:
        return REASON_NOT_FOUND
    return REASON_STILL_OPEN if state == "open" else state
