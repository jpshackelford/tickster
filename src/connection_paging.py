"""Exhaust GraphQL connections that the list queries only fetch the first page of.

Search queries request ``first: N`` nested connections (timeline items, review
threads, labels) for many items at once. Items that exceed ``N`` come back
silently truncated. ``complete_connection`` follows ``pageInfo`` for just those
items, up to a safety cap, and records on the connection whether it still ended
up short.
"""

import logging
from dataclasses import dataclass

from src.board.github_api import GitHubClient

logger = logging.getLogger(__name__)

TRUNCATION_MARKER = "…"
PAGE_INFO = "pageInfo { hasNextPage endCursor }"
FOLLOW_UP_PAGE_SIZE = 100


@dataclass(frozen=True)
class ConnectionSpec:
    """One nested connection: how to select it and how far to follow it."""

    type_name: str
    field: str
    selection: str
    cap: int
    args: str = ""
    first: int = 100
    total_count: bool = False

    def fragment_field(self) -> str:
        return self._field_body(self.first, after=None)

    def _field_body(self, first: int, after: str | None) -> str:
        after_arg = ", after: $after" if after is not None else ""
        args = f", {self.args}" if self.args else ""
        total = "    totalCount\n" if self.total_count else ""
        return (
            f"{self.field}(first: {first}{after_arg}{args}) {{\n"
            f"{total}"
            f"    {PAGE_INFO}\n"
            f"    nodes {{\n{self.selection}\n    }}\n"
            f"}}"
        )

    def follow_up_query(self) -> str:
        return (
            "query($id: ID!, $after: String) {\n"
            "  node(id: $id) {\n"
            f"    ... on {self.type_name} {{\n"
            f"      {self._field_body(FOLLOW_UP_PAGE_SIZE, after='$after')}\n"
            "    }\n"
            "  }\n"
            "}"
        )


def complete_connection(client: GitHubClient, item: dict, spec: ConnectionSpec) -> None:
    """Fetch the remaining pages of ``item[spec.field]`` in place.

    Stops once ``spec.cap`` nodes are held. Sets ``truncated`` on the connection
    when pages remain after that.
    """
    conn = item[spec.field]
    page_info = conn.get("pageInfo") or {}
    conn["truncated"] = False
    query = spec.follow_up_query()

    while page_info.get("hasNextPage"):
        if len(conn["nodes"]) >= spec.cap:
            conn["truncated"] = True
            logger.warning(
                "%s on %s #%s has more than %d entries; ignoring the rest",
                spec.field,
                spec.type_name,
                item.get("number"),
                spec.cap,
            )
            return
        data = client.graphql(query, {"id": item["id"], "after": page_info["endCursor"]})
        page = data["node"][spec.field]
        conn["nodes"].extend(page["nodes"])
        page_info = page["pageInfo"]


def is_truncated(item: dict, field: str) -> bool:
    """Whether ``complete_connection`` gave up on ``item[field]``."""
    return bool((item.get(field) or {}).get("truncated"))
