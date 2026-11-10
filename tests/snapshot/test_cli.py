"""`tkt snapshot {list,show,rm,diff}` CLI tests."""

from __future__ import annotations

import json

import pytest

from src.snapshot import store
from src.snapshot.cli import commands as cli

from .conftest import make_item, make_snapshot


@pytest.fixture
def seed(tkt_home):  # noqa: ARG001
    store.save(
        make_snapshot(
            kind="pr",
            name="hourly",
            items=[
                make_item(key="a/b#1", history="oC"),
                make_item(key="a/b#2", history="oCr"),
            ],
        )
    )
    store.save(
        make_snapshot(
            kind="pr",
            name="later",
            items=[
                make_item(key="a/b#2", history="oCrfA"),
                make_item(key="a/b#3", history="o"),
            ],
        )
    )
    return tkt_home


def test_list_shows_stored_snapshots(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_list()
    out = capsys.readouterr().out
    assert rc == 0
    assert "pr/hourly" in out
    assert "pr/later" in out


def test_list_filtered_by_kind_hides_other_kinds(seed, capsys):  # noqa: ARG001
    store.save(make_snapshot(kind="issue", name="hourly", items=[make_item()]))
    cli.cmd_list(kind="pr")
    out = capsys.readouterr().out
    assert "pr/hourly" in out
    assert "issue/hourly" not in out


def test_show_table_format(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_show("pr/hourly")
    out = capsys.readouterr().out
    assert rc == 0
    assert "pr/hourly" in out
    rows = [line for line in out.splitlines() if "a/b" in line]
    assert len(rows) == 2
    assert all(line.rstrip().endswith(" ago") for line in rows)
    assert "2026-09-30T22:00:00Z" not in "\n".join(rows)


def test_show_json_format_is_parseable(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_show("pr/hourly", output_format="json")
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["kind"] == "pr"
    assert len(data["items"]) == 2


def test_show_rejects_bad_ref(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_show("bogus-no-slash")
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err.startswith("Error: ")


def test_show_rejects_unknown_kind(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_show("bogus/hourly")
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err.startswith("Error: ")


def test_rm_removes_snapshots(seed, capsys):  # noqa: ARG001
    assert store.exists("pr", "hourly")
    rc = cli.cmd_rm(["pr/hourly"])
    assert rc == 0
    assert not store.exists("pr", "hourly")
    assert "removed pr/hourly" in capsys.readouterr().out


def test_rm_reports_missing(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_rm(["pr/nope"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not found" in captured.err


@pytest.mark.parametrize(
    "refs",
    [
        ["bogus-no-slash", "pr/nope"],  # parse error first, then not-found
        ["pr/nope", "bogus-no-slash"],  # not-found first, then parse error
    ],
)
def test_rm_exit_code_is_max_severity_regardless_of_order(seed, refs):  # noqa: ARG001
    # Parse error (2) should always dominate not-found (1), independent of argv order.
    assert cli.cmd_rm(refs) == 2


def test_diff_two_snapshots_renders_changes(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_diff("pr/hourly", "pr/later")
    out = capsys.readouterr().out
    assert rc == 0
    # a/b#2 history grew: "oCr" -> "oCrfA", so tail is "fA"
    assert "oCr[fA]" in out
    # a/b#3 is new
    assert "+1 new" in out
    # a/b#1 disappeared
    assert "-1 gone" in out


def test_diff_rejects_cross_kind(seed, capsys):  # noqa: ARG001
    store.save(make_snapshot(kind="issue", name="hourly", items=[]))
    rc = cli.cmd_diff("pr/hourly", "issue/hourly")
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert "cannot diff across kinds" in captured.err


def test_diff_json_errors_go_to_stderr(seed, capsys):  # noqa: ARG001
    store.save(make_snapshot(kind="issue", name="hourly", items=[]))
    rc = cli.cmd_diff("pr/hourly", "issue/hourly", output_format="json")
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert "cannot diff across kinds" in captured.err
    rc = cli.cmd_diff("pr/hourly", "pr/nope", output_format="json")
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "Error" in captured.err


def _corrupt(seed, name: str = "broken") -> str:  # noqa: ARG001
    path = store.snapshots_dir() / f"pr-{name}.json"
    path.write_text('{"kind": "pr", "name": "broken", "items": [')
    return str(path)


def test_show_corrupt_snapshot_is_one_error_line_on_stderr(seed, capsys):
    path = _corrupt(seed)
    assert cli.cmd_show("pr/broken", output_format="json") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("Error: snapshot pr/broken cannot be read (")
    assert path in captured.err
    assert "Traceback" not in captured.err


def test_list_with_a_corrupt_file_still_lists_the_others(seed, capsys, caplog):
    _corrupt(seed)
    assert cli.cmd_list() == 0
    out = capsys.readouterr().out
    assert "pr/hourly" in out and "pr/later" in out
    assert [r.levelname for r in caplog.records] == ["WARNING"]


def test_diff_with_a_corrupt_snapshot_is_an_error_on_stderr(seed, capsys):
    _corrupt(seed)
    assert cli.cmd_diff("pr/hourly", "pr/broken", output_format="json") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "snapshot pr/broken cannot be read" in captured.err


def test_diff_header_names_the_kind_of_both_snapshots(seed, capsys):  # noqa: ARG001
    assert cli.cmd_diff("pr/hourly", "pr/later") == 0
    assert "→ pr/later (" in capsys.readouterr().out.splitlines()[0]
