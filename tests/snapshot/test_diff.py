"""Diff engine tests."""

from __future__ import annotations

import pytest

from src.snapshot.diff import diff_snapshots
from src.snapshot.models import ChangeKind, SnapshotScope

from .conftest import make_item, make_snapshot


def test_added_item_marked_added_with_full_history_as_tail():
    prev = make_snapshot(items=[make_item(key="a/b#1", history="oC")])
    curr = make_snapshot(
        items=[
            make_item(key="a/b#1", history="oC"),
            make_item(key="a/b#2", history="oCr"),
        ]
    )
    result = diff_snapshots(prev, curr)
    by_key = {d.key: d for d in result.deltas}
    assert by_key["a/b#2"].kind is ChangeKind.ADDED
    assert by_key["a/b#2"].new_history_tail == "oCr"
    assert by_key["a/b#1"].kind is ChangeKind.UNCHANGED


def test_removed_item_marked_removed_with_reason():
    prev = make_snapshot(items=[make_item(key="a/b#1", state="open")])
    curr = make_snapshot(items=[])
    result = diff_snapshots(prev, curr)
    delta = result.deltas[0]
    assert delta.kind is ChangeKind.REMOVED
    # Prev was open and curr still has an open-including scope → closed-or-gone
    assert delta.disappearance_reason == "closed-or-gone"


def test_removed_review_row_reason_is_left_queue():
    # Review rows leave the queue mostly because the reviewer acted, not because the PR closed.
    prev = make_snapshot(kind="review", items=[make_item(key="a/b#1", state="open")])
    curr = make_snapshot(kind="review", items=[])
    assert diff_snapshots(prev, curr).deltas[0].disappearance_reason == "left-queue"


def test_removed_item_scope_mismatch_reason_is_scope():
    prev = make_snapshot(items=[make_item(key="a/b#1")], scope=SnapshotScope(board="oh"))
    curr = make_snapshot(items=[], scope=SnapshotScope(board="other"))
    result = diff_snapshots(prev, curr)
    assert result.scope_matches is False
    assert result.deltas[0].disappearance_reason == "scope"


def test_history_grew_tail_is_only_new_characters():
    prev = make_snapshot(items=[make_item(key="a/b#1", history="oRfA")])
    curr = make_snapshot(items=[make_item(key="a/b#1", history="oRfAfR")])
    result = diff_snapshots(prev, curr)
    delta = result.deltas[0]
    assert delta.kind is ChangeKind.CHANGED
    assert delta.new_history_tail == "fR"
    assert "history" in delta.changed_fields
    assert "history-rewritten" not in delta.changed_fields


def test_history_rewritten_flagged_when_prev_not_prefix_of_curr():
    prev = make_snapshot(items=[make_item(key="a/b#1", history="oCxr")])
    curr = make_snapshot(items=[make_item(key="a/b#1", history="oLx")])
    delta = diff_snapshots(prev, curr).deltas[0]
    assert delta.kind is ChangeKind.CHANGED
    assert "history-rewritten" in delta.changed_fields
    # Fallback: whole curr.history surfaces as the tail so the renderer
    # brackets the entire string.
    assert delta.new_history_tail == "oLx"


def test_label_set_equality_ignores_order():
    prev = make_snapshot(items=[make_item(key="a/b#1", labels=("bug", "p1"))])
    curr = make_snapshot(items=[make_item(key="a/b#1", labels=("p1", "bug"))])
    delta = diff_snapshots(prev, curr).deltas[0]
    assert delta.kind is ChangeKind.UNCHANGED


def test_ci_status_change_detected():
    prev = make_snapshot(items=[make_item(key="a/b#1", ci_status="green")])
    curr = make_snapshot(items=[make_item(key="a/b#1", ci_status="red")])
    delta = diff_snapshots(prev, curr).deltas[0]
    assert delta.kind is ChangeKind.CHANGED
    assert "ci_status" in delta.changed_fields


def test_unresolved_thread_count_change_detected():
    prev = make_snapshot(items=[make_item(key="a/b#1", unresolved=0)])
    curr = make_snapshot(items=[make_item(key="a/b#1", unresolved=3)])
    delta = diff_snapshots(prev, curr).deltas[0]
    assert "unresolved_thread_count" in delta.changed_fields


def test_cross_kind_diff_rejected():
    prev = make_snapshot(kind="pr", items=[])
    curr = make_snapshot(kind="issue", items=[])
    with pytest.raises(ValueError):
        diff_snapshots(prev, curr)


def test_counts_match_deltas():
    prev = make_snapshot(
        items=[
            make_item(key="a/b#1", history="oC"),
            make_item(key="a/b#2", history="oC"),
        ]
    )
    curr = make_snapshot(
        items=[
            make_item(key="a/b#2", history="oCr"),
            make_item(key="a/b#3", history="o"),
        ]
    )
    result = diff_snapshots(prev, curr)
    counts = result.counts
    assert counts[ChangeKind.ADDED] == 1  # a/b#3
    assert counts[ChangeKind.CHANGED] == 1  # a/b#2
    assert counts[ChangeKind.REMOVED] == 1  # a/b#1
    assert counts[ChangeKind.UNCHANGED] == 0


def test_deltas_sorted_added_changed_removed_unchanged():
    prev = make_snapshot(
        items=[
            make_item(key="a/b#1"),
            make_item(key="a/b#2", history="oC"),
            make_item(key="a/b#4"),
        ]
    )
    curr = make_snapshot(
        items=[
            make_item(key="a/b#1"),  # unchanged
            make_item(key="a/b#2", history="oCr"),  # changed
            make_item(key="a/b#3"),  # added
            # a/b#4 removed
        ]
    )
    deltas = diff_snapshots(prev, curr).deltas
    kinds = [d.kind for d in deltas]
    # Everything added comes first, then changed, then removed, then unchanged
    added = [i for i, k in enumerate(kinds) if k is ChangeKind.ADDED]
    changed = [i for i, k in enumerate(kinds) if k is ChangeKind.CHANGED]
    removed = [i for i, k in enumerate(kinds) if k is ChangeKind.REMOVED]
    unchanged = [i for i, k in enumerate(kinds) if k is ChangeKind.UNCHANGED]
    assert max(added) < min(changed)
    assert max(changed) < min(removed)
    assert max(removed) < min(unchanged)


def test_diff_result_json_contains_counts_and_scope_match():
    prev = make_snapshot(
        items=[make_item(key="a/b#1", history="oC")],
        scope=SnapshotScope(board="oh"),
    )
    curr = make_snapshot(
        items=[make_item(key="a/b#1", history="oCr")],
        scope=SnapshotScope(board="oh"),
    )
    out = diff_snapshots(prev, curr).to_dict()
    assert out["scope_matches"] is True
    assert out["counts"]["changed"] == 1
    assert out["deltas"][0]["new_history_tail"] == "r"


def test_diff_result_json_skips_bodies_for_unchanged_deltas():
    # UNCHANGED deltas would otherwise emit identical prev + curr bodies for
    # every row — on a 100-row snapshot, that's ~200 full items to describe
    # "nothing happened". Keep the delta entry (for schema stability) but
    # drop the bodies.
    prev = make_snapshot(
        items=[
            make_item(key="a/b#1", history="oC"),
            make_item(key="a/b#2", history="oCr"),
        ]
    )
    curr = make_snapshot(
        items=[
            make_item(key="a/b#1", history="oC"),  # unchanged
            make_item(key="a/b#2", history="oCrfA"),  # changed
        ]
    )
    deltas = diff_snapshots(prev, curr).to_dict()["deltas"]
    by_key = {d["key"]: d for d in deltas}
    assert by_key["a/b#1"]["kind"] == "unchanged"
    assert by_key["a/b#1"]["prev"] is None
    assert by_key["a/b#1"]["curr"] is None
    # Changed deltas still carry bodies.
    assert by_key["a/b#2"]["prev"] is not None
    assert by_key["a/b#2"]["curr"] is not None
