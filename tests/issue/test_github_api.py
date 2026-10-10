"""Tests for issue GitHub API functions."""

from unittest.mock import patch

import httpx

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
