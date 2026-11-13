"""`blocked_filter` keeps issues by `IssueInfo.open_blockers`, the Blocked by column's definition."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from src.issue.github_api import IssueClient


def _blocker(number: int, state: str) -> dict:
    return {"number": number, "state": state, "repository": {"nameWithOwner": "o/r"}}


def _node(number: int, *, blockers: list[dict] | None = None, total: int | None = None) -> dict:
    blockers = blockers or []
    return {
        "__typename": "Issue",
        "number": number,
        "title": "t",
        "state": "OPEN",
        "createdAt": f"2024-01-{number:02d}T00:00:00Z",
        "closedAt": None,
        "author": {"login": "someone"},
        "repository": {"nameWithOwner": "o/r"},
        "labels": {"nodes": []},
        "blockedBy": {"totalCount": len(blockers) if total is None else total, "nodes": blockers},
        "blocking": {"totalCount": 0, "nodes": []},
        "parent": None,
        "milestone": None,
        "timelineItems": {"nodes": []},
    }


def _page(nodes: list[dict], *, has_next: bool, count: int) -> httpx.Response:
    body = {
        "data": {
            "search": {
                "issueCount": count,
                "pageInfo": {"hasNextPage": has_next, "endCursor": "c" if has_next else None},
                "nodes": nodes,
            }
        }
    }
    return httpx.Response(200, json=body, request=httpx.Request("POST", "https://x"))


def _list(pages: list[httpx.Response], monkeypatch, **kwargs):
    monkeypatch.setenv("GITHUB_USERNAME", "me-user")
    with patch.object(httpx.Client, "post", side_effect=pages) as post:
        client = IssueClient(token="test-token")
        result = client.list_issues_by_author(None, repos=["o/r"], **kwargs)
        client.close()
    return result, post


def _mixed() -> list[dict]:
    return [
        _node(1),
        _node(2, blockers=[_blocker(90, "OPEN")]),
        _node(3, blockers=[_blocker(91, "CLOSED")]),
        _node(4, blockers=[_blocker(92, "OPEN"), _blocker(93, "CLOSED")]),
        _node(5, total=1),
    ]


def _numbers(result) -> list[int]:
    return sorted(i.number for i in result.issues)


def test_unblocked_keeps_issues_with_no_open_blocker(monkeypatch):
    result, _ = _list(
        [_page(_mixed(), has_next=False, count=5)], monkeypatch, blocked_filter="unblocked"
    )
    assert _numbers(result) == [1, 3]
    assert all(not i.open_blockers for i in result.issues)


def test_blocked_keeps_issues_with_an_open_or_unreadable_blocker(monkeypatch):
    result, _ = _list(
        [_page(_mixed(), has_next=False, count=5)], monkeypatch, blocked_filter="blocked"
    )
    assert _numbers(result) == [2, 4, 5]
    assert [i.open_blockers for i in result.issues if i.number == 5] == [["?"]]


def test_the_two_filters_partition_the_unfiltered_list(monkeypatch):
    def run(**kw):
        return _list([_page(_mixed(), has_next=False, count=5)], monkeypatch, **kw)[0]

    blocked, unblocked, everything = (
        run(blocked_filter="blocked"),
        run(blocked_filter="unblocked"),
        run(),
    )
    assert set(_numbers(blocked)).isdisjoint(_numbers(unblocked))
    assert (
        sorted(_numbers(blocked) + _numbers(unblocked)) == _numbers(everything) == [1, 2, 3, 4, 5]
    )


def test_a_closed_only_blocker_does_not_block(monkeypatch):
    page = _page([_node(3, blockers=[_blocker(91, "CLOSED")])], has_next=False, count=1)
    result, _ = _list([page], monkeypatch, blocked_filter="unblocked")
    assert _numbers(result) == [3]


def test_a_dependency_cycle_leaves_every_issue_in_it_blocked(monkeypatch):
    nodes = [_node(1, blockers=[_blocker(2, "OPEN")]), _node(2, blockers=[_blocker(1, "OPEN")])]
    result, _ = _list(
        [_page(nodes, has_next=False, count=2)], monkeypatch, blocked_filter="blocked"
    )
    assert _numbers(result) == [1, 2]


def test_limit_counts_matches_and_pages_on(monkeypatch):
    blocked = _blocker(90, "OPEN")
    first = _page(
        [_node(1, blockers=[blocked]), _node(2, blockers=[blocked]), _node(3)],
        has_next=True,
        count=9,
    )
    second = _page([_node(4, blockers=[blocked]), _node(5), _node(6)], has_next=True, count=9)
    result, post = _list([first, second], monkeypatch, blocked_filter="unblocked", limit=2)
    assert _numbers(result) == [3, 5]
    assert post.call_count == 2
    assert result.has_more is True


def test_has_more_comes_from_the_scan_not_the_unfiltered_count(monkeypatch):
    page = _page(_mixed(), has_next=False, count=500)
    result, _ = _list([page], monkeypatch, blocked_filter="unblocked", limit=10)
    assert result.has_more is False
    assert result.total_count == 500


def test_combines_with_the_pr_filter(monkeypatch):
    linked = _node(2)
    linked["timelineItems"] = {
        "nodes": [
            {
                "__typename": "CrossReferencedEvent",
                "actor": {"login": "dev"},
                "createdAt": "2024-01-02T00:00:00Z",
                "source": {
                    "__typename": "PullRequest",
                    "number": 902,
                    "state": "OPEN",
                    "repository": {"nameWithOwner": "o/r"},
                },
            }
        ]
    }
    page = _page(
        [_node(1), linked, _node(3, blockers=[_blocker(90, "OPEN")])], has_next=False, count=3
    )
    result, _ = _list([page], monkeypatch, blocked_filter="unblocked", pr_filter="no-pr")
    assert _numbers(result) == [1]


@pytest.mark.parametrize("blocked_filter", ["blocked", "unblocked"])
def test_blocked_issue_excluded_label_still_applies(monkeypatch, blocked_filter):
    page = _page(_mixed(), has_next=False, count=5)
    result, _ = _list([page], monkeypatch, blocked_filter=blocked_filter, not_labels=["nope"])
    assert len(result.issues) == (2 if blocked_filter == "unblocked" else 3)
