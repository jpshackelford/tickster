"""`--exit-code`: `--diff` and `--watch` exit 10 when any row was added, changed or removed."""

# ruff: noqa: ARG001, F401, F811

from __future__ import annotations

import io
import json
from dataclasses import replace
from typing import Any

import pytest

from src.__main__ import main
from src.snapshot import store
from src.snapshot.integration import EXIT_CHANGED, SnapshotPlan
from tests.snapshot.test_list_cmd_watch import COMMANDS, FakeClient, fake_client

CHANGED_EXIT = 10


def _touch_history(kind: str, name: str, number: int) -> None:
    """Make the saved baseline remember `number` with a different history."""
    snap = store.load(kind, name)
    items = tuple(replace(it, history="o") if it.number == number else it for it in snap.items)
    store.save(replace(snap, items=items))


def test_exit_changed_is_ten():
    assert EXIT_CHANGED == CHANGED_EXIT


@pytest.mark.parametrize("command", list(COMMANDS))
@pytest.mark.parametrize("flag", ["watch_name", "diff_name"])
def test_no_change_exits_zero(command, flag, tkt_home, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1, 2]
    assert cmd_list(watch_name="t") == 0
    capsys.readouterr()

    assert cmd_list(exit_code=True, **{flag: "t"}) == 0


@pytest.mark.parametrize("command", list(COMMANDS))
@pytest.mark.parametrize("flag", ["watch_name", "diff_name"])
def test_added_row_exits_ten(command, flag, tkt_home, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(watch_name="t") == 0
    capsys.readouterr()

    fake_client.numbers = [1, 2]
    assert cmd_list(exit_code=True, **{flag: "t"}) == CHANGED_EXIT
    assert "+1 new" in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
@pytest.mark.parametrize("flag", ["watch_name", "diff_name"])
def test_removed_row_exits_ten(command, flag, tkt_home, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1, 2]
    assert cmd_list(watch_name="t") == 0
    capsys.readouterr()

    fake_client.numbers = [1]
    assert cmd_list(exit_code=True, **{flag: "t"}) == CHANGED_EXIT
    assert "-1 gone" in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
@pytest.mark.parametrize("flag", ["watch_name", "diff_name"])
def test_changed_row_exits_ten(command, flag, tkt_home, fake_client, capsys):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1, 2]
    assert cmd_list(watch_name="t") == 0
    _touch_history(kind, "t", 2)
    capsys.readouterr()

    assert cmd_list(exit_code=True, **{flag: "t"}) == CHANGED_EXIT
    assert "*1 changed" in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_first_run_with_rows_exits_ten_and_saves_baseline(command, tkt_home, fake_client):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(exit_code=True, watch_name="t") == CHANGED_EXIT
    assert [it.key for it in store.load(kind, "t").items] == ["o/r#1"]

    assert cmd_list(exit_code=True, watch_name="t") == 0


@pytest.mark.parametrize("command", list(COMMANDS))
def test_first_run_with_no_rows_exits_zero(command, tkt_home, fake_client):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = []
    assert cmd_list(exit_code=True, watch_name="t") == 0


@pytest.mark.parametrize("command", list(COMMANDS))
def test_exit_ten_still_saves_the_baseline_under_watch(command, tkt_home, fake_client, capsys):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    cmd_list(watch_name="t")
    fake_client.numbers = [1, 2]
    assert cmd_list(exit_code=True, watch_name="t") == CHANGED_EXIT
    assert [it.key for it in store.load(kind, "t").items] == ["o/r#1", "o/r#2"]
    capsys.readouterr()

    assert cmd_list(exit_code=True, watch_name="t") == 0


@pytest.mark.parametrize("command", list(COMMANDS))
def test_exit_ten_under_diff_stages_the_pending_baseline(command, tkt_home, fake_client):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    cmd_list(snapshot_name="t")
    fake_client.numbers = [1, 2]
    assert cmd_list(exit_code=True, diff_name="t") == CHANGED_EXIT
    pending = store.load_pending(kind, "t")
    assert [it.key for it in pending.items] == ["o/r#1", "o/r#2"]


@pytest.mark.parametrize("command", list(COMMANDS))
def test_without_the_flag_a_changed_diff_still_exits_zero(command, tkt_home, fake_client):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    cmd_list(watch_name="t")
    fake_client.numbers = [1, 2]
    assert cmd_list(watch_name="t") == 0


@pytest.mark.parametrize("command", list(COMMANDS))
@pytest.mark.parametrize("output_format", ["table", "json"])
def test_stdout_is_the_same_with_and_without_the_flag(
    command,
    output_format,
    tkt_home,
    fake_client,  # noqa: F811
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    cmd_list(snapshot_name="t")
    fake_client.numbers = [1, 2]
    capsys.readouterr()

    def run(**flags: Any) -> tuple[int, str]:
        rc = cmd_list(diff_name="t", output_format=output_format, **flags)
        out = capsys.readouterr().out
        return rc, out

    plain_rc, plain_out = run()
    flagged_rc, flagged_out = run(exit_code=True)
    assert (plain_rc, flagged_rc) == (0, CHANGED_EXIT)
    if output_format == "json":
        plain, flagged = json.loads(plain_out), json.loads(flagged_out)
        for doc in (plain, flagged):
            doc["curr"].pop("captured_at")
        assert plain == flagged
    else:
        assert plain_out.split("\n", 1)[1] == flagged_out.split("\n", 1)[1]
        assert plain_out.startswith(f"diff {kind}/t")
    assert store.load_pending(kind, "t") is not None


@pytest.mark.parametrize("command", list(COMMANDS))
def test_scope_mismatch_with_the_flag_still_exits_two(command, tkt_home, fake_client, capsys):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(watch_name="t", field_dates={"updated_since": 14}) == 0
    capsys.readouterr()

    fake_client.numbers = [1, 2]
    rc = cmd_list(exit_code=True, watch_name="t", field_dates={"updated_since": 3})
    assert rc == 2
    assert "scope mismatch" in capsys.readouterr().out
    assert [it.key for it in store.load(kind, "t").items] == ["o/r#1"]


@pytest.mark.parametrize("command", list(COMMANDS))
def test_forced_scope_mismatch_with_the_flag_exits_ten_on_changes(command, tkt_home, fake_client):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    cmd_list(watch_name="t", field_dates={"updated_since": 14})
    fake_client.numbers = [1, 2]
    rc = cmd_list(exit_code=True, watch_name="t", diff_force=True, field_dates={"updated_since": 3})
    assert rc == CHANGED_EXIT


@pytest.mark.parametrize("command", list(COMMANDS))
def test_a_failing_query_with_the_flag_exits_one(
    command, tkt_home, fake_client, monkeypatch, capsys
):
    _, cmd_list = COMMANDS[command]

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("Bad credentials")

    for name in ("list_prs_by_author", "list_issues_by_author", "list_reviews"):
        monkeypatch.setattr(FakeClient, name, boom)
    assert cmd_list(exit_code=True, watch_name="t") == 1
    assert "Bad credentials" in capsys.readouterr().err


@pytest.mark.parametrize("command", list(COMMANDS))
def test_a_corrupt_baseline_with_the_flag_exits_one(command, tkt_home, fake_client, capsys):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    cmd_list(watch_name="t")
    next(tkt_home.rglob(f"{kind}-t.json")).write_text("{not json")
    capsys.readouterr()
    assert cmd_list(exit_code=True, watch_name="t") == 1


def test_resolve_does_not_hide_a_removed_row(tkt_home, fake_client):
    _, cmd_list = COMMANDS["pr"]
    fake_client.numbers = [1, 2]
    cmd_list(watch_name="t")
    fake_client.numbers = [1]
    assert cmd_list(exit_code=True, watch_name="t", diff_resolve=True) == CHANGED_EXIT


@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "list", "o/r#5", "--exit-code"],
        ["pr", "list", "o/r#5", "--snapshot", "s", "--exit-code"],
        ["pr", "list", "o/r#5", "--format", "json", "--exit-code"],
        ["issue", "list", "o/r#5", "--exit-code"],
        ["review", "--reviewer", "octocat", "--exit-code"],
    ],
)
def test_flag_without_diff_or_watch_is_a_usage_error(argv, tkt_home, fake_client, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "--exit-code needs --diff or --watch" in captured.err
    assert captured.out == ""
    assert fake_client.ref_calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "list", "o/r#5", "--watch", "w", "--exit-code"],
        ["issue", "list", "o/r#5", "--watch", "w", "--exit-code"],
        ["review", "--reviewer", "octocat", "--watch", "w", "--exit-code"],
    ],
)
def test_flag_reaches_the_list_command_through_the_cli(argv, tkt_home, fake_client, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    fake_client.numbers = [5]
    assert main(argv) == CHANGED_EXIT
    assert main(argv) == 0


def test_plan_rejects_exit_code_without_a_diff():
    with pytest.raises(ValueError, match="--exit-code needs --diff or --watch"):
        SnapshotPlan.from_args(
            kind="pr",
            snapshot_name="s",
            diff_name=None,
            watch_name=None,
            exit_code=True,
        )
