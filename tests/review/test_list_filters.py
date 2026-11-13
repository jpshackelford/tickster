"""The `Filters:` line under a plain `tkt review` (#141)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.pr.models import CIStatus
from src.review.cli import list_cmd as review_list
from src.review.github_api import ReviewListResult
from src.review.models import ReviewInfo, ReviewStatus

REAL_GET_REPOS = review_list._get_repos
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
DEFAULT_LINE = (
    "Filters: reviewer=octocat (you) · show=actionable · state=open · repos=all GitHub · limit=100"
)


def _review(number: int) -> ReviewInfo:
    return ReviewInfo(
        repo="o/r",
        number=number,
        title="t",
        history="oC",
        status=ReviewStatus.REVIEW,
        wait_seconds=60.0,
        ci_status=CIStatus.GREEN,
        unresolved_thread_count=0,
        author="alice",
        last_activity=NOW,
    )


class Client:
    numbers: list[int] = [1]
    has_more = False
    login_calls = 0
    reviewers_seen: list[str] = []

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_current_user(self) -> str:
        Client.login_calls += 1
        return "octocat"

    def list_reviews(self, reviewer: str, **_: Any) -> ReviewListResult:
        Client.reviewers_seen.append(reviewer)
        reviews = [_review(n) for n in self.numbers]
        return ReviewListResult(
            reviews=reviews,
            total_count=len(reviews) + 5,
            has_more=self.has_more,
            action_count=len(reviews),
        )


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(Client, "numbers", [1])
    monkeypatch.setattr(Client, "has_more", False)
    monkeypatch.setattr(Client, "login_calls", 0)
    monkeypatch.setattr(Client, "reviewers_seen", [])
    monkeypatch.setattr(review_list, "ReviewClient", Client)
    monkeypatch.setattr(review_list, "_get_repos", lambda explicit, _board: explicit or None)

    def _run(width: int = 200, **kwargs: Any) -> list[str]:
        buf = io.StringIO()
        monkeypatch.setattr(
            review_list, "console", Console(file=buf, width=width, color_system=None)
        )
        assert review_list.cmd_list(**kwargs) == 0
        return buf.getvalue().splitlines()

    return _run


def _filters(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("Filters:")]


def test_default_line_has_every_default(run):
    assert _filters(run()) == [DEFAULT_LINE]
    assert Client.login_calls == 1


def test_all_shows_show_all(run):
    assert "show=all · state=open" in _filters(run(all_reviews=True))[0]


@pytest.mark.parametrize(
    ("states", "text"),
    [
        (["merged"], "state=merged"),
        (["closed"], "state=closed"),
        (["merged", "closed"], "state=merged+closed"),
    ],
)
def test_historical_states_have_no_open(run, states, text):
    line = _filters(run(states=states))[0]
    assert f"show=actionable · {text} · repos=" in line


def test_reviewer_is_plain_without_you(run):
    lines = run(reviewer="octocat2")
    assert _filters(lines) == [DEFAULT_LINE.replace("octocat (you)", "octocat2")]
    assert Client.login_calls == 0
    assert Client.reviewers_seen == ["octocat2"]


def test_reviewer_me_is_printed_as_given(run):
    assert _filters(run(reviewer="me"))[0].startswith("Filters: reviewer=me · show=")


def test_author_and_exclude_come_after_reviewer(run):
    lines = run(
        reviewer="octocat2",
        author="bob",
        exclude_authors=["dependabot[bot]", "x"],
        repos=["o/r"],
        limit=5,
    )
    assert _filters(lines) == [
        "Filters: reviewer=octocat2 · author=bob · exclude=dependabot[bot],x · "
        "show=actionable · state=open · repos=o/r · limit=5"
    ]


def test_author_and_exclude_appear_only_when_set(run):
    line = _filters(run())[0]
    assert "author=" not in line
    assert "exclude=" not in line


def test_board_repos_are_comma_joined(run, monkeypatch):
    monkeypatch.setattr(review_list, "_get_repos", REAL_GET_REPOS)
    monkeypatch.setattr("src.pr.config.get_repos", lambda _name: ["a/b", "c/d"])
    assert "repos=a/b,c/d" in _filters(run(board_name="mine"))[0]


def test_line_sits_after_the_legend_and_before_the_footer(run):
    lines = run()
    line = lines.index(DEFAULT_LINE)
    assert (
        lines[line - 1] == "History: lowercase = octocat, UPPERCASE = others. o opened, c comment"
    )
    assert lines[line + 1 :] == ["", "Showing 1 PRs needing your review"]


def test_truncation_does_not_change_the_line(run):
    Client.has_more = True
    assert _filters(run()) == [DEFAULT_LINE]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "No PRs needing your review."),
        ({"all_reviews": True}, "No PRs found in your review queue."),
        ({"reviewer": "octocat2"}, "No PRs needing octocat2's review."),
        ({"states": ["merged"]}, "No historical PRs found that octocat reviewed."),
    ],
)
def test_empty_result_prints_its_message_then_the_line(run, kwargs, message):
    Client.numbers = []
    lines = run(**kwargs)
    assert lines[0] == message
    assert len(lines) == 2
    assert lines[1].startswith("Filters: reviewer=")


def test_window_is_not_repeated_and_stays_last(run):
    lines = run(field_dates={"updated_before": "2026-08-31"})
    assert lines[-1] == "Window: updated ≤ 2026-08-31 (UTC)"
    assert _filters(lines) == [DEFAULT_LINE]


def test_piped_output_does_not_depend_on_width(run):
    repos = ["o/very-long-repository-name", "o/another-very-long-repository-name"]
    narrow = run(width=20, repos=repos)
    wide = run(width=200, repos=repos)
    assert narrow == wide
    assert f"repos={','.join(repos)}" in _filters(narrow)[0]
