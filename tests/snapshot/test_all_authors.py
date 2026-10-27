"""`--all-authors` on `tkt issue list` / `tkt pr list`: argument handling and snapshots.

Only the GitHub client is stubbed; argument parsing, validation, the snapshot
store and the diff run for real against a tmp TKT_HOME.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.__main__ import main
from src.issue.cli import list_cmd as issue_list
from src.issue.models import IssueInfo, IssueListResult, IssueState
from src.pr.cli import list_cmd as pr_list
from src.pr.models import CIStatus, PRInfo, PRListResult, PRState
from src.snapshot import store
from src.snapshot.models import SnapshotScope

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class RecordingClient:
    """Stands in for IssueClient / PRClient and records the author each search used."""

    calls: list[tuple[str | None, list[str] | None]] = []

    def __enter__(self) -> RecordingClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def list_issues_by_author(self, author: str | None, **kw: Any) -> IssueListResult:
        self.calls.append((author, kw["repos"]))
        issue = IssueInfo(
            repo="o/r",
            number=1,
            title="t",
            state=IssueState.OPEN,
            history="O",
            linked_pr=None,
            labels=[],
            created_at=NOW,
            closed_at=None,
            last_activity=NOW,
            author="someone",
        )
        return IssueListResult(issues=[issue], total_count=1)

    def list_prs_by_author(self, author: str | None, **kw: Any) -> PRListResult:
        self.calls.append((author, kw["repos"]))
        pr = PRInfo(
            repo="o/r",
            number=2,
            title="t",
            state=PRState.OPEN,
            ci_status=CIStatus.GREEN,
            history="O",
            created_at=NOW,
            closed_at=None,
            last_activity=NOW,
            author="someone",
            is_draft=False,
            unresolved_thread_count=0,
        )
        return PRListResult(prs=[pr], total_count=1)


class NoNetworkClient:
    def __init__(self) -> None:
        raise AssertionError("no GitHub client should be created")


@pytest.fixture
def board_repos(monkeypatch) -> list[str]:
    """Repos the board would supply; tests clear it to simulate a repo-less board."""
    repos = ["o/r"]
    monkeypatch.setattr(RecordingClient, "calls", [])
    for module, client_attr in ((pr_list, "PRClient"), (issue_list, "IssueClient")):
        monkeypatch.setattr(module, client_attr, RecordingClient)
        monkeypatch.setattr(module, "_get_repos", lambda explicit, _board: explicit or repos)
        monkeypatch.setattr(module, "console", Console(width=200, color_system=None))
    return repos


COMMANDS = {
    "issue": (issue_list, "IssueClient", issue_list.cmd_list, "issue_refs"),
    "pr": (pr_list, "PRClient", pr_list.cmd_list, "pr_refs"),
}


# --- argument handling -------------------------------------------------------


@pytest.mark.parametrize("command", ["issue", "pr"])
def test_all_authors_and_author_are_mutually_exclusive(command, capsys):
    with pytest.raises(SystemExit) as exc:
        main([command, "list", "--all-authors", "--author", "alice"])
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["issue", "pr"])
@pytest.mark.parametrize(("args", "stdin"), [(["o/r#1"], ""), ([], "o/r#1\n")])
def test_explicit_refs_through_the_cli_are_rejected(
    command,
    args,
    stdin,
    board_repos,  # noqa: ARG001
    monkeypatch,
    capsys,
):
    module, client_attr, _, _ = COMMANDS[command]
    monkeypatch.setattr(module, client_attr, NoNetworkClient)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert main([command, "list", *args, "--all-authors"]) == 1
    out = capsys.readouterr().out
    assert "--all-authors cannot be combined with explicit refs" in out
    assert "drop --all-authors" in out


@pytest.mark.parametrize("command", ["issue", "pr"])
def test_without_repos_is_an_error_and_sends_no_search(command, board_repos, monkeypatch, capsys):
    module, client_attr, cmd_list, _ = COMMANDS[command]
    board_repos.clear()
    monkeypatch.setattr(module, client_attr, NoNetworkClient)
    assert cmd_list(all_authors=True) == 1
    out = capsys.readouterr().out
    assert "--all-authors needs repos to search" in out
    assert "--repo OWNER/REPO" in out


def test_pr_all_authors_with_reviewer_is_an_error(
    board_repos,  # noqa: ARG001
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(pr_list, "PRClient", NoNetworkClient)
    assert pr_list.cmd_list(all_authors=True, reviewer="bob") == 1
    assert "--all-authors cannot be combined with --reviewer" in capsys.readouterr().out


# --- search ------------------------------------------------------------------


@pytest.mark.parametrize("command", ["issue", "pr"])
def test_all_authors_searches_without_an_author_in_the_board_repos(
    command,
    board_repos,  # noqa: ARG001
):
    _, _, cmd_list, _ = COMMANDS[command]
    assert cmd_list(all_authors=True) == 0
    assert RecordingClient.calls == [(None, ["o/r"])]


@pytest.mark.parametrize("command", ["issue", "pr"])
def test_explicit_repo_wins_over_the_board(
    command,
    board_repos,  # noqa: ARG001
):
    _, _, cmd_list, _ = COMMANDS[command]
    assert cmd_list(all_authors=True, repos=["x/y"]) == 0
    assert RecordingClient.calls == [(None, ["x/y"])]


@pytest.mark.parametrize("command", ["issue", "pr"])
def test_default_is_still_the_current_user(
    command,
    board_repos,  # noqa: ARG001
):
    _, _, cmd_list, _ = COMMANDS[command]
    assert cmd_list() == 0
    assert RecordingClient.calls == [("me", ["o/r"])]


# --- snapshots ---------------------------------------------------------------


@pytest.mark.parametrize("command", ["issue", "pr"])
def test_watch_twice_with_all_authors_matches_its_own_scope(
    command,
    tkt_home,  # noqa: ARG001
    board_repos,  # noqa: ARG001
    capsys,
):
    _, _, cmd_list, _ = COMMANDS[command]
    assert cmd_list(all_authors=True, watch_name="factory") == 0
    capsys.readouterr()
    assert cmd_list(all_authors=True, watch_name="factory") == 0
    assert "scope" not in capsys.readouterr().out
    assert store.load(command, "factory").scope.all_authors is True


@pytest.mark.parametrize("command", ["issue", "pr"])
@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"all_authors": True}, {}),
        ({}, {"all_authors": True}),
        ({"author": "me"}, {"all_authors": True}),
    ],
)
def test_all_authors_and_current_user_snapshots_never_match(
    command,
    first,
    second,
    tkt_home,  # noqa: ARG001
    board_repos,  # noqa: ARG001
    capsys,
):
    _, _, cmd_list, _ = COMMANDS[command]
    assert cmd_list(watch_name="w", **first) == 0
    before = store.load(command, "w")
    capsys.readouterr()

    assert cmd_list(watch_name="w", **second) == 2
    assert "scope mismatch" in capsys.readouterr().out
    assert store.load(command, "w").scope == before.scope


def test_scope_hash_without_all_authors_is_unchanged():
    """Golden hashes computed on main before --all-authors existed."""
    issue = SnapshotScope.from_issue_args(
        board=None, author=None, repos=["o/r"], refs=None, states=["open"], labels=None, limit=100
    )
    pr = SnapshotScope.from_pr_args(
        board="oh",
        author=None,
        reviewer=None,
        repos=["o/r", "o/s"],
        refs=None,
        states=["open"],
        limit=100,
    )
    assert "all_authors" not in issue.to_dict()
    assert (issue.fingerprint(), pr.fingerprint()) == ("ab1ab50d", "f7f27131")


def test_all_authors_scope_round_trips_and_hashes_differently():
    kwargs: dict[str, Any] = {
        "board": None,
        "author": None,
        "repos": ["o/r"],
        "refs": None,
        "states": ["open"],
        "labels": None,
        "limit": 100,
    }
    mine = SnapshotScope.from_issue_args(**kwargs)
    everyone = SnapshotScope.from_issue_args(**kwargs, all_authors=True)
    assert everyone.to_dict()["all_authors"] is True
    assert SnapshotScope.from_dict(everyone.to_dict()) == everyone
    assert everyone.fingerprint() != mine.fingerprint()
