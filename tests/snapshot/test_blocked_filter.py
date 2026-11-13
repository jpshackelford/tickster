"""`tkt issue list --blocked / --unblocked`: arguments, footer, snapshot scope and diff reasons.

Only the GitHub client is stubbed; argument parsing, validation, the snapshot
store and the diff run for real against a tmp TKT_HOME.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.__main__ import main
from src.issue.cli import list_cmd as issue_list
from src.issue.models import IssueInfo, IssueListResult, IssueState
from src.snapshot import store
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import SnapshotScope
from src.snapshot.render import blocked_filter_note
from src.snapshot.resolve import resolve_removed

from .conftest import make_item, make_snapshot

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _issue(number: int, *, blockers: list[str] | None = None) -> IssueInfo:
    return IssueInfo(
        repo="o/r",
        number=number,
        title="t",
        state=IssueState.OPEN,
        history="O",
        linked_pr=None,
        labels=[],
        created_at=NOW,
        closed_at=None,
        last_activity=NOW,
        author="someone",
        open_blockers=blockers or [],
    )


class FakeClient:
    """Serves issues 1 and 2; issue 2 is blocked while `blocked` is True."""

    blocked = True
    seen: list[dict[str, Any]] = []
    has_more = False
    total_count = 9

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_current_user(self) -> str:
        return "octocat"

    def list_issues_by_author(self, author: str | None, **kw: Any) -> IssueListResult:  # noqa: ARG002
        self.seen.append(kw)
        issues = [_issue(1), _issue(2, blockers=["o/r#1"] if self.blocked else None)]
        if kw["blocked_filter"] == "blocked":
            issues = [i for i in issues if i.open_blockers]
        return IssueListResult(issues=issues, total_count=self.total_count, has_more=self.has_more)

    def get_issues_by_ref(self, refs: list[str]) -> IssueListResult:
        issues = [_issue(int(ref.rsplit("#", 1)[1])) for ref in refs]
        return IssueListResult(issues=issues, total_count=len(issues))


class NoNetworkClient:
    def __init__(self) -> None:
        raise AssertionError("no GitHub client should be created")


@pytest.fixture
def stub_client(monkeypatch):
    monkeypatch.setattr(FakeClient, "blocked", True)
    monkeypatch.setattr(FakeClient, "seen", [])
    monkeypatch.setattr(FakeClient, "has_more", False)
    monkeypatch.setattr(issue_list, "IssueClient", FakeClient)
    monkeypatch.setattr(issue_list, "_get_repos", lambda explicit, _board: explicit or ["o/r"])
    monkeypatch.setattr(issue_list, "console", Console(width=200, color_system=None))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


# --- arguments ---------------------------------------------------------------


def test_flags_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["issue", "list", "--blocked", "--unblocked"])
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flag", "expected"),
    [("--blocked", "blocked"), ("--unblocked", "unblocked"), (None, None)],
)
def test_cli_passes_the_filter_to_the_client(flag, expected, stub_client):  # noqa: ARG001
    assert main(["issue", "list", *([flag] if flag else [])]) == 0
    assert [kw["blocked_filter"] for kw in FakeClient.seen] == [expected]


@pytest.mark.parametrize("flag", ["--blocked", "--unblocked"])
@pytest.mark.parametrize(("args", "stdin"), [(["o/r#1"], ""), ([], "o/r#1\n")])
def test_explicit_refs_are_rejected(flag, args, stdin, monkeypatch, capsys):
    monkeypatch.setattr(issue_list, "IssueClient", NoNetworkClient)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert main(["issue", "list", *args, flag]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{flag} cannot be combined with explicit refs" in captured.err
    assert f"drop {flag}" in captured.err


def test_combines_with_the_other_filters(stub_client):  # noqa: ARG001
    argv = ["issue", "list", "--unblocked", "-l", "ready", "--repo", "o/r", "--all-authors"]
    assert main([*argv, "--no-pr"]) == 0
    (kw,) = FakeClient.seen
    assert (kw["blocked_filter"], kw["pr_filter"], kw["repos"]) == ("unblocked", "no-pr", ["o/r"])


def test_help_describes_both_flags(capsys):
    with pytest.raises(SystemExit):
        main(["issue", "list", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "--blocked" in out
    assert "--unblocked" in out
    assert "no open blocker" in out
    assert "cannot read" in out


# --- output ------------------------------------------------------------------


def test_filters_line_names_the_filter(stub_client, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--blocked"]) == 0
    assert "blocked=yes · limit=100" in capsys.readouterr().out
    assert main(["issue", "list", "--unblocked"]) == 0
    assert "blocked=no · limit=100" in capsys.readouterr().out
    assert main(["issue", "list"]) == 0
    assert "blocked=" not in capsys.readouterr().out


def test_json_stays_valid_json(stub_client, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--unblocked", "--snapshot", "j", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["scope"]["blocked_filter"] == "unblocked"


# --- footer ------------------------------------------------------------------


def test_filtered_footer_does_not_compare_with_the_unfiltered_total(stub_client, capsys):  # noqa: ARG001
    FakeClient.has_more = True
    assert main(["issue", "list", "--blocked"]) == 0
    out = capsys.readouterr().out
    assert "Showing 1 matching issues (more available; raise --limit)" in out
    assert "of 9" not in out


def test_filtered_scan_that_ended_prints_no_footer(stub_client, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--unblocked"]) == 0
    assert "Showing" not in capsys.readouterr().out


# --- snapshot scope ----------------------------------------------------------


def _scope(blocked_filter: str | None) -> SnapshotScope:
    return SnapshotScope.from_issue_args(
        board=None,
        author=None,
        repos=["o/r"],
        refs=None,
        states=["open"],
        labels=None,
        limit=100,
        blocked_filter=blocked_filter,
    )


def test_scope_hash_without_the_filter_is_unchanged():
    """Same golden hash as before --blocked existed."""
    scope = _scope(None)
    assert "blocked_filter" not in scope.to_dict()
    assert scope.fingerprint() == "ab1ab50d"


def test_scope_with_the_filter_differs_and_round_trips():
    blocked, unblocked = _scope("blocked"), _scope("unblocked")
    assert blocked.to_dict()["blocked_filter"] == "blocked"
    assert len({_scope(None).fingerprint(), blocked.fingerprint(), unblocked.fingerprint()}) == 3
    for scope in (blocked, unblocked):
        assert SnapshotScope.from_dict(scope.to_dict()) == scope
    assert SnapshotScope.from_dict(_scope(None).to_dict()).blocked_filter is None


def test_scopes_of_other_kinds_ignore_the_filter():
    scope = SnapshotScope.from_pr_args(
        board=None, author=None, reviewer=None, repos=None, refs=None, states=None, limit=1
    )
    assert scope.blocked_filter is None


def test_snapshot_flow_matches_with_the_flag_and_not_without_it(stub_client, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--blocked", "--snapshot", "a"]) == 0
    assert store.load("issue", "a").scope.blocked_filter == "blocked"
    capsys.readouterr()

    assert main(["issue", "list", "--blocked", "--diff", "a"]) == 0
    assert "scope mismatch" not in capsys.readouterr().out

    assert main(["issue", "list", "--diff", "a"]) == 2
    out = capsys.readouterr().out
    assert "scope mismatch" in out
    assert "blocked filter: blocked → none" in out

    assert main(["issue", "list", "--unblocked", "--diff", "a"]) == 2
    assert "blocked filter: blocked → unblocked" in capsys.readouterr().out


def test_note_names_the_filter_change_only_when_it_changed():
    plain = make_snapshot(kind="issue", scope=_scope(None))
    blocked = make_snapshot(kind="issue", scope=_scope("blocked"))
    unblocked = make_snapshot(kind="issue", scope=_scope("unblocked"))
    assert blocked_filter_note(plain, blocked) == "blocked filter: none → blocked"
    assert blocked_filter_note(blocked, unblocked) == "blocked filter: blocked → unblocked"
    assert blocked_filter_note(blocked, blocked) is None


# --- an issue that becomes unblocked leaves a --blocked list ------------------


def test_resolve_calls_an_unblocked_row_still_open():
    scope = _scope("blocked")
    prev = make_snapshot(kind="issue", scope=scope, items=[make_item(key="o/r#2")])
    curr = make_snapshot(kind="issue", scope=scope, items=[])
    result = resolve_removed(diff_snapshots(prev, curr), lambda _: [_issue(2)])
    assert result.deltas[0].disappearance_reason == "still-open"


def test_an_unblocked_issue_is_gone_and_resolve_says_still_open(stub_client, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--blocked", "--snapshot", "w"]) == 0
    FakeClient.blocked = False
    capsys.readouterr()

    assert main(["issue", "list", "--blocked", "--diff", "w", "--diff-resolve"]) == 0
    out = capsys.readouterr().out
    assert "-1 gone" in out
    assert "still open" in out
