"""The `Filters:` line under a plain `tkt pr list` (#141)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.pr.cli import list_cmd as pr_list
from src.pr.models import CIStatus, PRInfo, PRListResult, PRState

REAL_GET_REPOS = pr_list._get_repos
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ALL_STATES = ["open", "merged", "closed"]
DEFAULT_LINE = "Filters: author=octocat (you) · state=open · repos=all GitHub · limit=100"


def _pr(number: int) -> PRInfo:
    return PRInfo(
        repo="o/r",
        number=number,
        title="t",
        state=PRState.OPEN,
        ci_status=CIStatus.GREEN,
        history="oC",
        created_at=NOW,
        closed_at=None,
        last_activity=NOW,
        author="octocat",
        is_draft=False,
        unresolved_thread_count=0,
    )


class Client:
    numbers: list[int] = [1]
    has_more = False
    login_calls = 0
    searches: list[tuple[str, str | None]] = []

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_current_user(self) -> str:
        Client.login_calls += 1
        return "octocat"

    def _result(self) -> PRListResult:
        return PRListResult(
            prs=[_pr(n) for n in self.numbers],
            total_count=len(self.numbers) + 5,
            has_more=self.has_more,
        )

    def list_prs_by_author(self, author: str | None, **_: Any) -> PRListResult:
        Client.searches.append(("author", author))
        return self._result()

    def list_prs_for_reviewer(self, reviewer: str, **_: Any) -> PRListResult:
        Client.searches.append(("reviewer", reviewer))
        return self._result()

    def get_prs_by_ref(self, refs: list[str]) -> PRListResult:
        return PRListResult(prs=[_pr(int(r.split("#")[1])) for r in refs])


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(Client, "numbers", [1])
    monkeypatch.setattr(Client, "has_more", False)
    monkeypatch.setattr(Client, "login_calls", 0)
    monkeypatch.setattr(Client, "searches", [])
    monkeypatch.setattr(pr_list, "PRClient", Client)
    monkeypatch.setattr(pr_list, "_get_repos", lambda explicit, _board: explicit or None)

    def _run(width: int = 200, **kwargs: Any) -> list[str]:
        buf = io.StringIO()
        monkeypatch.setattr(pr_list, "console", Console(file=buf, width=width, color_system=None))
        kwargs.setdefault("states", ["open"])
        assert pr_list.cmd_list(**kwargs) == 0
        return buf.getvalue().splitlines()

    return _run


def _filters(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("Filters:")]


def test_default_line_has_every_default(run):
    assert _filters(run()) == [DEFAULT_LINE]
    assert Client.login_calls == 1
    assert Client.searches == [("author", "octocat")]


def test_me_is_the_same_as_the_default(run):
    assert _filters(run(author="me")) == [DEFAULT_LINE]
    assert Client.login_calls == 1


def test_explicit_author_all_states_repo_and_limit(run):
    lines = run(author="octocat2", states=ALL_STATES, repos=["o/r"], limit=5)
    assert _filters(lines) == [
        "Filters: author=octocat2 · state=open+merged+closed · repos=o/r · limit=5"
    ]
    assert Client.login_calls == 0
    assert Client.searches == [("author", "octocat2")]


def test_explicit_author_naming_the_current_login_has_no_you(run):
    assert "author=octocat ·" in _filters(run(author="octocat"))[0]


def test_all_authors_merged(run):
    lines = run(all_authors=True, repos=["o/r"], states=["merged"])
    assert _filters(lines) == ["Filters: author=all authors · state=merged · repos=o/r · limit=100"]
    assert Client.login_calls == 0
    assert Client.searches == [("author", None)]


def test_state_order_is_kept(run):
    assert "state=merged+closed" in _filters(run(states=["merged", "closed"]))[0]


def test_reviewer_shows_reviewer_and_open_only(run):
    lines = run(reviewer="octocat2", states=ALL_STATES, author="bob", repos=["o/r"])
    assert _filters(lines) == ["Filters: reviewer=octocat2 · state=open · repos=o/r · limit=100"]
    assert Client.login_calls == 0
    assert Client.searches == [("reviewer", "octocat2")]


def test_reviewer_me_shows_the_login_with_you(run):
    lines = run(reviewer="me")
    assert _filters(lines) == [
        "Filters: reviewer=octocat (you) · state=open · repos=all GitHub · limit=100"
    ]
    assert Client.login_calls == 1
    assert Client.searches == [("reviewer", "octocat")]


def test_explicit_refs_print_only_the_ref_count(run):
    lines = run(pr_refs=["o/r#1", "o/r#2"])
    assert _filters(lines) == ["Filters: refs=2"]
    assert Client.login_calls == 0


def test_board_repos_are_comma_joined(run, monkeypatch):
    monkeypatch.setattr(pr_list, "_get_repos", REAL_GET_REPOS)
    monkeypatch.setattr("src.pr.config.get_repos", lambda _name: ["a/b", "c/d"])
    assert "repos=a/b,c/d" in _filters(run(board_name="mine"))[0]


def test_line_sits_after_the_table_and_before_the_footer(run):
    Client.has_more = True
    lines = run(limit=1)
    line = lines.index(DEFAULT_LINE.replace("limit=100", "limit=1"))
    assert line > next(i for i, ln in enumerate(lines) if "#1" in ln)
    assert lines[line + 1 :] == ["", "Showing 1 of 6 PRs"]


def test_footer_drops_the_total_when_it_is_unknown(run, monkeypatch):
    Client.has_more = True
    monkeypatch.setattr(
        Client, "_result", lambda _self: PRListResult(prs=[_pr(1)], total_count=None, has_more=True)
    )
    assert run(limit=1)[-1] == "Showing 1 PRs"


def test_empty_result_prints_no_prs_then_the_line(run):
    Client.numbers = []
    assert run() == ["No PRs found.", DEFAULT_LINE]


def test_window_is_not_repeated_and_stays_last(run):
    lines = run(field_dates={"updated_before": "2026-08-31"})
    assert lines[-1] == "Window: updated ≤ 2026-08-31 (UTC)"
    assert _filters(lines) == [DEFAULT_LINE]


def test_piped_output_does_not_depend_on_width(run):
    repos = ["o/very-long-repository-name", "o/another-very-long-repository-name"]
    narrow = run(width=20, repos=repos)
    wide = run(width=200, repos=repos)
    assert narrow == wide
    assert _filters(narrow) == [
        f"Filters: author=octocat (you) · state=open · repos={','.join(repos)} · limit=100"
    ]
