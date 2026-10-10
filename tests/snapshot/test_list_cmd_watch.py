"""End-to-end `--watch` through the real list commands.

Only the GitHub client is stubbed (it talks to the network); the snapshot
store, diff, and render code run for real against a tmp TKT_HOME.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.issue.cli import list_cmd as issue_list
from src.issue.models import IssueInfo, IssueListResult, IssueState
from src.pr.cli import list_cmd as pr_list
from src.pr.models import CIStatus, PRInfo, PRListResult, PRState
from src.review.cli import list_cmd as review_list
from src.review.github_api import ReviewListResult
from src.review.models import ReviewInfo, ReviewStatus
from src.snapshot import store

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


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


class FakeClient:
    """Context-manager client whose list/get methods return `numbers` as rows."""

    numbers: list[int] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def list_prs_by_author(self, *_: Any, **__: Any) -> PRListResult:
        return PRListResult(prs=[_pr(n) for n in self.numbers])

    def get_prs_by_ref(self, refs: list[str]) -> PRListResult:
        return PRListResult(prs=[_pr(int(r.split("#")[1])) for r in refs])

    def list_issues_by_author(self, *_: Any, **__: Any) -> IssueListResult:
        return IssueListResult(issues=[_issue(n) for n in self.numbers])

    def get_issues_by_ref(self, refs: list[str]) -> IssueListResult:
        return IssueListResult(issues=[_issue(int(r.split("#")[1])) for r in refs])

    def list_reviews(self, *_: Any, **__: Any) -> ReviewListResult:
        reviews = [_review(n) for n in self.numbers]
        return ReviewListResult(
            reviews=reviews, total_count=len(reviews), has_more=False, action_count=len(reviews)
        )


@pytest.fixture
def fake_client(monkeypatch) -> type[FakeClient]:
    monkeypatch.setattr(FakeClient, "numbers", [])
    for module, client_attr in (
        (pr_list, "PRClient"),
        (issue_list, "IssueClient"),
        (review_list, "ReviewClient"),
    ):
        monkeypatch.setattr(module, client_attr, FakeClient)
        monkeypatch.setattr(module, "_get_repos", lambda *_: None)
        monkeypatch.setattr(module, "console", Console(width=200, color_system=None))
    return FakeClient


COMMANDS: dict[str, tuple[str, Callable[..., int]]] = {
    "pr": ("pr", pr_list.cmd_list),
    "issue": ("issue", issue_list.cmd_list),
    "review": ("review", lambda **kw: review_list.cmd_list(reviewer="octocat", **kw)),
}


@pytest.mark.parametrize("command", list(COMMANDS))
def test_watch_reports_last_item_going_away(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    kind, cmd_list = COMMANDS[command]

    fake_client.numbers = [1]
    assert cmd_list(watch_name="hourly") == 0
    assert [it.key for it in store.load(kind, "hourly").items] == ["o/r#1"]
    capsys.readouterr()

    fake_client.numbers = []
    assert cmd_list(watch_name="hourly") == 0
    out = capsys.readouterr().out
    assert "-1 gone" in out
    assert "o/r" in out and "#1" in out
    assert store.load(kind, "hourly").items == ()


@pytest.mark.parametrize("command", list(COMMANDS))
def test_snapshot_only_with_empty_result_saves_empty_baseline(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = []
    assert cmd_list(snapshot_name="nightly") == 0
    assert "No " in capsys.readouterr().out
    assert store.load(kind, "nightly").items == ()


@pytest.mark.parametrize(
    ("kind", "cmd_list", "refs_kwarg"),
    [
        ("pr", pr_list.cmd_list, "pr_refs"),
        ("issue", issue_list.cmd_list, "issue_refs"),
    ],
)
def test_watch_flags_changed_refs_as_scope_change_and_keeps_baseline(
    kind,
    cmd_list,
    refs_kwarg,
    tkt_home,  # noqa: ARG001
    fake_client,  # noqa: ARG001
    capsys,
):
    assert cmd_list(watch_name="refs", **{refs_kwarg: ["o/r#1", "o/r#2"]}) == 0
    capsys.readouterr()

    assert cmd_list(watch_name="refs", **{refs_kwarg: ["o/r#7"]}) == 2
    out = capsys.readouterr().out
    assert "scope mismatch" in out
    assert "closed?" not in out
    keys = [it.key for it in store.load(kind, "refs").items]
    assert keys == ["o/r#1", "o/r#2"]

    # Reordering the same refs is the same scope.
    assert cmd_list(watch_name="refs", **{refs_kwarg: ["o/r#2", "o/r#1"]}) == 0


@pytest.mark.parametrize(
    ("command", "module"), [("pr", pr_list), ("issue", issue_list), ("review", review_list)]
)
def test_watch_flags_board_repo_edit_as_scope_change(
    command,
    module,
    tkt_home,  # noqa: ARG001
    fake_client,
    monkeypatch,
    capsys,
):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]

    monkeypatch.setattr(module, "_get_repos", lambda *_: ["o/r", "o/s"])
    assert cmd_list(watch_name="hourly") == 0

    # Reordering the board's repos is the same scope.
    monkeypatch.setattr(module, "_get_repos", lambda *_: ["o/s", "o/r"])
    assert cmd_list(watch_name="hourly") == 0
    capsys.readouterr()

    monkeypatch.setattr(module, "_get_repos", lambda *_: ["o/s"])
    assert cmd_list(watch_name="hourly") == 2
    assert "scope mismatch" in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_watch_flags_changed_window_as_scope_change_and_keeps_baseline(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1, 2]

    assert cmd_list(watch_name="win", since_days=14) == 0
    capsys.readouterr()

    fake_client.numbers = [1]
    assert cmd_list(watch_name="win", since_days=3) == 2
    out = capsys.readouterr().out
    assert "scope mismatch" in out
    assert "window: updated since 14d ago → updated since 3d ago" in out
    assert [it.key for it in store.load(kind, "win").items] == ["o/r#1", "o/r#2"]


@pytest.mark.parametrize("command", list(COMMANDS))
def test_watch_flags_adding_a_window_as_scope_change(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,  # noqa: ARG001
    capsys,
):
    _, cmd_list = COMMANDS[command]
    assert cmd_list(watch_name="win") == 0
    capsys.readouterr()

    assert cmd_list(watch_name="win", since_days=14) == 2
    assert "window: none → updated since 14d ago" in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_watch_with_same_rolling_window_matches_and_names_it(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(watch_name="win", since_days=14) == 0
    capsys.readouterr()

    assert cmd_list(watch_name="win", since_days=14) == 0
    out = capsys.readouterr().out
    assert "scope-changed" not in out
    assert "window: updated since 14d ago" in out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_window_is_stored_in_the_snapshot_scope(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,  # noqa: ARG001
):
    kind, cmd_list = COMMANDS[command]
    assert cmd_list(snapshot_name="s", after="2026-08-01", before="2026-08-31") == 0
    window = store.load(kind, "s").scope.window
    assert window is not None
    assert (window.field, window.after, window.before) == ("updated", "2026-08-01", "2026-08-31")


@pytest.mark.parametrize(("command", "refs_kwarg"), [("pr", "pr_refs"), ("issue", "issue_refs")])
def test_window_with_explicit_refs_is_an_error(
    command,
    refs_kwarg,
    fake_client,  # noqa: ARG001
    capsys,
):
    _, cmd_list = COMMANDS[command]
    assert cmd_list(since_days=7, **{refs_kwarg: ["o/r#1"]}) == 1
    out = capsys.readouterr().out
    assert "--since cannot narrow explicit refs" in out
    assert "Drop the refs to search by date, or drop --since." in out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_date_field_without_a_window_is_an_error(command, fake_client, capsys):  # noqa: ARG001
    _, cmd_list = COMMANDS[command]
    assert cmd_list(date_field="created") == 1
    assert "--date-field needs --since, --after or --before" in capsys.readouterr().out


def test_open_listing_with_merged_date_field_is_an_error(fake_client, capsys):  # noqa: ARG001
    assert pr_list.cmd_list(states=["open"], since_days=7, date_field="merged") == 1
    assert "add --merged" in capsys.readouterr().out


def test_issue_listing_with_merged_date_field_is_an_error(fake_client, capsys):  # noqa: ARG001
    assert issue_list.cmd_list(since_days=7, date_field="merged") == 1
    assert "Issues have no merged date" in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_empty_result_names_the_window(command, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = []
    assert cmd_list(after="2026-08-01") == 0
    assert "(updated ≥ 2026-08-01, UTC)." in capsys.readouterr().out


@pytest.mark.parametrize("command", list(COMMANDS))
def test_listing_with_window_ends_with_a_window_line(command, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(before="2026-08-31") == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1] == "Window: updated ≤ 2026-08-31 (UTC)"


@pytest.mark.parametrize("command", list(COMMANDS))
def test_listing_without_window_has_no_window_line(command, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list() == 0
    assert "Window:" not in capsys.readouterr().out
