"""The removed --since/--after/--before/--date-field flags fail fast on the list commands."""

from __future__ import annotations

import pytest

from src.__main__ import main
from src.issue.github_api import IssueClient
from src.pr.github_api import PRClient
from src.review.github_api import ReviewClient

COMMANDS = [("issue", "list"), ("pr", "list"), ("review",)]
LIST_FIELDS = "--created-{k} {p}, --updated-{k} {p} or --closed-{k} {p}"
MERGED_PART = " (--merged-{k} {p} on pr list and review)"

FLAG_CASES = [
    ("--since", "14", "since", "N"),
    ("--after", "2026-08-01", "after", "D"),
    ("--before", "2026-08-31", "before", "D"),
]


def _expected(flag: str, kind: str, placeholder: str, *, merged: bool) -> str:
    text = f"{flag} was removed: use " + LIST_FIELDS.format(k=kind, p=placeholder)
    if merged:
        text += MERGED_PART.format(k=kind, p=placeholder)
    return text


def _usage_name(command: tuple[str, ...]) -> str:
    return "tkt " + " ".join(command)


@pytest.fixture(autouse=True)
def no_github_client(monkeypatch):
    """Any client built means a query could be sent: fail the test."""

    def boom(*_args, **_kwargs):
        raise AssertionError("a GitHub client was created")

    for client in (IssueClient, PRClient, ReviewClient):
        monkeypatch.setattr(client, "__init__", boom)
    monkeypatch.setenv("GITHUB_TOKEN", "x")


def _fail(command, args, capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        main([*command, *args])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    return captured.err


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
@pytest.mark.parametrize(("flag", "value", "kind", "placeholder"), FLAG_CASES)
def test_flag_with_value_gives_the_one_line_message(
    command, flag, value, kind, placeholder, capsys
):
    err = _fail(command, [flag, value], capsys)
    message = _expected(flag, kind, placeholder, merged=command[0] != "issue")
    lines = err.rstrip().splitlines()
    assert lines[-1] == f"{_usage_name(command)}: error: {message}"
    assert sum("error:" in line for line in lines) == 1


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
@pytest.mark.parametrize(("flag", "value"), [(f, v) for f, v, _, _ in FLAG_CASES])
def test_equals_and_bare_forms_give_the_same_message(command, flag, value, capsys):
    with_space = _fail(command, [flag, value], capsys)
    assert _fail(command, [f"{flag}={value}"], capsys) == with_space
    assert _fail(command, [flag], capsys) == with_space


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
class TestRemovedDateField:
    @pytest.mark.parametrize("field", ["created", "updated", "closed"])
    def test_a_valid_field_is_echoed_into_the_hint(self, command, field, capsys):
        err = _fail(command, ["--date-field", field], capsys)
        assert (
            err.rstrip()
            .splitlines()[-1]
            .endswith(
                f"--date-field was removed: put the field in the flag name, for example --{field}-since N"
            )
        )

    def test_merged_is_echoed_on_pr_list_and_review_only(self, command, capsys):
        err = _fail(command, ["--date-field", "merged"], capsys).rstrip().splitlines()[-1]
        field = "created" if command[0] == "issue" else "merged"
        assert err.endswith(f"for example --{field}-since N")

    @pytest.mark.parametrize("value", ["bogus", "MERGED", ""])
    def test_any_other_value_falls_back_to_created(self, command, value, capsys):
        err = _fail(command, ["--date-field", value], capsys).rstrip().splitlines()[-1]
        assert err.endswith("for example --created-since N")

    def test_equals_and_bare_forms(self, command, capsys):
        equals = _fail(command, ["--date-field=closed"], capsys)
        assert equals.rstrip().splitlines()[-1].endswith("for example --closed-since N")
        bare = _fail(command, ["--date-field"], capsys)
        assert bare.rstrip().splitlines()[-1].endswith("for example --created-since N")


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_issue_messages_omit_merged_and_the_others_include_it(command, capsys):
    err = _fail(command, ["--since", "3"], capsys)
    assert ("--merged-since" in err) == (command[0] != "issue")


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_stub_fires_before_other_arguments_are_acted_on(command, capsys):
    err = _fail(command, ["--since", "3", "--snapshot", "x", "--watch", "y"], capsys)
    assert "--since was removed" in err


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_help_does_not_mention_the_removed_flags(command, capsys):
    with pytest.raises(SystemExit) as exc:
        main([*command, "--help"])
    assert exc.value.code == 0
    words = capsys.readouterr().out.replace(",", " ").replace("[", " ").split()
    for removed in ("--since", "--after", "--before", "--date-field"):
        assert removed not in words
    assert "--created-since" in words


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_abbreviation_still_reaches_the_stub(command, capsys):
    err = _fail(command, ["--date", "created"], capsys)
    assert "--date-field was removed" in err


def test_other_commands_keep_their_own_time_flags(monkeypatch):
    seen: dict[str, object] = {}

    def fake_show(**kwargs):
        seen["show"] = kwargs["since_time"]
        return 0

    def fake_changes(**kwargs):
        seen["changes"] = kwargs["since"]
        return 0

    def fake_scan(**kwargs):
        seen["scan"] = kwargs["since_days"]
        return 0

    monkeypatch.setattr("src.show.cli.cmd_show", fake_show)
    monkeypatch.setattr("src.pr.cli.cmd_changes", fake_changes)
    monkeypatch.setattr("src.board.cli.cmd_scan", fake_scan)

    assert main(["pr", "show", "o/r#7", "--since-time", "2026-11-05T10:00:00Z"]) == 0
    assert main(["pr", "changes", "o/r#7", "--since-sha", "deadbee"]) == 0
    assert main(["board", "scan", "--updated-since", "7"]) == 0
    assert seen == {"show": "2026-11-05T10:00:00Z", "changes": "deadbee", "scan": 7}
