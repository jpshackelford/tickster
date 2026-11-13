"""Evidence `pr list --diff --format json` adds to each added or changed row.

A consumer that polls needs what was said and which steps are open, not only
that a row moved. The events come from the code behind `pr show` and the steps
from `collect_steps`, so a delta carries exactly what those commands print.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from src.board.github_api import GitHubClient, get_github_token, get_github_username
from src.pr.step_types import StepResult
from src.show.models import Show, parse_time
from src.show.pr import build_pr_show, fetch_pr_node
from src.snapshot.models import ChangeKind, DiffResult, ItemDelta

EVENTS_BRIEF = "brief"
EVENTS_FULL = "full"
EVENTS_NONE = "none"
EVENTS_MODES = (EVENTS_BRIEF, EVENTS_FULL, EVENTS_NONE)

BRIEF_BODY = 160
NO_TRIM = 0  # `trim_body` leaves a body whole at 0

_WITH_EVIDENCE = (ChangeKind.ADDED, ChangeKind.CHANGED)


def body_limit(events: str, max_body: int | None) -> int:
    """The body cut for `events`; `max_body` overrides the brief default."""
    if events == EVENTS_FULL:
        return NO_TRIM
    return BRIEF_BODY if max_body is None else max_body


def add_pr_evidence(
    result: DiffResult,
    *,
    events: str,
    max_body: int | None,
    steps: Mapping[str, tuple[StepResult, ...]],
) -> DiffResult:
    """Add `steps` and, unless `events` is none, `events_since` to each added or changed delta.

    A changed row gets the events after its previous `last_activity`; an added
    row has no earlier state, so it gets the whole timeline. Removed and
    unchanged rows are left as they are and cost no call.
    """
    wanted = [d for d in result.deltas if d.change in _WITH_EVIDENCE]
    shows = _fetch_shows(wanted, body_limit(events, max_body)) if events != EVENTS_NONE else {}
    deltas = tuple(
        _with_evidence(d, steps, shows.get(d.ref)) if d.change in _WITH_EVIDENCE else d
        for d in result.deltas
    )
    return replace(result, deltas=deltas)


def _fetch_shows(wanted: list[ItemDelta], max_body: int) -> dict[str, Show]:
    if not wanted:
        return {}
    shows: dict[str, Show] = {}
    with GitHubClient(get_github_token()) as client:
        reference_user = get_github_username() or client.get_authenticated_user()
        for delta in wanted:
            item = delta.display_item
            repo, number = item.ref.rsplit("#", 1)
            show = build_pr_show(fetch_pr_node(client, repo, int(number)), reference_user, max_body)
            if delta.prev is not None:
                show.apply_since(parse_time(delta.prev.last_activity))
            shows[delta.ref] = show
    return shows


def _with_evidence(
    delta: ItemDelta, steps: Mapping[str, tuple[StepResult, ...]], show: Show | None
) -> ItemDelta:
    evidence = replace(delta, steps=tuple(r.to_dict() for r in steps[delta.ref]))
    if show is None:
        return evidence
    return replace(
        evidence,
        events_since=tuple(e.to_dict() for e in show.entries),
        events_truncated=show.truncated,
    )
