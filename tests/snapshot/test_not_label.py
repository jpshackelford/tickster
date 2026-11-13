"""`tkt issue list --not-label`: search query, argument handling and snapshot scope.

Only the HTTP layer and the GitHub client are stubbed; argument parsing,
validation, the snapshot store and the diff run for real against a tmp TKT_HOME.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from rich.console import Console

from src.__main__ import main
from src.issue.cli import list_cmd as issue_list
from src.issue.github_api import IssueClient, _build_search_query
from src.issue.models import IssueInfo, IssueListResult, IssueState
from src.snapshot import store
from src.snapshot.models import SnapshotScope

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class TestSearchQuery:
    def test_excluded_labels_become_negated_qualifiers(self):
        query = _build_search_query(None, ["o/r"], ["open"], ["ready"], None, ["hold", "wip"])
        assert query.split() == [
            "is:issue",
            "repo:o/r",
            "is:open",
            "label:ready",
            '-label:"hold"',
            '-label:"wip"',
        ]

    def test_quotes_labels_with_spaces_and_colons(self):
        query = _build_search_query("me", None, None, None, None, ["help wanted", "priority:low"])
        assert '-label:"help wanted"' in query
        assert '-label:"priority:low"' in query

    @pytest.mark.parametrize("not_labels", [None, []])
    def test_no_exclusion_leaves_the_query_unchanged(self, not_labels):
        assert "-label" not in _build_search_query("me", None, None, ["bug"], None, not_labels)

    def test_combines_with_or_labels_in_the_client(self, monkeypatch):
        monkeypatch.setenv("GITHUB_USERNAME", "me-user")
        nodes = [_issue_node(1, ["ready", "bug"]), _issue_node(2, ["ready"])]
        with patch.object(httpx.Client, "post", return_value=_search_response(nodes)) as post:
            client = IssueClient(token="test-token")
            result = client.list_issues_by_author(
                None, repos=["o/r"], labels=["bug,stale", "ready"], not_labels=["hold"]
            )
            client.close()
        query = post.call_args.kwargs["json"]["variables"]["query"]
        assert "label:ready" in query
        assert '-label:"hold"' in query
        assert "bug,stale" not in query
        assert [i.number for i in result.issues] == [1]

    def test_limit_is_a_single_page_when_exclusion_is_in_the_query(self, monkeypatch):
        monkeypatch.setenv("GITHUB_USERNAME", "me-user")
        nodes = [_issue_node(1, ["ready"]), _issue_node(2, ["ready"])]
        with patch.object(httpx.Client, "post", return_value=_search_response(nodes)) as post:
            client = IssueClient(token="test-token")
            result = client.list_issues_by_author(
                None, repos=["o/r"], labels=["ready"], not_labels=["Hold"], limit=2
            )
            client.close()
        assert post.call_count == 1
        assert post.call_args.kwargs["json"]["variables"]["limit"] == 2
        assert '-label:"Hold"' in post.call_args.kwargs["json"]["variables"]["query"]
        assert len(result.issues) == 2


def _issue_node(number: int, labels: list[str]) -> dict:
    return {
        "__typename": "Issue",
        "number": number,
        "title": "t",
        "state": "OPEN",
        "createdAt": "2024-01-01T00:00:00Z",
        "closedAt": None,
        "author": {"login": "someone"},
        "repository": {"nameWithOwner": "o/r"},
        "labels": {"nodes": [{"name": name} for name in labels]},
        "blockedBy": {"totalCount": 0, "nodes": []},
        "blocking": {"totalCount": 0, "nodes": []},
        "parent": None,
        "milestone": None,
        "timelineItems": {"nodes": []},
    }


def _search_response(nodes: list[dict]) -> httpx.Response:
    body = {
        "data": {
            "search": {
                "issueCount": len(nodes),
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": nodes,
            }
        }
    }
    return httpx.Response(200, json=body, request=httpx.Request("POST", "https://x"))


class RecordingClient:
    not_labels_seen: list[list[str] | None] = []

    def __enter__(self) -> RecordingClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def list_issues_by_author(self, author: str | None, **kw: Any) -> IssueListResult:  # noqa: ARG002
        self.not_labels_seen.append(kw["not_labels"])
        issue = IssueInfo(
            repo="o/r",
            number=1,
            title="t",
            state=IssueState.OPEN,
            history="O",
            linked_pr=None,
            labels=["ready"],
            created_at=NOW,
            closed_at=None,
            last_activity=NOW,
            author="someone",
        )
        return IssueListResult(issues=[issue], total_count=1)


class NoNetworkClient:
    def __init__(self) -> None:
        raise AssertionError("no GitHub client should be created")


@pytest.fixture
def stub_client(monkeypatch):
    monkeypatch.setattr(RecordingClient, "not_labels_seen", [])
    monkeypatch.setattr(issue_list, "IssueClient", RecordingClient)
    monkeypatch.setattr(issue_list, "_get_repos", lambda explicit, _board: explicit or ["o/r"])
    monkeypatch.setattr(issue_list, "console", Console(width=200, color_system=None))


def test_cli_passes_repeated_flags_through_unsplit(stub_client, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    args = ["issue", "list", "--all-authors", "--not-label", "hold", "--not-label", "a,b"]
    assert main(args) == 0
    assert RecordingClient.not_labels_seen == [["hold", "a,b"]]


def test_not_set_passes_none(stub_client, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["issue", "list"]) == 0
    assert RecordingClient.not_labels_seen == [None]


@pytest.mark.parametrize(("args", "stdin"), [(["o/r#1"], ""), ([], "o/r#1\n")])
def test_explicit_refs_are_rejected(args, stdin, monkeypatch, capsys):
    monkeypatch.setattr(issue_list, "IssueClient", NoNetworkClient)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert main(["issue", "list", *args, "--not-label", "hold"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--not-label cannot be combined with explicit refs" in captured.err


def test_label_in_both_filters_is_not_an_error(stub_client, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["issue", "list", "-l", "ready", "--not-label", "ready"]) == 0


def test_help_lists_the_flag(capsys):
    with pytest.raises(SystemExit):
        main(["issue", "list", "--help"])
    assert "--not-label LABEL" in capsys.readouterr().out


# --- snapshots ---------------------------------------------------------------


def _scope(not_labels: list[str] | None) -> SnapshotScope:
    return SnapshotScope.from_issue_args(
        board=None,
        author=None,
        repos=["o/r"],
        refs=None,
        states=["open"],
        labels=None,
        limit=100,
        not_labels=not_labels,
    )


def test_scope_hash_without_not_label_is_unchanged():
    """Golden hash computed on main before --not-label existed."""
    scope = _scope(None)
    assert "not_labels" not in scope.to_dict()
    assert _scope([]).fingerprint() == scope.fingerprint()
    assert scope.fingerprint() == "ab1ab50d"


def test_scope_with_not_label_differs_and_round_trips():
    scope = _scope(["hold"])
    assert scope.to_dict()["not_labels"] == ["hold"]
    assert scope.fingerprint() != _scope(None).fingerprint()
    assert SnapshotScope.from_dict(scope.to_dict()) == scope


def test_scope_compares_not_labels_as_a_case_insensitive_set():
    a = _scope(["hold", "Wip", "hold"])
    b = _scope(["WIP", "Hold"])
    assert a == b
    assert a.fingerprint() == b.fingerprint()
    assert a.not_labels == ("hold", "wip")


def test_watch_mismatch_between_with_and_without_the_flag(
    stub_client,  # noqa: ARG001
    tkt_home,  # noqa: ARG001
    capsys,
):
    assert issue_list.cmd_list(watch_name="w", not_labels=["hold"]) == 0
    before = store.load("issue", "w")
    capsys.readouterr()
    assert issue_list.cmd_list(watch_name="w") == 2
    assert "scope mismatch" in capsys.readouterr().out
    assert store.load("issue", "w").scope == before.scope
    assert issue_list.cmd_list(watch_name="w", not_labels=["HOLD"]) == 0
