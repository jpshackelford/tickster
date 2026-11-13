"""A GraphQL endpoint for ``show`` tests, served through a real httpx client.

It holds each item's full connections and pages them out like GitHub: the first
query returns the first ``PAGE_SIZES[field]`` nodes with a ``pageInfo``; a
``node(id:)`` follow-up returns the next 100.
"""

from __future__ import annotations

import copy
import json
import re

import httpx

from src.board.github_api import GitHubClient

PAGE_SIZES = {
    "timelineItems": 100,
    "reviewThreads": 50,
    "comments": 50,
    "reviewRequests": 20,
    "latestReviews": 20,
    "labels": 20,
    "blockedBy": 50,
    "blocking": 50,
}
FOLLOW_UP_SIZE = 100
_FOLLOW_UP_FIELD = re.compile(r"on \w+ \{\s+(\w+)\(first")


def page(nodes: list, after: str | None, size: int) -> dict:
    start = int(after) if after else 0
    end = start + size
    return {
        "pageInfo": {"hasNextPage": end < len(nodes), "endCursor": str(end)},
        "nodes": nodes[start:end],
    }


def _first_pages(obj):
    if isinstance(obj, list):
        return [_first_pages(o) for o in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for key, value in obj.items():
        if key in PAGE_SIZES and isinstance(value, dict) and "nodes" in value:
            paged = page(value["nodes"], None, PAGE_SIZES[key])
            out[key] = {**value, **paged, "nodes": _first_pages(paged["nodes"])}
        else:
            out[key] = _first_pages(value)
    return out


def _find(obj, node_id: str):
    if isinstance(obj, dict):
        if obj.get("id") == node_id:
            return obj
        for value in obj.values():
            if (found := _find(value, node_id)) is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            if (found := _find(value, node_id)) is not None:
                return found
    return None


class FakeGitHub:
    """Serves one item (``kind`` is "pullRequest" or "issue") for the show queries."""

    def __init__(self, kind: str, item: dict | None):
        self.kind = kind
        self.item = item
        self.requests: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        query, variables = body["query"], body["variables"]
        if "$after" in query:
            owner = _find(self.item, variables["id"])
            match = _FOLLOW_UP_FIELD.search(query)
            assert owner is not None and match is not None
            field = match.group(1)
            nodes = owner[field]["nodes"]
            data = {"node": {field: page(nodes, variables["after"], FOLLOW_UP_SIZE)}}
            return httpx.Response(200, json={"data": data})
        found = None if self.item is None else _first_pages(copy.deepcopy(self.item))
        return httpx.Response(200, json={"data": {"repository": {self.kind: found}}})

    def client(self) -> GitHubClient:
        gh = GitHubClient.__new__(GitHubClient)
        gh._client = httpx.Client(transport=httpx.MockTransport(self.handle))
        return gh
