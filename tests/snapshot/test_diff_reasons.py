"""Why a row is gone (`limit`, resolved states) and mergeability warm-up in the diff."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum

import pytest

from src.pr.models import CIStatus
from src.review.models import ReviewInfo, ReviewStatus
from src.snapshot.convert import item_from_review, snapshot_from_issues, snapshot_from_prs
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import ChangeKind, ItemSnapshot, Snapshot, SnapshotScope
from src.snapshot.resolve import resolve_removed

from .conftest import make_item, make_snapshot


def _items(*numbers: int, **kwargs) -> list[ItemSnapshot]:
    return [make_item(ref=f"o/r#{n}", **kwargs) for n in numbers]


def _reasons(prev: Snapshot, curr: Snapshot) -> dict[str, str | None]:
    return {
        d.ref: d.disappearance_reason
        for d in diff_snapshots(prev, curr).deltas
        if d.change is ChangeKind.REMOVED
    }


class TestLimitReason:
    def test_tail_row_of_a_truncated_result_is_limit(self):
        prev = make_snapshot(items=_items(3, 2, 1))
        curr = make_snapshot(items=_items(4, 3, 2), has_more=True)
        assert _reasons(prev, curr) == {"o/r#1": "limit"}

    def test_row_outside_the_tail_is_still_closed_or_gone(self):
        prev = make_snapshot(items=_items(3, 2, 1))
        curr = make_snapshot(items=_items(4, 3, 1), has_more=True)
        assert _reasons(prev, curr) == {"o/r#2": "closed-or-gone"}

    def test_tail_is_as_long_as_the_number_of_added_rows(self):
        prev = make_snapshot(items=_items(4, 3, 2, 1))
        curr = make_snapshot(items=_items(6, 5, 4, 3), has_more=True)
        assert _reasons(prev, curr) == {"o/r#2": "limit", "o/r#1": "limit"}

    def test_tail_row_of_a_complete_result_is_closed_or_gone(self):
        prev = make_snapshot(items=_items(3, 2, 1))
        curr = make_snapshot(items=_items(4, 3, 2))
        assert _reasons(prev, curr) == {"o/r#1": "closed-or-gone"}

    def test_truncated_result_with_nothing_added_is_not_limit(self):
        prev = make_snapshot(items=_items(3, 2, 1))
        curr = make_snapshot(items=_items(3, 2), has_more=True)
        assert _reasons(prev, curr) == {"o/r#1": "closed-or-gone"}

    def test_review_row_pushed_past_the_limit_is_limit_not_left_queue(self):
        prev = make_snapshot(kind="review", items=_items(3, 2, 1))
        curr = make_snapshot(kind="review", items=_items(4, 3, 2), has_more=True)
        assert _reasons(prev, curr) == {"o/r#1": "limit"}

    def test_scope_change_wins_over_limit(self):
        prev = make_snapshot(items=_items(2, 1), scope=SnapshotScope(board="a"))
        curr = make_snapshot(items=_items(3, 2), scope=SnapshotScope(board="b"), has_more=True)
        assert _reasons(prev, curr) == {"o/r#1": "scope"}


class TestSnapshotHasMore:
    def test_round_trips(self):
        snap = make_snapshot(items=_items(1), has_more=True)
        assert Snapshot.from_dict(snap.to_dict(), "pr", "n").has_more is True

    def test_is_always_written(self):
        data = make_snapshot(items=_items(1)).to_dict()
        assert data["has_more"] is False
        assert Snapshot.from_dict(data, "pr", "n").has_more is False

    def test_convert_records_has_more(self):
        assert snapshot_from_prs([], scope=SnapshotScope(), name="n", has_more=True).has_more
        assert snapshot_from_issues([], scope=SnapshotScope(), name="n", has_more=True).has_more
        assert not snapshot_from_prs([], scope=SnapshotScope(), name="n").has_more


class _State(Enum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


@dataclass
class _Info:
    repo: str
    number: int
    state: _State


class TestResolveRemoved:
    def _gone(self, *numbers: int):
        return diff_snapshots(make_snapshot(items=_items(*numbers)), make_snapshot(items=[]))

    def test_replaces_each_reason_with_the_current_state(self):
        calls: list[list[str]] = []

        def fetch(refs: list[str]):
            calls.append(refs)
            return [_Info("o/r", 1, _State.MERGED), _Info("o/r", 2, _State.OPEN)]

        resolved = resolve_removed(self._gone(1, 2, 3), fetch)
        assert {d.ref: d.disappearance_reason for d in resolved.deltas} == {
            "o/r#1": "merged",
            "o/r#2": "still-open",
            "o/r#3": "not-found",
        }
        assert calls == [["o/r#1", "o/r#2", "o/r#3"]]

    def test_closed_state(self):
        resolved = resolve_removed(self._gone(1), lambda _: [_Info("o/r", 1, _State.CLOSED)])
        assert resolved.deltas[0].disappearance_reason == "closed"

    def test_matches_refs_ignoring_case(self):
        resolved = resolve_removed(self._gone(1), lambda _: [_Info("O/R", 1, _State.CLOSED)])
        assert resolved.deltas[0].disappearance_reason == "closed"

    def test_leaves_other_rows_alone_and_does_not_look_up_without_gone_rows(self):
        prev = make_snapshot(items=_items(1, 2))
        curr = make_snapshot(items=_items(2, 3))
        diff = diff_snapshots(prev, curr)

        def fetch(refs: list[str]):
            assert refs == ["o/r#1"]
            return [_Info("o/r", 1, _State.CLOSED)]

        resolved = resolve_removed(diff, fetch)
        assert [d.change for d in resolved.deltas] == [d.change for d in diff.deltas]
        assert {d.ref: d.disappearance_reason for d in resolved.deltas if d.curr is None} == {
            "o/r#1": "closed"
        }

        def fail(_: list[str]):
            raise AssertionError("no row is gone")

        unchanged = diff_snapshots(prev, prev)
        assert resolve_removed(unchanged, fail) is unchanged


def _pr(**kwargs) -> ItemSnapshot:
    defaults = {"head": "a" * 40, "mergeable": "MERGEABLE", "merge_state": "CLEAN"}
    return replace(make_item(), **{**defaults, **kwargs})


def _changed(prev: ItemSnapshot, curr: ItemSnapshot) -> tuple[str, ...]:
    return (
        diff_snapshots(make_snapshot(items=[prev]), make_snapshot(items=[curr]))
        .deltas[0]
        .changed_fields
    )


class TestMergeabilityWarmUp:
    @pytest.mark.parametrize(
        ("prev", "curr"),
        [
            ({"mergeable": "UNKNOWN", "ci": "green"}, {"ci": "conflict"}),
            ({"ci": "conflict"}, {"mergeable": "UNKNOWN", "ci": "green"}),
            ({"mergeable": "UNKNOWN", "ci": "red"}, {"ci": "conflict"}),
            ({"ci": "pending"}, {"mergeable": "UNKNOWN", "ci": "conflict"}),
        ],
    )
    def test_conflict_appearing_or_clearing_around_unknown_is_not_a_change(self, prev, curr):
        assert _changed(_pr(**prev), _pr(**curr)) == ()

    def test_unknown_to_conflicting_leaves_the_row_unchanged(self):
        prev = _pr(mergeable="UNKNOWN", merge_state="UNKNOWN", ci="green")
        curr = _pr(mergeable="CONFLICTING", merge_state="DIRTY", ci="conflict")
        [delta] = diff_snapshots(make_snapshot(items=[prev]), make_snapshot(items=[curr])).deltas
        assert delta.change is ChangeKind.UNCHANGED

    def test_a_real_conflict_between_known_states_is_still_flagged(self):
        prev = _pr(ci="green")
        curr = _pr(mergeable="CONFLICTING", merge_state="DIRTY", ci="conflict")
        assert _changed(prev, curr) == ("ci", "merge_state", "mergeable")

    def test_a_rollup_change_while_unknown_is_still_flagged(self):
        prev = _pr(mergeable="UNKNOWN", ci="green")
        assert _changed(prev, _pr(ci="red")) == ("ci",)

    def test_a_new_conflict_after_a_push_is_flagged_by_the_head_change(self):
        prev = _pr(ci="green")
        curr = _pr(head="b" * 40, mergeable="UNKNOWN", ci="conflict")
        assert "head" in _changed(prev, curr)

    def test_review_rows_record_mergeable_for_the_same_rule(self):
        def row(mergeable: str, ci: CIStatus) -> ItemSnapshot:
            return item_from_review(
                ReviewInfo(
                    repo="o/r",
                    number=1,
                    title="t",
                    history="oC",
                    status=ReviewStatus.REVIEW,
                    wait_seconds=1.0,
                    ci_status=ci,
                    unresolved_thread_count=0,
                    author="a",
                    last_activity=datetime(2026, 10, 1, tzinfo=UTC),
                    created_at=datetime(2026, 10, 1, tzinfo=UTC),
                    mergeable=mergeable,
                )
            )

        prev, curr = row("UNKNOWN", CIStatus.GREEN), row("CONFLICTING", CIStatus.CONFLICT)
        assert prev.mergeable == "UNKNOWN"
        assert _changed(prev, curr) == ()
