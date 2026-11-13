"""`total_count` and `has_more` of the three list clients: exact, or None when unknown (#142)."""

import pytest

from src.board.github_api import GitHubClient
from src.issue.github_api import IssueClient
from src.pr.github_api import PRClient
from src.review.github_api import ReviewClient
from tests.test_search_paging import FakeGitHub, issue_node, no_sleep, pr_node, serve  # noqa: F401


def labeled_issue(n: int) -> dict:
    node = issue_node(n)
    node["labels"] = {"nodes": [{"name": "bug" if n % 2 else "docs"}]}
    return node


def issue_client() -> IssueClient:
    client = IssueClient.__new__(IssueClient)
    client._client = GitHubClient()
    return client


def review_client() -> ReviewClient:
    client = ReviewClient.__new__(ReviewClient)
    client._client = GitHubClient()
    return client


class TestIssueOrLabels:
    def search(self, monkeypatch, total: int, limit: int):
        serve(monkeypatch, FakeGitHub(total=total, node=labeled_issue))
        return issue_client()._search_issues(
            "is:issue", "alice", limit=limit, or_groups=[["bug", "feature"]]
        )

    def test_a_finished_scan_counts_only_the_matches(self, monkeypatch):
        result = self.search(monkeypatch, total=10, limit=50)
        assert sorted(i.number for i in result.issues) == [1, 3, 5, 7, 9]
        assert result.total_count == 5
        assert result.has_more is False

    def test_a_scan_that_stopped_early_has_no_count(self, monkeypatch):
        result = self.search(monkeypatch, total=10, limit=2)
        assert len(result.issues) == 2
        assert result.total_count is None
        assert result.has_more is True

    def test_without_or_labels_the_count_is_the_search_count(self, monkeypatch):
        serve(monkeypatch, FakeGitHub(total=10, node=labeled_issue))
        result = issue_client()._search_issues("is:issue", "alice", limit=4)
        assert result.total_count == 10
        assert result.has_more is True


class TestPRClientSideStates:
    def list(self, monkeypatch, total: int, limit: int, states: list[str]):
        serve(monkeypatch, FakeGitHub(total=total, node=pr_node))
        return PRClient().list_prs_by_author(
            "alice", repos=["owner/repo"], states=states, limit=limit
        )

    def test_a_finished_scan_has_an_exact_count(self, monkeypatch):
        result = self.list(monkeypatch, total=3, limit=10, states=["open", "merged"])
        assert result.total_count == 3
        assert result.has_more is False

    def test_a_scan_that_stopped_at_the_limit_has_no_count(self, monkeypatch):
        result = self.list(monkeypatch, total=5, limit=3, states=["open", "merged"])
        assert len(result.prs) == 3
        assert result.total_count is None
        assert result.has_more is True

    def test_a_scan_that_ends_exactly_at_the_limit_is_exact(self, monkeypatch):
        result = self.list(monkeypatch, total=3, limit=3, states=["open", "merged"])
        assert result.total_count == 3
        assert result.has_more is False

    def test_server_side_states_keep_the_search_count(self, monkeypatch):
        result = self.list(monkeypatch, total=5, limit=3, states=["open"])
        assert result.total_count == 5
        assert result.has_more is True


class TestReviewCounts:
    def list(self, monkeypatch, total: int, limit: int):
        serve(monkeypatch, FakeGitHub(total=total, node=pr_node))
        return review_client().list_reviews(reviewer="carol", limit=limit, include_all=True)

    def test_nothing_cut_off_gives_the_matching_count(self, monkeypatch):
        result = self.list(monkeypatch, total=3, limit=10)
        assert result.total_count == 3
        assert result.has_more is False

    def test_a_source_cut_off_has_no_count(self, monkeypatch):
        result = self.list(monkeypatch, total=5, limit=3)
        assert len(result.reviews) == 3
        assert result.total_count is None
        assert result.has_more is True

    def test_a_source_that_ends_exactly_at_the_limit_is_not_cut_off(self, monkeypatch):
        result = self.list(monkeypatch, total=3, limit=3)
        assert result.total_count == 3
        assert result.has_more is False

    def test_the_count_is_taken_before_the_limit(self, monkeypatch):
        serve(monkeypatch, FakeGitHub(total=3, node=pr_node))
        client = review_client()
        client._search_prs = lambda _query, _limit: [pr_node(n) for n in range(1, 4)]  # type: ignore[method-assign]
        result = client.list_reviews(reviewer="carol", limit=2, include_all=True)
        assert len(result.reviews) == 2
        assert result.total_count == 3
        assert result.has_more is True


@pytest.mark.usefixtures("no_sleep")
def test_the_cut_off_flag_is_reset_for_each_listing(monkeypatch):
    serve(monkeypatch, FakeGitHub(total=5, node=pr_node))
    client = review_client()
    assert client.list_reviews(reviewer="carol", limit=3, include_all=True).total_count is None
    serve(monkeypatch, FakeGitHub(total=2, node=pr_node))
    client._client = GitHubClient()
    assert client.list_reviews(reviewer="carol", limit=3, include_all=True).total_count == 2
