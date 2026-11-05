"""Nested connections past their first page are followed, not silently dropped (#26)."""

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.board import github_api
from src.board.github_api import GitHubClient
from src.connection_paging import TRUNCATION_MARKER, ConnectionSpec, complete_connection
from src.issue.github_api import ISSUE_FIELDS_FRAGMENT, IssueClient
from src.pr.github_api import PR_FIELDS_FRAGMENT, PRClient
from src.pr.history import process_pr_data
from src.review.github_api import ReviewClient
from src.snapshot.convert import item_from_pr
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import ChangeKind
from tests.snapshot.conftest import make_snapshot

BASE = datetime(2024, 1, 1, tzinfo=UTC)


def stamp(i: int) -> str:
    return (BASE + timedelta(minutes=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr_chatter(n: int) -> list[dict]:
    """Alternating comment / review-request events, so none collapse in the history."""
    return [
        {"__typename": "IssueComment", "author": {"login": "bob"}, "createdAt": stamp(i)}
        if i % 2 == 0
        else {
            "__typename": "ReviewRequestedEvent",
            "actor": {"login": "bob"},
            "createdAt": stamp(i),
        }
        for i in range(n)
    ]


def issue_chatter(n: int) -> list[dict]:
    return [
        {"__typename": "IssueComment", "author": {"login": "bob"}, "createdAt": stamp(i)}
        if i % 2 == 0
        else {
            "__typename": "LabeledEvent",
            "actor": {"login": "bob"},
            "label": {"name": "x"},
            "createdAt": stamp(i),
        }
        for i in range(n)
    ]


def merged(i: int) -> dict:
    return {"__typename": "MergedEvent", "actor": {"login": "bob"}, "createdAt": stamp(i)}


def closed(i: int) -> dict:
    return {"__typename": "ClosedEvent", "actor": {"login": "bob"}, "createdAt": stamp(i)}


def pr_node(
    timeline: list[dict], *, threads: list[dict] | None = None, state: str = "MERGED"
) -> dict:
    return {
        "id": "PR_1",
        "number": 1,
        "title": "Busy PR",
        "state": state,
        "isDraft": False,
        "createdAt": "2024-01-01T00:00:00Z",
        "closedAt": None,
        "mergeable": "UNKNOWN",
        "author": {"login": "alice"},
        "repository": {"nameWithOwner": "owner/repo"},
        "reviewThreads": {"nodes": threads or []},
        "commits": {"nodes": []},
        "timelineItems": {"nodes": timeline},
    }


def issue_node(timeline: list[dict], labels: list[dict] | None = None) -> dict:
    return {
        "__typename": "Issue",
        "id": "I_1",
        "number": 7,
        "title": "Busy issue",
        "state": "CLOSED",
        "createdAt": "2024-01-01T00:00:00Z",
        "closedAt": None,
        "author": {"login": "alice"},
        "repository": {"nameWithOwner": "owner/repo"},
        "labels": {"nodes": labels or []},
        "timelineItems": {"nodes": timeline},
    }


class FakeGitHub:
    """GraphQL endpoint holding full connections and serving them a page at a time.

    ``search``/``batch`` answers return the node with only its first page of each
    connection, like the real list queries; ``node(id:)`` follow-ups serve the rest.
    """

    def __init__(self, node: dict, first: dict[str, int] | None = None):
        self.node = node
        self.first = {"timelineItems": 100, "reviewThreads": 100, "labels": 20, **(first or {})}
        self.follow_ups: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        if "node(id" in body["query"]:
            return self._follow_up(body["query"], variables)
        page = self._first_page()
        if "search(" in body["query"]:
            data = {
                "search": {
                    "issueCount": 1,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [page],
                }
            }
        else:
            data = {"pr0": {"pullRequest": page}, "issue0": {"issue": page}}
        return httpx.Response(200, json={"data": data})

    def _first_page(self) -> dict:
        page = dict(self.node)
        for field, size in self.first.items():
            if field in page:
                nodes = page[field]["nodes"]
                page[field] = {
                    "nodes": nodes[:size],
                    "pageInfo": {
                        "hasNextPage": len(nodes) > size,
                        "endCursor": str(size) if len(nodes) > size else None,
                    },
                }
        return page

    def _follow_up(self, query: str, variables: dict) -> httpx.Response:
        field = next(f for f in self.first if f"{f}(first: 100, after: $after" in query)
        self.follow_ups.append({"field": field, **variables})
        assert variables["id"] == self.node["id"]
        nodes = self.node[field]["nodes"]
        start = int(variables["after"])
        end = start + 100
        page = {
            "nodes": nodes[start:end],
            "pageInfo": {"hasNextPage": end < len(nodes), "endCursor": str(end)},
        }
        return httpx.Response(200, json={"data": {"node": {field: page}}})


def serve(monkeypatch, fake: FakeGitHub) -> GitHubClient:
    def client_factory(**kwargs) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(fake), headers=kwargs.get("headers"))

    monkeypatch.setattr(github_api, "create_logging_client", client_factory)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    return GitHubClient()


def pr_client(monkeypatch, fake: FakeGitHub) -> PRClient:
    client = PRClient.__new__(PRClient)
    client._client = serve(monkeypatch, fake)
    return client


def chatter_history(n: int, letters: str) -> str:
    return "".join(letters[i % 2] for i in range(n))


def pr_history(n: int, end: str = "M") -> str:
    return "o" + chatter_history(n, "CH") + end


def issue_history(n: int, end: str = "X") -> str:
    return "o" + chatter_history(n, "CL").upper() + end


class TestPrHistory:
    def test_history_ends_with_true_terminal_event(self, monkeypatch):
        fake = FakeGitHub(pr_node(pr_chatter(250) + [merged(250)]))
        client = pr_client(monkeypatch, fake)

        [pr] = client._search_prs("is:pr", "alice", limit=10).prs

        assert pr.history == pr_history(250)
        assert pr.history.endswith("M")
        assert [f["field"] for f in fake.follow_ups] == ["timelineItems", "timelineItems"]

    def test_batched_lookup_by_ref_is_completed_too(self, monkeypatch):
        fake = FakeGitHub(pr_node(pr_chatter(150) + [merged(150)]))
        client = pr_client(monkeypatch, fake)

        [pr] = client.get_prs_by_ref(["owner/repo#1"], reference_user="alice").prs

        assert pr.history == pr_history(150)

    def test_exactly_one_page_needs_no_follow_up(self, monkeypatch):
        fake = FakeGitHub(pr_node(pr_chatter(99) + [merged(99)]))
        client = pr_client(monkeypatch, fake)

        [pr] = client._search_prs("is:pr", "alice", limit=10).prs

        assert pr.history == pr_history(99)
        assert fake.follow_ups == []

    def test_cap_leaves_visible_marker(self, monkeypatch, caplog):
        fake = FakeGitHub(pr_node(pr_chatter(700) + [merged(700)]))
        client = pr_client(monkeypatch, fake)

        with caplog.at_level(logging.WARNING):
            [pr] = client._search_prs("is:pr", "alice", limit=10).prs

        assert pr.history.endswith(TRUNCATION_MARKER)
        assert pr.history == "o" + chatter_history(500, "CH") + TRUNCATION_MARKER
        assert len(fake.follow_ups) == 4
        assert "timelineItems" in caplog.text

    def test_unresolved_threads_counted_past_first_page(self, monkeypatch):
        threads = [{"isResolved": i % 2 == 0} for i in range(250)]
        fake = FakeGitHub(pr_node(pr_chatter(1), threads=threads))
        client = pr_client(monkeypatch, fake)

        [pr] = client._search_prs("is:pr", "alice", limit=10).prs

        assert pr.unresolved_thread_count == 125
        assert {f["field"] for f in fake.follow_ups} == {"reviewThreads"}


class TestSnapshotDiff:
    def snapshot_at(self, monkeypatch, n_comments: int, name: str):
        fake = FakeGitHub(pr_node(pr_chatter(n_comments), state="OPEN"))
        client = pr_client(monkeypatch, fake)
        [pr] = client._search_prs("is:pr", "alice", limit=10).prs
        return make_snapshot(items=[item_from_pr(pr)], name=name)

    def test_event_past_the_first_100_is_detected(self, monkeypatch):
        before = self.snapshot_at(monkeypatch, 100, "before")
        after = self.snapshot_at(monkeypatch, 101, "after")

        [delta] = diff_snapshots(before, after).deltas

        assert delta.kind is ChangeKind.CHANGED
        assert delta.new_history_tail == "C"
        assert "history" in delta.changed_fields
        assert "activity" in delta.changed_fields


class TestReview:
    def test_raw_search_results_carry_the_full_timeline(self, monkeypatch):
        fake = FakeGitHub(pr_node(pr_chatter(250) + [merged(250)]))
        client = ReviewClient.__new__(ReviewClient)
        client._client = serve(monkeypatch, fake)

        [raw] = client._search_prs("is:pr", limit=10)
        review = client._process_pr_for_reviewer(raw, "carol")

        assert review is not None
        assert review.history == "O" + chatter_history(250, "CH") + "M"

    def test_cap_leaves_visible_marker(self, monkeypatch):
        fake = FakeGitHub(pr_node(pr_chatter(700) + [merged(700)]))
        client = ReviewClient.__new__(ReviewClient)
        client._client = serve(monkeypatch, fake)

        [raw] = client._search_prs("is:pr", limit=10)
        review = client._process_pr_for_reviewer(raw, "carol")

        assert review is not None
        assert review.history.endswith(TRUNCATION_MARKER)


class TestIssue:
    def test_history_ends_with_true_terminal_event(self, monkeypatch):
        fake = FakeGitHub(issue_node(issue_chatter(250) + [closed(250)]))
        client = IssueClient.__new__(IssueClient)
        client._client = serve(monkeypatch, fake)

        [issue] = client._search_issues("is:issue", "alice", limit=10).issues

        assert issue.history == issue_history(250)

    def test_batched_lookup_by_ref_is_completed_too(self, monkeypatch):
        fake = FakeGitHub(issue_node(issue_chatter(150) + [closed(150)]))
        client = IssueClient.__new__(IssueClient)
        client._client = serve(monkeypatch, fake)

        [issue] = client.get_issues_by_ref(["owner/repo#7"], reference_user="alice").issues

        assert issue.history.endswith("X")

    def test_cap_leaves_visible_marker(self, monkeypatch):
        fake = FakeGitHub(issue_node(issue_chatter(700) + [closed(700)]))
        client = IssueClient.__new__(IssueClient)
        client._client = serve(monkeypatch, fake)

        [issue] = client._search_issues("is:issue", "alice", limit=10).issues

        assert issue.history.endswith(TRUNCATION_MARKER)

    def test_labels_past_the_first_20_are_kept(self, monkeypatch):
        labels = [{"name": f"label-{i:02d}"} for i in range(45)]
        fake = FakeGitHub(issue_node(issue_chatter(1), labels=labels))
        client = IssueClient.__new__(IssueClient)
        client._client = serve(monkeypatch, fake)

        [issue] = client._search_issues("is:issue", "alice", limit=10).issues

        assert issue.labels == sorted(lbl["name"] for lbl in labels)


class TestCompleteConnection:
    SPEC = ConnectionSpec(type_name="Thing", field="things", selection="        name", cap=150)

    def test_cap_stops_between_pages_and_flags_the_connection(self, monkeypatch):
        node = {"id": "T_1", "things": {"nodes": [{"name": str(i)} for i in range(400)]}}
        fake = FakeGitHub(node, first={"things": 100})
        item = fake._first_page()
        client = serve(monkeypatch, fake)

        complete_connection(client, item, self.SPEC)

        assert len(item["things"]["nodes"]) == 200
        assert item["things"]["truncated"] is True

    def test_exhausted_connection_is_not_flagged(self, monkeypatch):
        node = {"id": "T_1", "things": {"nodes": [{"name": str(i)} for i in range(120)]}}
        fake = FakeGitHub(node, first={"things": 100})
        item = fake._first_page()

        complete_connection(serve(monkeypatch, fake), item, self.SPEC)

        assert len(item["things"]["nodes"]) == 120
        assert item["things"]["truncated"] is False


class TestFragments:
    @pytest.mark.parametrize("fragment", [PR_FIELDS_FRAGMENT, ISSUE_FIELDS_FRAGMENT])
    def test_fragment_requests_id_and_page_info(self, fragment):
        assert "\n    id\n" in fragment
        assert fragment.count("pageInfo { hasNextPage endCursor }") == 2

    def test_follow_up_query_repeats_the_fragment_selection(self):
        from src.pr.github_api import PR_TIMELINE

        query = PR_TIMELINE.follow_up_query()
        assert "node(id: $id)" in query
        assert "... on PullRequest" in query
        assert "after: $after" in query
        assert "MERGED_EVENT" in query
        assert "... on MergedEvent" in query

    def test_process_pr_data_without_completion_is_not_marked(self):
        pr = process_pr_data(pr_node(pr_chatter(2)), "alice")
        assert not pr.history.endswith(TRUNCATION_MARKER)
