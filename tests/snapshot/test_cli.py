"""`tkt snapshot {list,show,rm,diff}` CLI tests."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

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
                make_item(ref="a/b#1", history="oC"),
                make_item(ref="a/b#2", history="oCr"),
            ],
        )
    )
    store.save(
        make_snapshot(
            kind="pr",
            name="later",
            items=[
                make_item(ref="a/b#2", history="oCrfA"),
                make_item(ref="a/b#3", history="o"),
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


def _notices(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("tkt: discarded")]


def _corrupt(seed, name: str = "broken") -> str:  # noqa: ARG001
    path = store.snapshots_dir() / f"pr-{name}.json"
    path.write_text('{"kind": "pr", "name": "broken", "items": [')
    return str(path)


def test_show_corrupt_snapshot_is_discarded_with_a_notice_and_reported_missing(
    seed, capsys, caplog
):
    path = _corrupt(seed)
    assert cli.cmd_show("pr/broken", output_format="json") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert captured.err.startswith("Error: snapshot not found: pr/broken")
    [notice] = _notices(caplog)
    assert notice.startswith("tkt: discarded snapshot pr/broken: invalid JSON")
    assert "Traceback" not in captured.err
    assert not Path(path).exists()


def test_list_with_a_corrupt_file_still_lists_the_others(seed, capsys, caplog):
    _corrupt(seed)
    assert cli.cmd_list() == 0
    out = capsys.readouterr().out
    assert "pr/hourly" in out and "pr/later" in out
    assert [r.levelname for r in caplog.records] == ["WARNING"]


def test_diff_with_a_corrupt_snapshot_is_an_error_on_stderr(seed, capsys, caplog):
    _corrupt(seed)
    assert cli.cmd_diff("pr/hourly", "pr/broken", output_format="json") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "snapshot not found: pr/broken" in captured.err
    [notice] = _notices(caplog)
    assert notice.startswith("tkt: discarded snapshot pr/broken: invalid JSON")


def test_diff_header_names_the_kind_of_both_snapshots(seed, capsys):  # noqa: ARG001
    assert cli.cmd_diff("pr/hourly", "pr/later") == 0
    assert "→ pr/later (" in capsys.readouterr().out.splitlines()[0]


LONG_HISTORY = "oCrfA" * 60
LONG_REPO = "OpenHands/a-very-long-repository-name"


@pytest.fixture
def wide_snapshot(tkt_home):  # noqa: ARG001
    store.save(
        make_snapshot(
            kind="pr",
            name="wide",
            items=[
                make_item(ref=f"{LONG_REPO}#13306", history=LONG_HISTORY),
                make_item(ref="jpshackelford/tickster#86", history=LONG_HISTORY),
            ],
        )
    )


def _show(monkeypatch, *, width: int, terminal: bool) -> str:
    buf = io.StringIO()
    monkeypatch.setattr(
        cli, "console", Console(file=buf, width=width, force_terminal=terminal or None)
    )
    assert cli.cmd_show("pr/wide") == 0
    return buf.getvalue()


def test_show_piped_prints_everything_at_natural_width(wide_snapshot, monkeypatch):  # noqa: ARG001
    out = _show(monkeypatch, width=40, terminal=False)
    assert LONG_HISTORY in out
    assert LONG_REPO in out
    assert "13306" in out and " 86 " in out
    assert "…" not in out
    assert ">" not in out
    assert "cropped" not in out


def test_show_piped_output_does_not_depend_on_width(wide_snapshot, monkeypatch):  # noqa: ARG001
    assert _show(monkeypatch, width=40, terminal=False) == _show(
        monkeypatch, width=200, terminal=False
    )


def test_show_terminal_fits_and_crops_history(wide_snapshot, monkeypatch):  # noqa: ARG001
    out = _show(monkeypatch, width=80, terminal=True)
    rows = [line for line in out.splitlines() if "13306" in line or " 86 " in line]
    assert len(rows) == 2
    assert all("open" in line for line in rows)
    assert all(line.count(">") == 1 for line in rows)
    assert LONG_HISTORY not in out
    assert "History cropped to fit the terminal" in out


def test_list_piped_prints_full_columns_on_narrow_console(seed, monkeypatch):  # noqa: ARG001
    buf = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buf, width=20))
    assert cli.cmd_list() == 0
    out = buf.getvalue()
    assert "…" not in out
    for item in ("pr/hourly", "2026-09-30T22:00:00Z", "pr/later"):
        assert item in out
    header = next(line for line in out.splitlines() if "Ref" in line)
    assert all(h in header for h in ("Captured at", "Items", "Scope#"))


def test_ack_commits_the_pending_baseline(seed, capsys):  # noqa: ARG001
    store.save_pending(make_snapshot(kind="pr", name="hourly", items=[make_item(ref="a/b#9")]))

    assert cli.cmd_ack("pr/hourly") == 0

    assert "acked pr/hourly" in capsys.readouterr().out
    assert [it.ref for it in store.load("pr", "hourly").items] == ["a/b#9"]
    assert not store.has_pending("pr", "hourly")


def test_ack_without_pending_exits_1_and_changes_nothing(seed, capsys):  # noqa: ARG001
    before = store.path_for("pr", "hourly").read_bytes()

    assert cli.cmd_ack("pr/hourly") == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "Error: nothing to ack: pr/hourly has no pending baseline (run a --diff hourly first)"
    ]
    assert store.path_for("pr", "hourly").read_bytes() == before


def test_ack_rejects_a_bad_ref(seed, capsys):  # noqa: ARG001
    assert cli.cmd_ack("hourly") == 2
    assert "KIND/NAME" in capsys.readouterr().err


def test_ack_of_a_corrupt_pending_file_is_an_error_line(seed, capsys, caplog):  # noqa: ARG001
    path = store.pending_path_for("pr", "hourly")
    path.parent.mkdir()
    path.write_text("{")

    assert cli.cmd_ack("pr/hourly") == 1

    assert "pending baseline not found: pr/hourly" in capsys.readouterr().err
    [notice] = _notices(caplog)
    assert notice.startswith("tkt: discarded pending baseline pr/hourly: invalid JSON")
    assert not path.exists()


def test_list_marks_a_snapshot_with_a_pending_baseline(seed, capsys):  # noqa: ARG001
    store.save_pending(make_snapshot(kind="pr", name="hourly"))

    assert cli.cmd_list() == 0

    lines = capsys.readouterr().out.splitlines()
    assert any("pr/hourly" in ln and "(pending ack)" in ln for ln in lines)
    assert not any("pr/later" in ln and "pending" in ln for ln in lines)


def test_rm_removes_the_pending_baseline_too(seed, capsys):  # noqa: ARG001
    store.save_pending(make_snapshot(kind="pr", name="hourly"))

    assert cli.cmd_rm(["pr/hourly"]) == 0

    assert not store.has_pending("pr", "hourly")
