"""Tests for issue GitHub API functions."""

from unittest.mock import patch

import httpx
import pytest

from src.issue.github_api import (
    IssueClient,
    _build_search_query,
    _matches_or_labels,
    parse_label_filters,
)


class TestParseLabelFilters:
    """Tests for parse_label_filters function."""

    def test_empty_list(self):
        """Test with empty list."""
        and_labels, or_groups = parse_label_filters([])
        assert and_labels == []
        assert or_groups == []

    def test_simple_and_labels(self):
        """Test simple AND labels."""
        and_labels, or_groups = parse_label_filters(["bug", "urgent"])
        assert and_labels == ["bug", "urgent"]
        assert or_groups == []

    def test_simple_or_group(self):
        """Test comma-separated OR group."""
        and_labels, or_groups = parse_label_filters(["bug,stale"])
        assert and_labels == []
        assert or_groups == [["bug", "stale"]]

    def test_mixed_and_or(self):
        """Test mix of AND labels and OR groups."""
        and_labels, or_groups = parse_label_filters(["bug", "stale,wontfix", "urgent"])
        assert and_labels == ["bug", "urgent"]
        assert or_groups == [["stale", "wontfix"]]

    def test_strips_whitespace(self):
        """Test that whitespace is stripped."""
        and_labels, or_groups = parse_label_filters(["  bug  ", " stale , wontfix "])
        assert and_labels == ["bug"]
        assert or_groups == [["stale", "wontfix"]]

    def test_multiple_or_groups(self):
        """Test multiple OR groups."""
        and_labels, or_groups = parse_label_filters(["bug,fix", "P1,P2"])
        assert and_labels == []
        assert or_groups == [["bug", "fix"], ["P1", "P2"]]


class TestMatchesOrLabels:
    """Tests for _matches_or_labels function."""

    def test_empty_or_groups_matches_all(self):
        """Test that empty OR groups match all issues."""
        assert _matches_or_labels(["bug"], []) is True
        assert _matches_or_labels([], []) is True

    def test_matches_single_or_group(self):
        """Test matching a single OR group."""
        or_groups = [["bug", "fix"]]
        assert _matches_or_labels(["bug"], or_groups) is True
        assert _matches_or_labels(["fix"], or_groups) is True
        assert _matches_or_labels(["enhancement"], or_groups) is False

    def test_matches_multiple_or_groups(self):
        """Test that all OR groups must match."""
        or_groups = [["bug", "fix"], ["P1", "P2"]]
        # Has bug (matches first group) and P1 (matches second group)
        assert _matches_or_labels(["bug", "P1"], or_groups) is True
        # Has bug but no P1/P2
        assert _matches_or_labels(["bug"], or_groups) is False
        # Has P1 but no bug/fix
        assert _matches_or_labels(["P1"], or_groups) is False

    def test_case_insensitive(self):
        """Test that matching is case-insensitive."""
        or_groups = [["Bug", "Fix"]]
        assert _matches_or_labels(["bug"], or_groups) is True
        assert _matches_or_labels(["BUG"], or_groups) is True


class TestBuildSearchQuery:
    """Tests for _build_search_query function."""

    def test_basic_query(self):
        """Test basic query with author."""
        query = _build_search_query("testuser", None, None, None)
        assert "is:issue" in query
        assert "author:testuser" in query

    def test_with_repos(self):
        """Test query with repos."""
        query = _build_search_query("testuser", ["owner/repo1", "owner/repo2"], None, None)
        assert "repo:owner/repo1" in query
        assert "repo:owner/repo2" in query

    def test_with_open_state(self):
        """Test query with open state filter."""
        query = _build_search_query("testuser", None, ["open"], None)
        assert "is:open" in query

    def test_with_closed_state(self):
        """Test query with closed state filter."""
        query = _build_search_query("testuser", None, ["closed"], None)
        assert "is:closed" in query

    def test_with_both_states(self):
        """Test query with both states (no filter needed)."""
        query = _build_search_query("testuser", None, ["open", "closed"], None)
        assert "is:open" not in query
        assert "is:closed" not in query

    def test_with_and_labels(self):
        """Test query with AND labels."""
        query = _build_search_query("testuser", None, None, ["bug", "urgent"])
        assert "label:bug" in query
        assert "label:urgent" in query

    def test_with_label_containing_space(self):
        """Test query with label containing space."""
        query = _build_search_query("testuser", None, None, ["help wanted"])
        assert 'label:"help wanted"' in query

    def test_with_date_qualifier(self):
        """Test query includes the date qualifier when provided."""
        query = _build_search_query("testuser", None, ["closed"], None, "closed:>=2026-08-01")
        assert "closed:>=2026-08-01" in query

    def test_without_date_qualifier(self):
        """Test query has no stray date qualifier when omitted."""
        query = _build_search_query("testuser", None, None, None)
        assert ":>=" not in query


class TestGetIssuesByRefWithUnresolvableRef:
    """A ref whose repo can't be resolved nulls its alias; the other refs must still load."""

    def test_other_refs_are_returned_and_the_missing_one_is_skipped(self):
        node = {
            "number": 16,
            "title": "Test issue",
            "state": "OPEN",
            "createdAt": "2024-01-01T00:00:00Z",
            "closedAt": None,
            "author": {"login": "testuser"},
            "repository": {"nameWithOwner": "owner/repo"},
            "labels": {"nodes": []},
            "blockedBy": {"totalCount": 0, "nodes": []},
            "blocking": {"totalCount": 0, "nodes": []},
            "parent": None,
            "milestone": None,
            "timelineItems": {"nodes": []},
        }
        body = {
            "data": {"issue0": {"issue": node}, "issue1": None},
            "errors": [
                {
                    "type": "NOT_FOUND",
                    "path": ["issue1"],
                    "message": "Could not resolve to a Repository with the name 'o/gone'.",
                }
            ],
        }
        response = httpx.Response(200, json=body, request=httpx.Request("POST", "https://x"))

        with patch.object(httpx.Client, "post", return_value=response):
            client = IssueClient(token="test-token")
            result = client.get_issues_by_ref(
                ["owner/repo#16", "o/gone#1"], reference_user="testuser"
            )
            client.close()

        assert [(i.repo, i.number) for i in result.issues] == [("owner/repo", 16)]


class TestBuildSearchQueryAllAuthors:
    """`author=None` lists every author's issues, but only within repos."""

    def test_omits_author_and_keeps_repo_qualifiers(self):
        query = _build_search_query(None, ["owner/repo1", "owner/repo2"], ["open"], ["bug"])
        assert query.split() == [
            "is:issue",
            "repo:owner/repo1",
            "repo:owner/repo2",
            "is:open",
            "label:bug",
        ]

    @pytest.mark.parametrize("repos", [None, []])
    def test_refuses_an_unscoped_search(self, repos):
        with pytest.raises(ValueError, match="scoped to repos"):
            _build_search_query(None, repos, None, None)


def _issue_node(number: int, author: str) -> dict:
    return {
        "__typename": "Issue",
        "number": number,
        "title": "t",
        "state": "OPEN",
        "createdAt": "2024-01-01T00:00:00Z",
        "closedAt": None,
        "author": {"login": author},
        "repository": {"nameWithOwner": "owner/repo"},
        "labels": {"nodes": []},
        "blockedBy": {"totalCount": 0, "nodes": []},
        "blocking": {"totalCount": 0, "nodes": []},
        "parent": None,
        "milestone": None,
        "timelineItems": {"nodes": []},
    }


class TestListIssuesAllAuthors:
    """End to end through IssueClient with only the HTTP layer stubbed."""

    def _search_response(self, nodes: list[dict]) -> httpx.Response:
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

    def test_sends_no_author_qualifier_and_keeps_history_relative_to_me(self, monkeypatch):
        monkeypatch.setenv("GITHUB_USERNAME", "me-user")
        response = self._search_response([_issue_node(1, "me-user"), _issue_node(2, "someone")])
        with patch.object(httpx.Client, "post", return_value=response) as post:
            client = IssueClient(token="test-token")
            result = client.list_issues_by_author(None, repos=["owner/repo"])
            client.close()

        query = post.call_args.kwargs["json"]["variables"]["query"]
        assert "author:" not in query
        assert "repo:owner/repo" in query
        assert {i.number: i.history for i in result.issues} == {1: "o", 2: "O"}

    def test_without_repos_raises_before_any_request(self, monkeypatch):
        monkeypatch.setenv("GITHUB_USERNAME", "me-user")
        with patch.object(httpx.Client, "post") as post:
            client = IssueClient(token="test-token")
            with pytest.raises(ValueError, match="scoped to repos"):
                client.list_issues_by_author(None, repos=None)
            client.close()
        post.assert_not_called()


class TestPrFilter:
    """`pr_filter` keeps issues by `IssueInfo.linked_pr`, the PR column's definition."""

    @staticmethod
    def _node(number: int, *, pr: str | None = None, state: str = "OPEN", source="PullRequest"):
        timeline = []
        if pr is not None or source != "PullRequest":
            timeline.append(
                {
                    "__typename": "CrossReferencedEvent",
                    "actor": {"login": "dev"},
                    "createdAt": "2024-01-02T00:00:00Z",
                    "source": {
                        "__typename": source,
                        "number": 900 + number,
                        "state": state,
                        "repository": {"nameWithOwner": "o/r"},
                    },
                }
            )
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
            "blockedBy": {"totalCount": 0, "nodes": []},
            "blocking": {"totalCount": 0, "nodes": []},
            "parent": None,
            "milestone": None,
            "timelineItems": {"nodes": timeline},
        }

    @staticmethod
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

    def _list(self, pages: list[httpx.Response], monkeypatch, **kwargs):
        monkeypatch.setenv("GITHUB_USERNAME", "me-user")
        with patch.object(httpx.Client, "post", side_effect=pages) as post:
            client = IssueClient(token="test-token")
            result = client.list_issues_by_author(None, repos=["o/r"], **kwargs)
            client.close()
        return result, post

    def _mixed(self):
        return [
            self._node(1),
            self._node(2, pr="x"),
            self._node(3),
            self._node(4, pr="x", state="CLOSED"),
            self._node(5, pr="x", state="MERGED"),
        ]

    def test_no_pr_keeps_only_unlinked_issues(self, monkeypatch):
        page = self._page(self._mixed(), has_next=False, count=5)
        result, _ = self._list([page], monkeypatch, pr_filter="no-pr")
        assert sorted(i.number for i in result.issues) == [1, 3]
        assert all(i.linked_pr is None for i in result.issues)

    def test_has_pr_is_the_complement_and_counts_closed_unmerged_prs(self, monkeypatch):
        page = self._page(self._mixed(), has_next=False, count=5)
        result, _ = self._list([page], monkeypatch, pr_filter="has-pr")
        assert sorted(i.number for i in result.issues) == [2, 4, 5]

    def test_a_mention_from_another_issue_is_not_a_linked_pr(self, monkeypatch):
        nodes = [self._node(1, source="Issue"), self._node(2, pr="x")]
        page = self._page(nodes, has_next=False, count=2)
        no_pr, _ = self._list([page], monkeypatch, pr_filter="no-pr")
        has_pr, _ = self._list([page], monkeypatch, pr_filter="has-pr")
        assert [i.number for i in no_pr.issues] == [1]
        assert [i.number for i in has_pr.issues] == [2]

    def test_limit_counts_matches_and_cuts_the_scan(self, monkeypatch):
        page = self._page(self._mixed(), has_next=False, count=5)
        result, post = self._list([page], monkeypatch, pr_filter="no-pr", limit=1)
        assert len(result.issues) == 1
        assert post.call_count == 1
        assert result.has_more is True

    def test_pages_on_until_limit_matches_are_found(self, monkeypatch):
        first = self._page(
            [self._node(1, pr="x"), self._node(2, pr="x"), self._node(3)], has_next=True, count=9
        )
        second = self._page(
            [self._node(4, pr="x"), self._node(5), self._node(6), self._node(7)],
            has_next=True,
            count=9,
        )
        result, post = self._list([first, second], monkeypatch, pr_filter="no-pr", limit=3)
        assert sorted(i.number for i in result.issues) == [3, 5, 6]
        assert post.call_count == 2
        assert result.has_more is True

    def test_limit_reached_on_the_last_node_of_a_page_looks_at_has_next_page(self, monkeypatch):
        nodes = [self._node(1, pr="x"), self._node(2)]
        more = self._page(nodes, has_next=True, count=50)
        done = self._page(nodes, has_next=False, count=50)
        assert self._list([more], monkeypatch, pr_filter="no-pr", limit=1)[0].has_more is True
        assert self._list([done], monkeypatch, pr_filter="no-pr", limit=1)[0].has_more is False

    def test_has_more_is_false_when_the_scan_ended_despite_a_larger_issue_count(self, monkeypatch):
        page = self._page(self._mixed(), has_next=False, count=500)
        result, _ = self._list([page], monkeypatch, pr_filter="no-pr", limit=10)
        assert [i.number for i in result.issues] == [3, 1]
        assert result.has_more is False
        assert result.total_count == 2

    def test_without_a_filter_has_more_and_total_count_are_unchanged(self, monkeypatch):
        page = self._page(self._mixed(), has_next=False, count=500)
        result, _ = self._list([page], monkeypatch, limit=10)
        assert len(result.issues) == 5
        assert result.has_more is True
        assert result.total_count == 500
