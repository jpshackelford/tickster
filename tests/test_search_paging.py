"""Search listings survive slow pages: small pages, 502/504 retries, halving (#47)."""

import json
from collections.abc import Callable

import httpx
import pytest
from rich.console import Console

from src.board import github_api
from src.board.github_api import SEARCH_PAGE_SIZE, GitHubClient
from src.issue.github_api import IssueClient
from src.pr.cli import list_cmd as pr_list
from src.review.github_api import ReviewClient


def pr_node(n: int) -> dict:
    return {
        "number": n,
        "title": f"PR {n}",
        "state": "OPEN",
        "isDraft": False,
        "createdAt": f"2024-01-01T00:{n // 60:02d}:{n % 60:02d}Z",
        "closedAt": None,
        "mergeable": "MERGEABLE",
        "author": {"login": "alice"},
        "repository": {"nameWithOwner": "owner/repo"},
        "reviewThreads": {"nodes": []},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
        "timelineItems": {"nodes": []},
    }


def issue_node(n: int) -> dict:
    return {
        "__typename": "Issue",
        "number": n,
        "title": f"Issue {n}",
        "state": "OPEN",
        "createdAt": "2024-01-01T00:00:00Z",
        "closedAt": None,
        "author": {"login": "alice"},
        "repository": {"nameWithOwner": "owner/repo"},
        "labels": {"nodes": []},
        "timelineItems": {"nodes": []},
    }


class FakeGitHub:
    """Paginated GraphQL ``search`` endpoint that fails on cue."""

    def __init__(self, total: int, node: Callable[[int], dict], failures: list[int] | None = None):
        self.total = total
        self.node = node
        self.failures = list(failures or [])
        self.limits: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        variables = json.loads(request.content)["variables"]
        limit = variables["limit"]
        self.limits.append(limit)
        if self.failures:
            return httpx.Response(self.failures.pop(0))
        start = int(variables.get("cursor") or 0)
        end = min(start + limit, self.total)
        search = {
            "issueCount": self.total,
            "pageInfo": {"hasNextPage": end < self.total, "endCursor": str(end)},
            "nodes": [self.node(n) for n in range(start + 1, end + 1)],
        }
        return httpx.Response(200, json={"data": {"search": search}})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(github_api, "_sleep", lambda _seconds: None)


def serve(monkeypatch, fake: FakeGitHub) -> None:
    def client_factory(**kwargs) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(fake), headers=kwargs.get("headers"))

    monkeypatch.setattr(github_api, "create_logging_client", client_factory)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")


class TestPrListCommand:
    @pytest.fixture(autouse=True)
    def wide_console(self, monkeypatch):
        monkeypatch.setattr(pr_list, "console", Console(width=200, color_system=None))

    def test_prints_every_row_after_a_502(self, monkeypatch, capsys):
        fake = FakeGitHub(total=60, node=pr_node, failures=[502])
        serve(monkeypatch, fake)

        assert pr_list.cmd_list(author="alice", repos=["owner/repo"], limit=60) == 0

        out = capsys.readouterr().out
        assert all(f"#{n} " in out for n in range(1, 61))
        assert max(fake.limits) <= SEARCH_PAGE_SIZE
        assert fake.limits == [25, 25, 25, 10]

    def test_halves_a_page_that_keeps_timing_out(self, monkeypatch, capsys):
        attempts = github_api.GRAPHQL_MAX_ATTEMPTS
        fake = FakeGitHub(total=40, node=pr_node, failures=[504] * attempts)
        serve(monkeypatch, fake)

        assert pr_list.cmd_list(author="alice", repos=["owner/repo"], limit=40) == 0

        out = capsys.readouterr().out
        assert all(f"#{n} " in out for n in range(1, 41))
        # Later pages stay at the reduced size.
        assert fake.limits == [25] * attempts + [12, 12, 12, 4]

    def test_reports_error_when_retries_run_out(self, monkeypatch, capsys):
        fake = FakeGitHub(total=10, node=pr_node, failures=[502] * 100)
        serve(monkeypatch, fake)

        assert pr_list.cmd_list(author="alice", repos=["owner/repo"], limit=10) == 1
        assert "502 Bad Gateway" in capsys.readouterr().out


class TestIssueAndReviewPaging:
    def test_issue_search_uses_small_pages_and_retries(self, monkeypatch):
        fake = FakeGitHub(total=60, node=issue_node, failures=[502])
        serve(monkeypatch, fake)
        client = IssueClient.__new__(IssueClient)
        client._client = GitHubClient()

        result = client._search_issues("is:issue", "alice", limit=60)

        assert sorted(i.number for i in result.issues) == list(range(1, 61))
        assert max(fake.limits) <= SEARCH_PAGE_SIZE

    def test_review_search_uses_small_pages_and_retries(self, monkeypatch):
        fake = FakeGitHub(total=60, node=pr_node, failures=[504])
        serve(monkeypatch, fake)
        client = ReviewClient.__new__(ReviewClient)
        client._client = GitHubClient()

        prs = client._search_prs("is:pr", limit=60)

        assert [pr["number"] for pr in prs] == list(range(1, 61))
        assert max(fake.limits) <= SEARCH_PAGE_SIZE
