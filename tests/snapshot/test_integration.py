"""SnapshotPlan tests — covers --snapshot / --diff / --watch wiring."""

from __future__ import annotations

import pytest
from rich.console import Console

from src.snapshot import store
from src.snapshot.integration import SnapshotPlan
from src.snapshot.models import KIND_PR, SnapshotScope

from .conftest import make_item, make_snapshot


def test_from_args_returns_none_when_no_flags():
    assert (
        SnapshotPlan.from_args(kind=KIND_PR, snapshot_name=None, diff_name=None, watch_name=None)
        is None
    )


def test_from_args_watch_cannot_combine_with_snapshot_or_diff():
    with pytest.raises(ValueError):
        SnapshotPlan.from_args(kind=KIND_PR, snapshot_name="x", diff_name=None, watch_name="y")
    with pytest.raises(ValueError):
        SnapshotPlan.from_args(kind=KIND_PR, snapshot_name=None, diff_name="x", watch_name="y")


def test_watch_is_diff_and_save_under_same_name():
    plan = SnapshotPlan.from_args(
        kind=KIND_PR, snapshot_name=None, diff_name=None, watch_name="hourly"
    )
    assert plan is not None
    assert plan.wants_diff and plan.wants_save
    assert plan.diff_name == "hourly"
    assert plan.save_name == "hourly"


def test_save_persists_under_requested_name(tkt_home):  # noqa: ARG001
    plan = SnapshotPlan.from_args(
        kind=KIND_PR, snapshot_name="nightly", diff_name=None, watch_name=None
    )
    assert plan is not None
    snap = make_snapshot(name="whatever", items=[make_item(key="a/b#1")])
    plan.save(snap)
    loaded = store.load(KIND_PR, "nightly")
    assert loaded.name == "nightly"


def test_render_diff_with_missing_baseline_treats_all_as_new(tkt_home, capsys):  # noqa: ARG001
    plan = SnapshotPlan.from_args(
        kind=KIND_PR, snapshot_name=None, diff_name=None, watch_name="hourly"
    )
    assert plan is not None
    console = Console(width=200, color_system=None)
    curr = make_snapshot(items=[make_item(key="a/b#1", history="oC")])
    rc = plan.render_diff(curr, console)
    out = capsys.readouterr().out
    assert rc == 0
    assert "No snapshot pr/hourly" in out  # first-run warning
    assert "+1 new" in out


@pytest.mark.parametrize("output_format", ["table", "json"])
def test_scope_mismatch_blocks_without_force_in_both_formats(
    tkt_home,  # noqa: ARG001
    capsys,
    output_format,
):
    # Seed a baseline scoped to board=A, then diff with scope board=B.
    baseline = make_snapshot(
        kind=KIND_PR,
        name="hourly",
        items=[make_item(key="a/b#1", history="oC")],
        scope=SnapshotScope(board="A"),
    )
    store.save(baseline)
    plan = SnapshotPlan.from_args(
        kind=KIND_PR,
        snapshot_name=None,
        diff_name="hourly",
        watch_name=None,
        output_format=output_format,
    )
    assert plan is not None
    curr = make_snapshot(
        items=[make_item(key="a/b#1", history="oCr")],
        scope=SnapshotScope(board="B"),
    )
    rc = plan.render_diff(curr, Console(width=200, color_system=None))
    out = capsys.readouterr().out
    assert rc == 2
    assert "scope mismatch" in out
    assert "--diff-force" in out


def test_scope_mismatch_renders_with_force(tkt_home, capsys):  # noqa: ARG001
    baseline = make_snapshot(
        kind=KIND_PR,
        name="hourly",
        items=[make_item(key="a/b#1", history="oC")],
        scope=SnapshotScope(board="A"),
    )
    store.save(baseline)
    plan = SnapshotPlan.from_args(
        kind=KIND_PR,
        snapshot_name=None,
        diff_name="hourly",
        watch_name=None,
        force=True,
    )
    assert plan is not None
    curr = make_snapshot(
        items=[make_item(key="a/b#1", history="oCr")],
        scope=SnapshotScope(board="B"),
    )
    rc = plan.render_diff(curr, Console(width=200, color_system=None))
    out = capsys.readouterr().out
    assert rc == 0
    assert "[scope-changed]" in out


def _watch_plan(*, force: bool = False) -> SnapshotPlan:
    plan = SnapshotPlan.from_args(
        kind=KIND_PR, snapshot_name=None, diff_name=None, watch_name="hourly", force=force
    )
    assert plan is not None
    return plan


def test_execute_scope_mismatch_leaves_baseline_for_force_retry(tkt_home, capsys):  # noqa: ARG001
    store.save(
        make_snapshot(
            kind=KIND_PR,
            name="hourly",
            items=[make_item(key="a/b#1", history="oC")],
            scope=SnapshotScope(board="A"),
        )
    )
    curr = make_snapshot(
        items=[make_item(key="a/b#1", history="oCr")],
        scope=SnapshotScope(board="B"),
    )
    console = Console(width=200, color_system=None)

    assert _watch_plan().execute(curr, console, print_table=lambda: None) == 2
    baseline = store.load(KIND_PR, "hourly")
    assert baseline.scope.board == "A"
    assert baseline.items[0].history == "oC"
    capsys.readouterr()

    assert _watch_plan(force=True).execute(curr, console, print_table=lambda: None) == 0
    out = capsys.readouterr().out
    assert "*1 changed" in out
    assert "oC[r]" in out
    assert store.load(KIND_PR, "hourly").scope.board == "B"


def test_execute_snapshot_only_prints_table_and_saves(tkt_home):  # noqa: ARG001
    plan = SnapshotPlan.from_args(
        kind=KIND_PR, snapshot_name="nightly", diff_name=None, watch_name=None
    )
    assert plan is not None
    printed: list[bool] = []
    curr = make_snapshot(items=[make_item(key="a/b#1")])
    rc = plan.execute(curr, Console(), print_table=lambda: printed.append(True))
    assert rc == 0
    assert printed == [True]
    assert [it.key for it in store.load(KIND_PR, "nightly").items] == ["a/b#1"]
