"""Renderer tests — assert the Δ column, bracketed tail, and summary line."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from rich.console import Console

from src.snapshot.diff import diff_snapshots
from src.snapshot.models import (
    ChangeKind,
    ItemDelta,
    SnapshotScope,
    WindowScope,
    _delta_to_dict,
)
from src.snapshot.render import _render_note, render_diff

from .conftest import make_item, make_snapshot


def _capture(diff, **kw) -> str:
    buf = io.StringIO()
    console = Console(file=buf, width=200, color_system=None, record=False, highlight=False)
    render_diff(diff, console=console, **kw)
    return buf.getvalue()


def test_table_renders_added_glyph_and_bracketed_history():
    prev = make_snapshot(items=[])
    curr = make_snapshot(items=[make_item(key="a/b#1", history="oCr")])
    out = _capture(diff_snapshots(prev, curr))
    assert "+ " in out  # added glyph (color stripped)
    assert "[oCr]" in out  # whole history bracketed for new row


def test_table_renders_only_new_tail_bracketed_for_changed_row():
    prev = make_snapshot(items=[make_item(key="a/b#1", history="oRfA")])
    curr = make_snapshot(items=[make_item(key="a/b#1", history="oRfAfR")])
    out = _capture(diff_snapshots(prev, curr))
    assert "oRfA[fR]" in out
    assert "[oRfAfR]" not in out  # only tail, not whole


@pytest.mark.parametrize("kind", ["pr", "issue", "review"])
def test_activity_without_history_growth_marks_last_column_changed(kind):
    recent = (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = make_snapshot(kind=kind, items=[make_item(key="a/b#1", history="oc")])
    curr = make_snapshot(
        kind=kind, items=[make_item(key="a/b#1", history="oc", last_activity=recent)]
    )
    out = _capture(diff_snapshots(prev, curr))
    row = next(line for line in out.splitlines() if "a/b" in line)
    assert row.lstrip().startswith("* ")
    assert " oc " in row  # history shown with no bracketed tail
    assert "5m ago!" in row


def test_table_shows_removed_glyph_and_gone_note():
    prev = make_snapshot(items=[make_item(key="a/b#1")])
    curr = make_snapshot(items=[])
    out = _capture(diff_snapshots(prev, curr))
    gone_row = next(line for line in out.splitlines() if line.lstrip().startswith("- "))
    assert "a/b" in gone_row and "#1" in gone_row


@pytest.mark.parametrize(
    ("kind", "prev_state", "curr_scope", "label"),
    [
        ("pr", "open", SnapshotScope(), "closed?"),
        ("issue", "open", SnapshotScope(), "closed?"),
        ("review", "open", SnapshotScope(), "done?"),
        ("pr", "open", SnapshotScope(author="someone-else"), "scope"),
        ("pr", "merged", SnapshotScope(), "?"),
    ],
)
def test_gone_row_note_is_a_short_hint_per_reason(kind, prev_state, curr_scope, label):
    prev = make_snapshot(kind=kind, items=[make_item(key="a/b#1", state=prev_state)])
    curr = make_snapshot(kind=kind, items=[], scope=curr_scope)
    out = _capture(diff_snapshots(prev, curr), output_format="table")
    gone_row = next(line for line in out.splitlines() if line.lstrip().startswith("- "))
    assert gone_row.split()[-1] == label
    assert "(gone:" not in out


def _ago(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_summary_line_shows_relative_times_and_counts():
    prev = make_snapshot(
        items=[make_item(key="a/b#1", history="oC")], name="hourly", captured_at=_ago(hours=2)
    )
    curr = make_snapshot(
        items=[make_item(key="a/b#1", history="oCr"), make_item(key="a/b#2")],
        name="hourly",
        captured_at=_ago(minutes=5),
    )
    header = _capture(diff_snapshots(prev, curr)).splitlines()[0]
    assert header.startswith("diff pr/hourly: 2h ago → 5m ago  (+1 new, *1 changed, -0 gone")
    assert len(header) <= 80


def test_summary_line_names_both_snapshots_when_they_differ():
    prev = make_snapshot(name="monday", captured_at=_ago(days=3))
    curr = make_snapshot(name="current", captured_at=_ago(minutes=1))
    header = _capture(diff_snapshots(prev, curr)).splitlines()[0]
    assert header.startswith("diff pr/monday (3d ago) → current (1m ago)  (")


def test_unchanged_rows_hidden_by_default():
    prev = make_snapshot(items=[make_item(key="a/b#1")])
    curr = make_snapshot(items=[make_item(key="a/b#1")])  # unchanged
    out = _capture(diff_snapshots(prev, curr))
    assert "No changes." in out


def test_unchanged_rows_shown_with_show_unchanged():
    prev = make_snapshot(items=[make_item(key="a/b#1", history="oC")])
    curr = make_snapshot(items=[make_item(key="a/b#1", history="oC")])
    out = _capture(diff_snapshots(prev, curr), show_unchanged=True)
    assert "a/b" in out  # unchanged row rendered


def test_json_format_emits_parseable_payload():
    prev = make_snapshot(items=[make_item(key="a/b#1", history="oC")])
    curr = make_snapshot(items=[make_item(key="a/b#1", history="oCr")])
    out = _capture(diff_snapshots(prev, curr), output_format="json")
    data = json.loads(out)
    assert data["counts"]["changed"] == 1
    assert data["deltas"][0]["new_history_tail"] == "r"


def test_issue_table_rendered_with_labels_and_linked_pr():
    prev = make_snapshot(
        kind="issue",
        items=[make_item(key="a/b#1", history="oC", labels=("bug",))],
    )
    curr = make_snapshot(
        kind="issue",
        items=[
            make_item(
                key="a/b#1",
                history="oCL",
                labels=("bug", "urgent"),
                linked_pr="a/b#42",
            )
        ],
    )
    out = _capture(diff_snapshots(prev, curr))
    assert "oC[L]" in out
    assert "#42" in out
    # Changed label field renders with the ! suffix
    assert "bug,urgent!" in out


def _narrow_diff(kind: str):
    status = "review" if kind == "review" else None
    prev = [
        make_item(key="OpenHands/OpenHands#11250", history="oCRfA", review_status=status),
        make_item(key="OpenHands/infra#87", history="oCax", review_status=status),
    ]
    curr = [
        make_item(key="OpenHands/OpenHands#11250", history="oCRfAfR", review_status=status),
        make_item(key="OpenHands/docs#42", history="oCL", review_status=status),
    ]
    return diff_snapshots(
        make_snapshot(kind=kind, items=prev), make_snapshot(kind=kind, items=curr)
    )


@pytest.mark.parametrize("kind", ["pr", "issue", "review"])
@pytest.mark.parametrize("is_terminal", [False, True])
def test_80_columns_keeps_glyph_number_history_tail_and_note(kind, is_terminal):
    buf = io.StringIO()
    console = Console(file=buf, width=80, color_system=None, force_terminal=is_terminal)
    render_diff(_narrow_diff(kind), console=console)
    rows = {line.split()[0]: line for line in buf.getvalue().splitlines() if line[:3].strip()}

    assert "#42" in rows["+"] and "[oCL]" in rows["+"]
    assert "#11250" in rows["*"] and "oCRfA[fR]" in rows["*"]
    assert "#87" in rows["-"] and rows["-"].split()[-1] == (
        "done?" if kind == "review" else "closed?"
    )
    assert console.width == 80
    if is_terminal:
        assert max(len(line) for line in buf.getvalue().splitlines()) <= 80
    else:
        assert "OpenHands/OpenHands" in rows["*"]  # piped output is never truncated


@pytest.mark.parametrize("kind", ["pr", "issue", "review"])
def test_80_columns_crops_a_long_history_with_the_crop_mark_not_rich_ellipsis(kind):
    status = "review" if kind == "review" else None
    long_history = "o" + "cC" * 40
    prev = make_snapshot(
        kind=kind, items=[make_item(key="o/r#1", history=long_history, review_status=status)]
    )
    curr = make_snapshot(
        kind=kind, items=[make_item(key="o/r#1", history=long_history + "f", review_status=status)]
    )
    buf = io.StringIO()
    console = Console(file=buf, width=80, color_system=None, force_terminal=True)
    render_diff(diff_snapshots(prev, curr), console=console)
    out = buf.getvalue()
    row = next(line for line in out.splitlines() if "#1" in line)

    cell = next(token for token in row.split() if token.startswith("oc"))
    assert "#1" in row
    assert cell.endswith(">") and "…" not in cell
    assert "History cropped to fit the terminal" in out
    assert console.width == 80


def test_wide_terminal_diff_has_no_crop_and_no_legend():
    long_history = "o" + "cC" * 40
    prev = make_snapshot(items=[make_item(key="o/r#1", history=long_history)])
    curr = make_snapshot(items=[make_item(key="o/r#1", history=long_history + "f")])
    buf = io.StringIO()
    console = Console(file=buf, width=200, color_system=None, force_terminal=True)
    render_diff(diff_snapshots(prev, curr), console=console)
    assert long_history + "[f]" in buf.getvalue()
    assert "History cropped" not in buf.getvalue()


def _windowed(window: WindowScope | None, **kw):
    return make_snapshot(scope=SnapshotScope(board="oh", window=window), **kw)


def test_summary_names_the_window_when_both_snapshots_share_it():
    window = WindowScope(field="merged", since_days=14)
    out = _capture(diff_snapshots(_windowed(window), _windowed(window)))
    lines = out.splitlines()
    assert "scope-changed" not in lines[0]
    assert lines[1] == "window: merged since 14d ago"


def test_summary_explains_a_scope_change_caused_by_the_window():
    prev = _windowed(WindowScope(field="merged", since_days=14))
    curr = _windowed(WindowScope(field="merged", since_days=3))
    lines = _capture(diff_snapshots(prev, curr)).splitlines()
    assert "[scope-changed]" in lines[0]
    assert lines[1] == "window: merged since 14d ago → merged since 3d ago"


def test_summary_reports_a_window_added_or_removed():
    window = WindowScope(field="updated", after="2026-08-01")
    added = _capture(diff_snapshots(_windowed(None), _windowed(window))).splitlines()
    assert added[1] == "window: none → updated ≥ 2026-08-01"
    removed = _capture(diff_snapshots(_windowed(window), _windowed(None))).splitlines()
    assert removed[1] == "window: updated ≥ 2026-08-01 → none"


def test_summary_has_no_window_line_without_a_window():
    out = _capture(diff_snapshots(_windowed(None), _windowed(None)))
    assert "window:" not in out


def _note_for(**changes) -> str:
    item = make_item(key="a/b#1")
    delta = ItemDelta(key="a/b#1", kind=ChangeKind.CHANGED, prev=item, curr=item, **changes)
    return _render_note(delta)


def test_note_joins_several_step_changes_with_semicolons():
    note = _note_for(
        step_changes=("fix CI: waiting → done", "address review findings: done → needed")
    )
    assert "fix CI: waiting → done; address review findings: done → needed" in note


def test_note_joins_reviewer_and_step_changes_with_semicolons():
    note = _note_for(
        reviewer_changes=("bob ↻ re-requested",),
        step_changes=("request re-review: done → needed",),
    )
    assert "bob ↻ re-requested; request re-review: done → needed" in note


def test_note_with_a_single_part_has_no_separator():
    assert ";" not in _note_for(step_changes=("fix CI: waiting → done",))


def test_json_step_changes_stay_a_list():
    item = make_item(key="a/b#1")
    delta = ItemDelta(
        key="a/b#1",
        kind=ChangeKind.CHANGED,
        prev=item,
        curr=item,
        step_changes=("a: x → y", "b: y → z"),
    )
    assert _delta_to_dict(delta)["step_changes"] == ["a: x → y", "b: y → z"]


@pytest.mark.parametrize("kind", ["pr", "issue", "review"])
def test_piped_header_and_notes_do_not_depend_on_width(kind):
    outs = []
    for width in (30, 200):
        buf = io.StringIO()
        console = Console(file=buf, width=width, color_system=None)
        render_diff(_narrow_diff(kind), console=console)
        outs.append(buf.getvalue())
    assert outs[0] == outs[1]
    lines = outs[0].splitlines()
    assert sum(line.startswith("diff ") for line in lines) == 1
    assert sum(line.startswith("Δ:") and "Step notes:" in line for line in lines) == 1


def test_piped_no_changes_line_does_not_depend_on_width():
    snap = make_snapshot(items=[make_item(key="a/b#1", history="oC")])
    outs = []
    for width in (10, 200):
        buf = io.StringIO()
        render_diff(
            diff_snapshots(snap, snap), console=Console(file=buf, width=width, color_system=None)
        )
        outs.append(buf.getvalue())
    assert outs[0] == outs[1]
    assert outs[0].splitlines()[-1] == "No changes."


def test_terminal_footer_still_wraps():
    buf = io.StringIO()
    console = Console(file=buf, width=60, force_terminal=True, color_system=None)
    render_diff(_narrow_diff("pr"), console=console)
    lines = buf.getvalue().splitlines()
    assert not any(line.startswith("Δ:") and "Step notes:" in line for line in lines)
    assert any(line.startswith("Δ:") for line in lines)
