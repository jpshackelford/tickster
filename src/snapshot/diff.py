"""Pure diff of two snapshots.

Items are matched by their `key` (`owner/repo#NNN`). For items present in
both snapshots we compare the fields that drive the display and produce an
`ItemDelta` with:

- `changed_fields` — which of (history, state, ci_status, labels,
  unresolved_thread_count, is_draft, linked_pr, review_status) differ,
  plus `"activity"` when `last_activity` moved. PR rows also compare
  `head_sha`, `review_decision`, `merge_state` and `mergeable` (see
  `_compare_pr_detail`). History collapses
  consecutive same-type events, so new comments or reviews can leave the
  string byte-identical; `last_activity` still records them.
- `new_history_tail` — characters of `curr.history` not in `prev.history`,
  computed as the longest common prefix (LCP). The history string is
  append-only by construction (`src.pr.history`, `src.issue.history`),
  so LCP yields exactly the events that appeared since the prior snapshot.
  Fallback: if `prev.history` is not an LCP-prefix of `curr.history`
  (e.g. GitHub mutated history by deleting a comment), we flag the whole
  `curr.history` as the new tail and record `"history-rewritten"` as a
  changed field so the agent is told the diff is approximate.

A `ci_status` move to or from `conflict` is not flagged while either side's
`mergeable` is `UNKNOWN` (GitHub computes mergeability lazily); see
`_is_mergeability_warmup`.
"""

from __future__ import annotations

from src.snapshot.models import (
    KIND_REVIEW,
    ChangeKind,
    DiffResult,
    ItemDelta,
    ItemSnapshot,
    Snapshot,
)

_FIELDS_TO_COMPARE: tuple[str, ...] = (
    "history",
    "state",
    "ci_status",
    "is_draft",
    "labels",
    "unresolved_thread_count",
    "linked_pr",
    "review_status",
)

_PR_DETAIL_FIELDS: tuple[str, ...] = ("head_sha", "review_decision", "merge_state", "mergeable")
_MERGEABILITY_FIELDS = ("merge_state", "mergeable")
_MERGEABILITY_UNKNOWN = "UNKNOWN"


def diff_snapshots(prev: Snapshot, curr: Snapshot) -> DiffResult:
    """Return the diff of two snapshots.

    `prev` and `curr` must be the same `kind` (pr/issue/review). Scope
    equality is reported via `DiffResult.scope_matches` but does not block
    the diff; callers decide whether to warn.
    """
    if prev.kind != curr.kind:
        raise ValueError(
            f"cannot diff snapshots of different kinds: {prev.kind!r} vs {curr.kind!r}"
        )

    prev_items = prev.items_by_key
    curr_items = curr.items_by_key

    deltas: list[ItemDelta] = []
    added_count = len(curr_items.keys() - prev_items.keys())
    prev_rank = {it.key: i for i, it in enumerate(prev.items)}

    # ADDED: in curr, not in prev
    for key in curr_items.keys() - prev_items.keys():
        deltas.append(
            ItemDelta(
                key=key,
                kind=ChangeKind.ADDED,
                prev=None,
                curr=curr_items[key],
                new_history_tail=curr_items[key].history,
                changed_fields=(),
            )
        )

    # REMOVED: in prev, not in curr
    for key in prev_items.keys() - curr_items.keys():
        deltas.append(
            ItemDelta(
                key=key,
                kind=ChangeKind.REMOVED,
                prev=prev_items[key],
                curr=None,
                disappearance_reason=_infer_removal_reason(
                    prev_items[key],
                    curr,
                    prev,
                    pushed_out=prev_rank[key] >= len(prev.items) - added_count,
                ),
            )
        )

    # CHANGED / UNCHANGED: in both
    for key in prev_items.keys() & curr_items.keys():
        p = prev_items[key]
        c = curr_items[key]
        changed = _compare_fields(p, c)
        tail = _new_history_tail(p.history, c.history)
        if changed:
            deltas.append(
                ItemDelta(
                    key=key,
                    kind=ChangeKind.CHANGED,
                    prev=p,
                    curr=c,
                    new_history_tail=tail,
                    changed_fields=changed,
                )
            )
        else:
            deltas.append(
                ItemDelta(
                    key=key,
                    kind=ChangeKind.UNCHANGED,
                    prev=p,
                    curr=c,
                )
            )

    deltas.sort(key=_delta_sort_key)
    return DiffResult(
        prev=prev,
        curr=curr,
        deltas=tuple(deltas),
        scope_matches=(prev.scope_hash == curr.scope_hash),
    )


def _delta_sort_key(d: ItemDelta) -> tuple:
    """Order: ADDED, CHANGED, REMOVED, UNCHANGED; then by key."""
    kind_order = {
        ChangeKind.ADDED: 0,
        ChangeKind.CHANGED: 1,
        ChangeKind.REMOVED: 2,
        ChangeKind.UNCHANGED: 3,
    }
    return (kind_order[d.kind], d.key)


def _compare_fields(prev: ItemSnapshot, curr: ItemSnapshot) -> tuple[str, ...]:
    """Return the names of fields that differ between prev and curr."""
    changed: list[str] = []
    for field_name in _FIELDS_TO_COMPARE:
        a = getattr(prev, field_name)
        b = getattr(curr, field_name)
        if field_name == "labels":
            if set(a) != set(b):
                changed.append(field_name)
            continue
        if field_name == "ci_status" and a != b and _is_mergeability_warmup(prev, curr):
            continue
        if a != b:
            changed.append(field_name)
    changed.extend(_compare_pr_detail(prev, curr))
    if prev.last_activity != curr.last_activity:
        changed.append("activity")
    # History-rewritten tag: history changed but prev is not a prefix of curr.
    if "history" in changed and not curr.history.startswith(prev.history):
        changed.append("history-rewritten")
    return tuple(changed)


def _compare_pr_detail(prev: ItemSnapshot, curr: ItemSnapshot) -> list[str]:
    """Names of head / review / mergeability fields that differ.

    A snapshot without `head_sha` predates these fields, so comparing would flag
    every row. GitHub reports `UNKNOWN` mergeability while it computes it after a
    push or a base change; a move to or from `UNKNOWN` is warm-up noise.
    """
    if prev.head_sha is None or curr.head_sha is None:
        return []
    changed: list[str] = []
    for field_name in _PR_DETAIL_FIELDS:
        a = getattr(prev, field_name)
        b = getattr(curr, field_name)
        if a == b:
            continue
        if field_name in _MERGEABILITY_FIELDS and _MERGEABILITY_UNKNOWN in (a, b):
            continue
        changed.append(field_name)
    return changed


def _is_mergeability_warmup(prev: ItemSnapshot, curr: ItemSnapshot) -> bool:
    """True when a CI change to or from `conflict` is only GitHub still computing mergeability.

    While `mergeable` is `UNKNOWN`, `ci_status` falls back to the check rollup,
    so it flips to `conflict` once the answer arrives. Only moves involving
    `conflict` are suppressed: a rollup change (green to red) is real.
    """
    if _MERGEABILITY_UNKNOWN not in (prev.mergeable, curr.mergeable):
        return False
    return "conflict" in (prev.ci_status, curr.ci_status)


def _new_history_tail(prev_history: str, curr_history: str) -> str:
    """Characters of `curr_history` that are new relative to `prev_history`.

    LCP-based. Returns "" when the history did not grow or when curr is
    shorter than prev (treated as a rewrite — see `_compare_fields`).
    """
    if curr_history == prev_history:
        return ""
    if curr_history.startswith(prev_history):
        return curr_history[len(prev_history) :]
    # History was rewritten (not just extended). Caller marks this via the
    # "history-rewritten" entry in changed_fields; we surface the whole
    # curr string as the tail so the renderer can bracket it unambiguously.
    return curr_history


def _infer_removal_reason(
    prev_item: ItemSnapshot,
    curr_snapshot: Snapshot,
    prev_snapshot: Snapshot,
    *,
    pushed_out: bool = False,
) -> str:
    """Best-effort reason why an item disappeared between snapshots.

    - "scope": the two snapshots were produced by different scope filters,
      so the item may just have been filtered out.
    - "limit": the current query matched more rows than `--limit` kept and
      the item sat in the last positions of the previous result, as many as
      rows were added (`pushed_out`), so it was probably pushed past the limit.
    - "left-queue": a review-queue row is gone. Usually the reviewer acted
      (approved, or the PR went on hold) rather than the PR closing.
    - "closed-or-gone": prev showed it open under a scope that still
      includes open items, so it was most likely closed (or deleted /
      transferred; the snapshot alone can't tell which).
    - "unknown": otherwise.
    """
    if prev_snapshot.scope_hash != curr_snapshot.scope_hash:
        return "scope"
    if curr_snapshot.has_more and pushed_out:
        return "limit"
    if prev_item.state == "open" and (
        curr_snapshot.scope.states is None or "open" in curr_snapshot.scope.states
    ):
        return "left-queue" if prev_snapshot.kind == KIND_REVIEW else "closed-or-gone"
    return "unknown"
