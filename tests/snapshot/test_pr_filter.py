"""`tkt issue list --no-pr / --has-pr`: arguments, footer, snapshot scope and diff reasons.

Only the GitHub client is stubbed; argument parsing, validation, the snapshot
store and the diff run for real against a tmp TKT_HOME.
"""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.__main__ import main
from src.issue.cli import list_cmd as issue_list
from src.issue.models import IssueInfo, IssueListResult, IssueState
from src.snapshot import store
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import ChangeKind, SnapshotScope
from src.snapshot.render import pr_filter_note
from src.snapshot.resolve import resolve_removed

from .conftest import make_item, make_snapshot

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _issue(number: int, *, linked_pr: str | None = None, state=IssueState.OPEN) -> IssueInfo:
    return IssueInfo(
        repo="o/r",
        number=number,
        title="t",
        state=state,
        history="O",
        linked_pr=linked_pr,
        labels=[],
        created_at=NOW,
        closed_at=None,
        last_activity=NOW,
        author="someone",
    )


class FakeClient:
    """Serves issues 1 and 2, leaving out those in `linked`."""

    linked: set[int] = set()
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
        issues = [_issue(n) for n in (1, 2) if n not in self.linked]
        return IssueListResult(issues=issues, total_count=self.total_count, has_more=self.has_more)

    def get_issues_by_ref(self, refs: list[str]) -> IssueListResult:
        issues = [
            _issue(int(ref.rsplit("#", 1)[1]), linked_pr="o/r#99" if n in self.linked else None)
            for ref in refs
            for n in [int(ref.rsplit("#", 1)[1])]
        ]
        return IssueListResult(issues=issues, total_count=len(issues))


class NoNetworkClient:
    def __init__(self) -> None:
        raise AssertionError("no GitHub client should be created")


@pytest.fixture
def stub_client(monkeypatch):
    monkeypatch.setattr(FakeClient, "linked", set())
    monkeypatch.setattr(FakeClient, "seen", [])
    monkeypatch.setattr(FakeClient, "has_more", False)
    monkeypatch.setattr(issue_list, "IssueClient", FakeClient)
    monkeypatch.setattr(issue_list, "_get_repos", lambda explicit, _board: explicit or ["o/r"])
    monkeypatch.setattr(issue_list, "console", Console(width=200, color_system=None))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


# --- arguments ---------------------------------------------------------------


def test_flags_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["issue", "list", "--no-pr", "--has-pr"])
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("flag", "expected"), [("--no-pr", "no-pr"), ("--has-pr", "has-pr"), (None, None)]
)
def test_cli_passes_the_filter_to_the_client(flag, expected, stub_client):  # noqa: ARG001
    assert main(["issue", "list", *([flag] if flag else [])]) == 0
    assert [kw["pr_filter"] for kw in FakeClient.seen] == [expected]


@pytest.mark.parametrize("flag", ["--no-pr", "--has-pr"])
@pytest.mark.parametrize(("args", "stdin"), [(["o/r#1"], ""), ([], "o/r#1\n")])
def test_explicit_refs_are_rejected(flag, args, stdin, monkeypatch, capsys):
    monkeypatch.setattr(issue_list, "IssueClient", NoNetworkClient)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert main(["issue", "list", *args, flag]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{flag} cannot be combined with explicit refs" in captured.err
    assert f"drop {flag}" in captured.err


def test_help_describes_both_flags(capsys):
    with pytest.raises(SystemExit):
        main(["issue", "list", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "--no-pr" in out
    assert "--has-pr" in out
    assert "no linked PR" in out
    assert "--closed or --all" in out


# --- footer ------------------------------------------------------------------


def test_filtered_footer_does_not_compare_with_the_unfiltered_total(stub_client, capsys):  # noqa: ARG001
    FakeClient.has_more = True
    assert main(["issue", "list", "--no-pr"]) == 0
    out = capsys.readouterr().out
    assert "Showing 2 matching issues (more available; raise --limit)" in out
    assert "of 9" not in out


def test_filtered_scan_that_ended_prints_no_footer(stub_client, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--no-pr"]) == 0
    assert "Showing" not in capsys.readouterr().out


def test_unfiltered_footer_is_unchanged(stub_client, capsys):  # noqa: ARG001
    FakeClient.has_more = True
    assert main(["issue", "list"]) == 0
    assert "Showing 2 of 9 issues" in capsys.readouterr().out


# --- snapshot scope ----------------------------------------------------------


def _scope(pr_filter: str | None) -> SnapshotScope:
    return SnapshotScope.from_issue_args(
        board=None,
        author=None,
        repos=["o/r"],
        refs=None,
        states=["open"],
        labels=None,
        limit=100,
        pr_filter=pr_filter,
    )


def test_scope_with_the_filter_differs_and_round_trips():
    no_pr, has_pr = _scope("no-pr"), _scope("has-pr")
    assert no_pr.to_dict()["pr_filter"] == "no-pr"
    assert len({_scope(None).fingerprint(), no_pr.fingerprint(), has_pr.fingerprint()}) == 3
    for scope in (no_pr, has_pr):
        assert SnapshotScope.from_dict(scope.to_dict()) == scope
    assert SnapshotScope.from_dict(_scope(None).to_dict()).pr_filter is None


def test_scopes_of_other_kinds_ignore_the_filter():
    assert (
        SnapshotScope.from_pr_args(
            board=None, author=None, reviewer=None, repos=None, refs=None, states=None, limit=1
        ).pr_filter
        is None
    )


def test_snapshot_flow_matches_with_the_flag_and_not_without_it(stub_client, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--no-pr", "--snapshot", "a"]) == 0
    assert store.load("issue", "a").scope.pr_filter == "no-pr"
    capsys.readouterr()

    assert main(["issue", "list", "--no-pr", "--diff", "a"]) == 0
    assert "scope mismatch" not in capsys.readouterr().out

    assert main(["issue", "list", "--diff", "a"]) == 2
    out = capsys.readouterr().out
    assert "scope mismatch" in out
    assert "pr filter: no-pr → none" in out


def test_note_names_the_filter_change_only_when_it_changed():
    plain = make_snapshot(kind="issue", scope=_scope(None))
    no_pr = make_snapshot(kind="issue", scope=_scope("no-pr"))
    has_pr = make_snapshot(kind="issue", scope=_scope("has-pr"))
    assert pr_filter_note(plain, no_pr) == "pr filter: none → no-pr"
    assert pr_filter_note(no_pr, has_pr) == "pr filter: no-pr → has-pr"
    assert pr_filter_note(no_pr, no_pr) is None


# --- why a row left a --no-pr diff -------------------------------------------


def _removed_reason(prev_state: str, pr_filter: str | None, states=("open",)) -> str | None:
    scope = replace(_scope(pr_filter), states=states)
    prev = make_snapshot(
        kind="issue", scope=scope, items=[make_item(ref="o/r#1", state=prev_state)]
    )
    curr = make_snapshot(kind="issue", scope=scope, items=[])
    (delta,) = diff_snapshots(prev, curr).deltas
    assert delta.kind is ChangeKind.REMOVED
    return delta.disappearance_reason


def test_open_row_leaving_a_no_pr_list_is_attributed_to_a_pr_link():
    assert _removed_reason("open", "no-pr") == "pr-linked?"


@pytest.mark.parametrize("pr_filter", [None, "has-pr"])
def test_other_scopes_keep_the_closed_guess(pr_filter):
    assert _removed_reason("open", pr_filter) == "closed-or-gone"


def test_closed_row_in_a_no_pr_list_is_not_blamed_on_a_pr_link():
    assert _removed_reason("closed", "no-pr", states=("open", "closed")) == "unknown"


def _resolved(pr_filter: str | None, fetched: list[IssueInfo]) -> str | None:
    scope = _scope(pr_filter)
    prev = make_snapshot(kind="issue", scope=scope, items=[make_item(ref="o/r#1")])
    curr = make_snapshot(kind="issue", scope=scope, items=[])
    result = resolve_removed(diff_snapshots(prev, curr), lambda _: fetched)
    return result.deltas[0].disappearance_reason


def test_resolve_names_the_pr_link_for_an_open_issue_that_gained_one():
    assert _resolved("no-pr", [_issue(1, linked_pr="o/r#9")]) == "pr-linked"


def test_resolve_keeps_the_state_when_no_pr_explains_it():
    assert _resolved("no-pr", [_issue(1)]) == "still-open"
    assert _resolved("no-pr", [_issue(1, linked_pr="o/r#9", state=IssueState.CLOSED)]) == "closed"
    assert _resolved("no-pr", []) == "not-found"


def test_resolve_ignores_linked_prs_outside_a_no_pr_scope():
    assert _resolved(None, [_issue(1, linked_pr="o/r#9")]) == "still-open"


def test_watch_shows_a_linked_issue_as_gone_with_the_pr_reason(stub_client, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--no-pr", "--watch", "w"]) == 0
    FakeClient.linked.add(2)
    capsys.readouterr()

    assert main(["issue", "list", "--no-pr", "--watch", "w"]) == 0
    assert "PR linked?" in capsys.readouterr().out

    FakeClient.linked.add(1)
    assert main(["issue", "list", "--no-pr", "--diff", "w", "--diff-resolve"]) == 0
    assert "PR linked" in capsys.readouterr().out
