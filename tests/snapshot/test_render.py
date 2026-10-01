"""Renderer tests — assert the Δ column, bracketed tail, and summary line."""

from __future__ import annotations

import io
import json

from rich.console import Console

from src.snapshot.diff import diff_snapshots
from src.snapshot.render import render_diff

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


def test_table_shows_removed_glyph_and_gone_note():
    prev = make_snapshot(items=[make_item(key="a/b#1")])
    curr = make_snapshot(items=[])
    out = _capture(diff_snapshots(prev, curr))
    assert "- " in out
    assert "gone:" in out


def test_summary_line_shows_counts():
    prev = make_snapshot(items=[make_item(key="a/b#1", history="oC")])
    curr = make_snapshot(
        items=[
            make_item(key="a/b#1", history="oCr"),
            make_item(key="a/b#2"),
        ]
    )
    out = _capture(diff_snapshots(prev, curr))
    assert "diff:" in out
    assert "+1 new" in out
    assert "*1 changed" in out


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
