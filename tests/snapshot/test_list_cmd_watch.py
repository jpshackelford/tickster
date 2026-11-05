"""End-to-end `--watch` through the real list commands.

Only the GitHub client is stubbed (it talks to the network); the snapshot
store, diff, and render code run for real against a tmp TKT_HOME.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
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
    """Context-manager client whose list/get methods return `numbers` as rows.

    `has_more` marks list results truncated. `lookup`, when set, maps a number to
    its current state for the by-ref getters; numbers missing from it are not found.
    """

    numbers: list[int] = []
    has_more: bool = False
    lookup: dict[int, str] | None = None
    ref_calls: list[list[str]] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def _by_ref(self, refs: list[str]) -> dict[int, str]:
        FakeClient.ref_calls.append(refs)
        numbers = [int(r.split("#")[1]) for r in refs]
        if self.lookup is None:
            return dict.fromkeys(numbers, "open")
        return {n: self.lookup[n] for n in numbers if n in self.lookup}

    def list_prs_by_author(self, *_: Any, **__: Any) -> PRListResult:
        return PRListResult(prs=[_pr(n) for n in self.numbers], has_more=self.has_more)

    def get_prs_by_ref(self, refs: list[str]) -> PRListResult:
        found = self._by_ref(refs)
        return PRListResult(prs=[replace(_pr(n), state=PRState(s)) for n, s in found.items()])

    def list_issues_by_author(self, *_: Any, **__: Any) -> IssueListResult:
        return IssueListResult(issues=[_issue(n) for n in self.numbers], has_more=self.has_more)

    def get_issues_by_ref(self, refs: list[str]) -> IssueListResult:
        found = self._by_ref(refs)
        return IssueListResult(
            issues=[replace(_issue(n), state=IssueState(s)) for n, s in found.items()]
        )

    def list_reviews(self, *_: Any, **__: Any) -> ReviewListResult:
        reviews = [_review(n) for n in self.numbers]
        return ReviewListResult(
            reviews=reviews,
            total_count=len(reviews),
            has_more=self.has_more,
            action_count=len(reviews),
        )


@pytest.fixture
def fake_client(monkeypatch) -> type[FakeClient]:
    monkeypatch.setattr(FakeClient, "numbers", [])
    monkeypatch.setattr(FakeClient, "has_more", False)
    monkeypatch.setattr(FakeClient, "lookup", None)
    monkeypatch.setattr(FakeClient, "ref_calls", [])
    monkeypatch.setattr(review_list, "PRClient", FakeClient)
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


@pytest.mark.parametrize("command", list(COMMANDS))
def test_watch_names_a_row_pushed_past_the_limit(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [3, 2, 1]
    assert cmd_list(watch_name="hourly", limit=3) == 0
    assert not store.load(kind, "hourly").has_more
    capsys.readouterr()

    fake_client.numbers = [4, 3, 2]
    fake_client.has_more = True
    assert cmd_list(watch_name="hourly", limit=3) == 0
    out = capsys.readouterr().out
    assert "limit?" in out
    assert "closed?" not in out and "done?" not in out
    assert store.load(kind, "hourly").has_more


@pytest.mark.parametrize("command", list(COMMANDS))
def test_json_reason_is_limit_for_a_row_pushed_past_the_limit(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [2, 1]
    assert cmd_list(watch_name="hourly", limit=2) == 0
    capsys.readouterr()

    fake_client.numbers = [3, 2]
    fake_client.has_more = True
    assert cmd_list(watch_name="hourly", limit=2, diff_format="json") == 0
    deltas = json.loads(capsys.readouterr().out)["deltas"]
    assert {d["key"]: d["disappearance_reason"] for d in deltas if d["kind"] == "removed"} == {
        "o/r#1": "limit"
    }


@pytest.mark.parametrize("command", list(COMMANDS))
def test_diff_resolve_replaces_the_guess_with_the_current_state(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1, 2, 3]
    assert cmd_list(watch_name="hourly") == 0
    capsys.readouterr()

    fake_client.numbers = []
    fake_client.lookup = {1: "closed", 2: "open"}
    assert cmd_list(watch_name="hourly", diff_resolve=True, diff_format="json") == 0
    deltas = json.loads(capsys.readouterr().out)["deltas"]
    assert {d["key"]: d["disappearance_reason"] for d in deltas} == {
        "o/r#1": "closed",
        "o/r#2": "still-open",
        "o/r#3": "not-found",
    }
    assert fake_client.ref_calls == [["o/r#1", "o/r#2", "o/r#3"]]
    assert store.load(kind, "hourly").items == ()


@pytest.mark.parametrize("command", ["pr", "review"])
def test_diff_resolve_table_names_merged_and_not_found(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1, 2]
    assert cmd_list(watch_name="hourly") == 0
    capsys.readouterr()

    fake_client.numbers = []
    fake_client.lookup = {1: "merged"}
    assert cmd_list(watch_name="hourly", diff_resolve=True) == 0
    rows = [line for line in capsys.readouterr().out.splitlines() if line.lstrip().startswith("-")]
    assert [row.split("ago", 1)[1].strip() for row in rows] == ["merged", "not found"]


@pytest.mark.parametrize("command", list(COMMANDS))
def test_diff_resolve_is_off_by_default(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(watch_name="hourly") == 0
    capsys.readouterr()

    fake_client.numbers = []
    assert cmd_list(watch_name="hourly") == 0
    assert fake_client.ref_calls == []


@pytest.mark.parametrize("command", list(COMMANDS))
def test_diff_resolve_with_nothing_gone_makes_no_lookup(
    command,
    tkt_home,  # noqa: ARG001
    fake_client,
    capsys,
):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(watch_name="hourly") == 0
    capsys.readouterr()

    assert cmd_list(watch_name="hourly", diff_resolve=True) == 0
    assert fake_client.ref_calls == []
