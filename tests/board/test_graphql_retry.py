"""GraphQL retry/backoff and search page halving (#47)."""

import json
import time
from collections.abc import Callable

import httpx
import pytest

from src.board import github_api
from src.board.github_api import (
    MAX_RETRY_WAIT,
    MIN_SEARCH_PAGE_SIZE,
    SEARCH_PAGE_SIZE,
    GitHubClient,
    fetch_search_page,
)

SEARCH_QUERY = "query($query: String!, $limit: Int!) { search { issueCount } }"
OK_BODY = {"data": {"search": {"issueCount": 1}}}

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(github_api, "_sleep", recorded.append)
    return recorded


def make_client(handler: Handler) -> GitHubClient:
    client = GitHubClient(token="test-token")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def scripted(*responses: httpx.Response | Exception) -> tuple[Handler, list[dict]]:
    """Handler that replays ``responses`` in order and records each request body."""
    queue = list(responses)
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


def ok() -> httpx.Response:
    return httpx.Response(200, json=OK_BODY)


class TestGraphQLRetry:
    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_transient_status_is_retried(self, status, sleeps):
        handler, seen = scripted(httpx.Response(status), ok())
        with make_client(handler) as client:
            assert client.graphql(SEARCH_QUERY) == OK_BODY["data"]
        assert len(seen) == 2
        assert len(sleeps) == 1

    def test_gives_up_after_max_attempts(self, sleeps):
        handler, seen = scripted(httpx.Response(502))
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError) as exc:
            client.graphql(SEARCH_QUERY)
        assert exc.value.response.status_code == 502
        assert len(seen) == github_api.GRAPHQL_MAX_ATTEMPTS
        assert len(sleeps) == github_api.GRAPHQL_MAX_ATTEMPTS - 1

    def test_backoff_grows_with_jitter(self, sleeps):
        handler, _ = scripted(httpx.Response(504))
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            client.graphql(SEARCH_QUERY)
        first, second = sleeps
        assert 1.0 <= first <= 2.0
        assert 2.0 <= second <= 3.0

    def test_timeout_is_retried(self, sleeps):
        handler, seen = scripted(httpx.ReadTimeout("slow"), ok())
        with make_client(handler) as client:
            assert client.graphql(SEARCH_QUERY) == OK_BODY["data"]
        assert len(seen) == 2
        assert len(sleeps) == 1

    def test_persistent_timeout_raises(self, sleeps):
        handler, seen = scripted(httpx.ReadTimeout("slow"))
        with make_client(handler) as client, pytest.raises(httpx.ReadTimeout):
            client.graphql(SEARCH_QUERY)
        assert len(seen) == github_api.GRAPHQL_MAX_ATTEMPTS
        assert len(sleeps) == github_api.GRAPHQL_MAX_ATTEMPTS - 1

    @pytest.mark.parametrize("status", [400, 401, 404, 500])
    def test_non_transient_status_is_not_retried(self, status, sleeps):
        handler, seen = scripted(httpx.Response(status), ok())
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 1
        assert sleeps == []

    def test_plain_403_is_not_retried(self, sleeps):
        handler, seen = scripted(httpx.Response(403, text="Resource not accessible"), ok())
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 1
        assert sleeps == []

    def test_mutation_is_not_retried(self, sleeps):
        handler, seen = scripted(httpx.Response(502), ok())
        mutation = "\n  mutation($id: ID!) { deleteProjectV2Item(input: {}) { deletedItemId } }"
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            client.graphql(mutation, {"id": "x"})
        assert len(seen) == 1
        assert sleeps == []

    def test_mutation_word_inside_a_query_still_retries(self, sleeps):
        handler, seen = scripted(httpx.Response(502), ok())
        query = 'query { search(query: "mutation testing") { issueCount } }'
        with make_client(handler) as client:
            client.graphql(query)
        assert len(seen) == 2
        assert len(sleeps) == 1


class TestRateLimitRetry:
    def test_retry_after_header_is_respected(self, sleeps):
        handler, seen = scripted(httpx.Response(403, headers={"retry-after": "3"}), ok())
        with make_client(handler) as client:
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 2
        assert sleeps == [3.5]

    def test_unparseable_retry_after_falls_back_to_backoff(self, sleeps):
        handler, _ = scripted(httpx.Response(429, headers={"retry-after": "soon"}), ok())
        with make_client(handler) as client:
            client.graphql(SEARCH_QUERY)
        assert 1.0 <= sleeps[0] <= 2.0

    def test_429_without_headers_backs_off(self, sleeps):
        handler, seen = scripted(httpx.Response(429), ok())
        with make_client(handler) as client:
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 2
        assert 1.0 <= sleeps[0] <= 2.0

    def test_secondary_rate_limit_message_waits_a_minute(self, sleeps):
        body = {"message": "You have exceeded a secondary rate limit."}
        handler, seen = scripted(httpx.Response(403, json=body), ok())
        with make_client(handler) as client:
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 2
        assert sleeps == [MAX_RETRY_WAIT]

    def test_primary_limit_resetting_soon_is_waited_out(self, sleeps):
        reset = str(int(time.time()) + 5)
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}
        handler, seen = scripted(httpx.Response(403, headers=headers), ok())
        with make_client(handler) as client:
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 2
        assert 0 < sleeps[0] <= 7

    def test_primary_limit_without_reset_backs_off(self, sleeps):
        headers = {"x-ratelimit-remaining": "0"}
        handler, seen = scripted(httpx.Response(403, headers=headers), ok())
        with make_client(handler) as client:
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 2
        assert 1.0 <= sleeps[0] <= 2.0

    def test_primary_limit_resetting_later_fails_fast(self, sleeps):
        reset = str(int(time.time()) + 3600)
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}
        handler, seen = scripted(httpx.Response(403, headers=headers), ok())
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            client.graphql(SEARCH_QUERY)
        assert len(seen) == 1
        assert sleeps == []


class TestFetchSearchPage:
    def test_caps_page_size(self, sleeps):
        handler, seen = scripted(ok())
        with make_client(handler) as client:
            search, size = fetch_search_page(client, SEARCH_QUERY, {"cursor": None}, 100)
        assert search == OK_BODY["data"]["search"]
        assert size == SEARCH_PAGE_SIZE
        assert seen[0]["variables"] == {"cursor": None, "limit": SEARCH_PAGE_SIZE}
        assert sleeps == []

    def test_smaller_request_is_kept(self, sleeps):  # noqa: ARG002
        handler, seen = scripted(ok())
        with make_client(handler) as client:
            _, size = fetch_search_page(client, SEARCH_QUERY, {}, 7)
        assert size == 7
        assert seen[0]["variables"]["limit"] == 7

    def test_gateway_timeout_halves_the_page(self, sleeps):  # noqa: ARG002
        attempts = github_api.GRAPHQL_MAX_ATTEMPTS
        handler, seen = scripted(*[httpx.Response(504)] * attempts, ok())
        with make_client(handler) as client:
            _, size = fetch_search_page(client, SEARCH_QUERY, {}, 100)
        assert size == SEARCH_PAGE_SIZE // 2
        limits = [body["variables"]["limit"] for body in seen]
        assert limits == [SEARCH_PAGE_SIZE] * attempts + [SEARCH_PAGE_SIZE // 2]

    def test_client_timeout_halves_the_page(self, sleeps):  # noqa: ARG002
        attempts = github_api.GRAPHQL_MAX_ATTEMPTS
        handler, _ = scripted(*[httpx.ReadTimeout("slow")] * attempts, ok())
        with make_client(handler) as client:
            _, size = fetch_search_page(client, SEARCH_QUERY, {}, 20)
        assert size == 10

    def test_gateway_timeout_warning_is_one_line_with_the_status(self, sleeps, caplog):  # noqa: ARG002
        attempts = github_api.GRAPHQL_MAX_ATTEMPTS
        handler, _ = scripted(*[httpx.Response(504)] * attempts, ok())
        with (
            make_client(handler) as client,
            caplog.at_level("WARNING", logger=github_api.logger.name),
        ):
            fetch_search_page(client, SEARCH_QUERY, {}, 100)
        (message,) = [r.getMessage() for r in caplog.records if "timed out" in r.getMessage()]
        assert (
            message == f"Search page timed out (504); retrying with {SEARCH_PAGE_SIZE // 2} items"
        )

    def test_client_timeout_warning_is_one_line_with_the_exception_name(self, sleeps, caplog):  # noqa: ARG002
        attempts = github_api.GRAPHQL_MAX_ATTEMPTS
        handler, _ = scripted(*[httpx.ReadTimeout("slow")] * attempts, ok())
        with (
            make_client(handler) as client,
            caplog.at_level("WARNING", logger=github_api.logger.name),
        ):
            fetch_search_page(client, SEARCH_QUERY, {}, 20)
        (message,) = [r.getMessage() for r in caplog.records if "timed out" in r.getMessage()]
        assert message == "Search page timed out (ReadTimeout); retrying with 10 items"

    def test_gives_up_at_minimum_size(self, sleeps):  # noqa: ARG002
        handler, seen = scripted(httpx.Response(502))
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            fetch_search_page(client, SEARCH_QUERY, {}, 100)
        sizes = sorted({body["variables"]["limit"] for body in seen}, reverse=True)
        assert sizes == [25, 12, 6, MIN_SEARCH_PAGE_SIZE]

    def test_other_errors_are_not_halved(self, sleeps):  # noqa: ARG002
        handler, seen = scripted(httpx.Response(500))
        with make_client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            fetch_search_page(client, SEARCH_QUERY, {}, 100)
        assert len(seen) == 1

    def test_graphql_errors_are_not_halved(self, sleeps):  # noqa: ARG002
        body = {"errors": [{"message": "Something went wrong"}]}
        handler, seen = scripted(httpx.Response(200, json=body))
        with make_client(handler) as client, pytest.raises(RuntimeError):
            fetch_search_page(client, SEARCH_QUERY, {}, 100)
        assert len(seen) == 1
