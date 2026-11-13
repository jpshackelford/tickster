"""The `Filters:` line under a plain `tkt issue list` (#140)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.issue.cli import list_cmd as issue_list
from src.issue.models import IssueInfo, IssueListResult, IssueState
from src.list_table import filters_line, print_filters

REAL_GET_REPOS = issue_list._get_repos
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
DEFAULT_LINE = (
    "Filters: author=octocat (you) · state=open · repos=all GitHub · label=any · limit=100"
)


def _issue(number: int) -> IssueInfo:
    return IssueInfo(
        repo="o/r",
        number=number,
        title="t",
        state=IssueState.OPEN,
        history="oC",
        linked_pr=None,
        labels=[],
        created_at=NOW,
        closed_at=None,
        last_activity=NOW,
        author="octocat",
    )


class Client:
    numbers: list[int] = [1]
    has_more = False
    login_calls = 0
    author_seen: list[str | None] = []

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_current_user(self) -> str:
        Client.login_calls += 1
        return "octocat"

    def list_issues_by_author(self, author: str | None, **_: Any) -> IssueListResult:
        Client.author_seen.append(author)
        return IssueListResult(
            issues=[_issue(n) for n in self.numbers],
            total_count=len(self.numbers) + 5,
            has_more=self.has_more,
        )

    def get_issues_by_ref(self, refs: list[str]) -> IssueListResult:
        return IssueListResult(issues=[_issue(int(r.split("#")[1])) for r in refs])


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(Client, "numbers", [1])
    monkeypatch.setattr(Client, "has_more", False)
    monkeypatch.setattr(Client, "login_calls", 0)
    monkeypatch.setattr(Client, "author_seen", [])
    monkeypatch.setattr(issue_list, "IssueClient", Client)
    monkeypatch.setattr(issue_list, "_get_repos", lambda explicit, _board: explicit or None)

    def _run(width: int = 200, **kwargs: Any) -> list[str]:
        buf = io.StringIO()
        monkeypatch.setattr(
            issue_list, "console", Console(file=buf, width=width, color_system=None)
        )
        assert issue_list.cmd_list(**kwargs) == 0
        return buf.getvalue().splitlines()

    return _run


def _filters(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("Filters:")]


def test_default_line_has_every_default(run):
    assert _filters(run()) == [DEFAULT_LINE]


def test_me_is_the_same_as_the_default_and_resolves_the_login_once(run):
    assert _filters(run(author="me")) == [DEFAULT_LINE]
    assert Client.login_calls == 1
    assert Client.author_seen == ["octocat"]


def test_explicit_author_state_repo_label_and_limit(run):
    lines = run(
        author="octocat2",
        states=["open", "closed"],
        repos=["o/r"],
        labels=["bug"],
        limit=5,
    )
    assert _filters(lines) == [
        "Filters: author=octocat2 · state=open+closed · repos=o/r · label=bug · limit=5"
    ]
    assert Client.login_calls == 0
    assert Client.author_seen == ["octocat2"]


def test_all_authors(run):
    lines = run(all_authors=True, repos=["o/r"])
    assert _filters(lines) == [
        "Filters: author=all authors · state=open · repos=o/r · label=any · limit=100"
    ]
    assert Client.login_calls == 0
    assert Client.author_seen == [None]


def test_board_repos_are_comma_joined(run, monkeypatch):
    monkeypatch.setattr(issue_list, "_get_repos", REAL_GET_REPOS)
    monkeypatch.setattr("src.repo.config.get_repos", lambda _name: ["a/b", "c/d"])
    assert "repos=a/b,c/d" in _filters(run(board_name="mine"))[0]


def test_label_grouping_keeps_and_and_or(run):
    lines = run(labels=["bug,stale", "urgent"])
    assert "label=bug|stale & urgent" in _filters(lines)[0]


def test_not_label_appears_only_when_given(run):
    assert "not-label" not in _filters(run())[0]
    line = _filters(run(not_labels=["hold", "wip"]))[0]
    assert line.endswith("label=any · not-label=hold,wip · limit=100")


def test_label_with_brackets_is_printed_literally(run):
    line = _filters(run(labels=["[bug]"]))[0]
    assert "label=[bug]" in line


def test_line_sits_between_table_and_legend(run):
    lines = run()
    assert lines.index(DEFAULT_LINE) < next(
        i for i, ln in enumerate(lines) if ln.startswith("History:")
    )
    assert lines.index(DEFAULT_LINE) > next(i for i, ln in enumerate(lines) if "#1" in ln)


def test_empty_result_prints_no_issues_then_the_line(run):
    Client.numbers = []
    lines = run()
    assert lines == ["No issues found.", DEFAULT_LINE]


def test_explicit_refs_print_only_the_ref_count(run):
    lines = run(issue_refs=["o/r#1", "o/r#2"])
    assert _filters(lines) == ["Filters: refs=2"]
    assert Client.login_calls == 0


def test_window_is_not_repeated_and_stays_last(run):
    lines = run(field_dates={"updated_before": "2026-08-31"})
    assert lines[-1] == "Window: updated ≤ 2026-08-31 (UTC)"
    assert _filters(lines) == [DEFAULT_LINE]


def test_truncation_footer_and_limit_are_both_shown(run):
    Client.has_more = True
    lines = run(limit=1)
    assert any(line.startswith("Showing 1 of 6 issues") for line in lines)
    assert "limit=1" in _filters(lines)[0]


def test_piped_output_does_not_depend_on_width(run):
    narrow = run(width=20, repos=["o/very-long-repository-name"], labels=["a-long-label-name"])
    wide = run(width=200, repos=["o/very-long-repository-name"], labels=["a-long-label-name"])
    assert narrow == wide
    assert "label=a-long-label-name" in _filters(narrow)[0]


def test_filters_line_joins_pairs():
    assert filters_line([("a", "1"), ("b", "x y")]) == "Filters: a=1 · b=x y"


def test_print_filters_escapes_markup_and_does_not_wrap_when_piped():
    buf = io.StringIO()
    print_filters(Console(file=buf, width=10, color_system=None), [("label", "[bold]x[/]" * 3)])
    assert buf.getvalue() == "Filters: label=" + "[bold]x[/]" * 3 + "\n"


def test_print_filters_wraps_on_a_terminal():
    buf = io.StringIO()
    console = Console(file=buf, width=20, force_terminal=True, color_system=None)
    print_filters(console, [("repos", "o/a-long-repository-name")])
    assert len(buf.getvalue().splitlines()) > 1
