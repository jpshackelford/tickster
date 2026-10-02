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


def test_show_json_format_is_parseable(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_show("pr/hourly", output_format="json")
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["kind"] == "pr"
    assert len(data["items"]) == 2


def test_show_rejects_bad_ref(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_show("bogus-no-slash")
    assert rc == 2
    assert "Error" in capsys.readouterr().out


def test_show_rejects_unknown_kind(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_show("bogus/hourly")
    assert rc == 2
    assert "Error" in capsys.readouterr().out


def test_rm_removes_snapshots(seed, capsys):  # noqa: ARG001
    assert store.exists("pr", "hourly")
    rc = cli.cmd_rm(["pr/hourly"])
    assert rc == 0
    assert not store.exists("pr", "hourly")
    assert "removed pr/hourly" in capsys.readouterr().out


def test_rm_reports_missing(seed, capsys):  # noqa: ARG001
    rc = cli.cmd_rm(["pr/nope"])
    assert rc == 1
    assert "not found" in capsys.readouterr().out


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
    out = capsys.readouterr().out
    assert rc == 2
    assert "cannot diff across kinds" in out
