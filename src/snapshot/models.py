"""Snapshot and diff data models.

A `Snapshot` captures the fields of a `pr list` / `issue list` / `review`
result that are relevant to detecting change — history string, state,
labels, CI status, thread count, last activity — along with the query
scope that produced it. Snapshots serialize to a stable JSON schema and
compare deterministically via `src.snapshot.diff.diff_snapshots`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum

SCHEMA_VERSION = 1

KIND_PR = "pr"
KIND_ISSUE = "issue"
KIND_REVIEW = "review"
VALID_KINDS = (KIND_PR, KIND_ISSUE, KIND_REVIEW)


class ChangeKind(Enum):
    """How an item differs between two snapshots."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class SnapshotScope:
    """The query filter set that produced a snapshot.

    Two snapshots can only be meaningfully diffed when their scopes match
    (same board, author, repos, states, labels, limit). `hash_` yields a
    stable short digest used to detect scope drift between runs.
    """

    board: str | None = None
    author: str | None = None
    reviewer: str | None = None
    repos: tuple[str, ...] | None = None
    states: tuple[str, ...] | None = None
    labels: tuple[str, ...] | None = None
    exclude_authors: tuple[str, ...] | None = None
    include_all: bool = False  # review: --all
    limit: int = 100

    def to_dict(self) -> dict:
        return {
            "board": self.board,
            "author": self.author,
            "reviewer": self.reviewer,
            "repos": list(self.repos) if self.repos else None,
            "states": list(self.states) if self.states else None,
            "labels": list(self.labels) if self.labels else None,
            "exclude_authors": (list(self.exclude_authors) if self.exclude_authors else None),
            "include_all": self.include_all,
            "limit": self.limit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SnapshotScope:
        return cls(
            board=data.get("board"),
            author=data.get("author"),
            reviewer=data.get("reviewer"),
            repos=tuple(data["repos"]) if data.get("repos") else None,
            states=tuple(data["states"]) if data.get("states") else None,
            labels=tuple(data["labels"]) if data.get("labels") else None,
            exclude_authors=(
                tuple(data["exclude_authors"]) if data.get("exclude_authors") else None
            ),
            include_all=bool(data.get("include_all", False)),
            limit=int(data.get("limit", 100)),
        )

    def hash_(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class ItemSnapshot:
    """Per-row fields persisted in a snapshot.

    Only the fields the diff reasons about — not the raw GraphQL timeline.
    `key` is "owner/repo#NNN" and uniquely identifies the row across runs.
    """

    key: str
    repo: str
    number: int
    title: str
    history: str
    state: str
    author: str
    last_activity: str  # ISO-8601 UTC
    labels: tuple[str, ...] = ()
    ci_status: str | None = None  # pr / review
    is_draft: bool = False  # pr / review
    unresolved_thread_count: int = 0  # pr / review
    linked_pr: str | None = None  # issue
    review_status: str | None = None  # review
    wait_seconds: float | None = None  # review

    def to_dict(self) -> dict:
        d = asdict(self)
        d["labels"] = list(self.labels)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ItemSnapshot:
        return cls(
            key=data["key"],
            repo=data["repo"],
            number=int(data["number"]),
            title=data.get("title", ""),
            history=data.get("history", ""),
            state=data.get("state", ""),
            author=data.get("author", ""),
            last_activity=data.get("last_activity", ""),
            labels=tuple(data.get("labels", [])),
            ci_status=data.get("ci_status"),
            is_draft=bool(data.get("is_draft", False)),
            unresolved_thread_count=int(data.get("unresolved_thread_count", 0)),
            linked_pr=data.get("linked_pr"),
            review_status=data.get("review_status"),
            wait_seconds=data.get("wait_seconds"),
        )


@dataclass(frozen=True)
class Snapshot:
    """A full captured query result."""

    kind: str  # KIND_PR | KIND_ISSUE | KIND_REVIEW
    name: str
    captured_at: str  # ISO-8601 UTC
    scope: SnapshotScope
    items: tuple[ItemSnapshot, ...]
    schema: int = SCHEMA_VERSION

    @property
    def scope_hash(self) -> str:
        return self.scope.hash_()

    @property
    def items_by_key(self) -> dict[str, ItemSnapshot]:
        return {it.key: it for it in self.items}

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "kind": self.kind,
            "name": self.name,
            "captured_at": self.captured_at,
            "scope": self.scope.to_dict(),
            "scope_hash": self.scope_hash,
            "items": [it.to_dict() for it in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        kind = data["kind"]
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid snapshot kind: {kind!r}")
        return cls(
            schema=int(data.get("schema", SCHEMA_VERSION)),
            kind=kind,
            name=data["name"],
            captured_at=data["captured_at"],
            scope=SnapshotScope.from_dict(data.get("scope", {})),
            items=tuple(ItemSnapshot.from_dict(it) for it in data.get("items", [])),
        )

    @classmethod
    def make(
        cls,
        *,
        kind: str,
        name: str,
        scope: SnapshotScope,
        items: list[ItemSnapshot],
    ) -> Snapshot:
        """Build a fresh snapshot with captured_at = now (UTC)."""
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid snapshot kind: {kind!r}")
        return cls(
            kind=kind,
            name=name,
            captured_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            scope=scope,
            items=tuple(items),
        )


@dataclass(frozen=True)
class ItemDelta:
    """Diff of one item between two snapshots.

    `new_history_tail` holds the suffix of `curr.history` that was not
    present in `prev.history` — the characters we bracket in the rendered
    diff. Empty when the history string did not grow.
    """

    key: str
    kind: ChangeKind
    prev: ItemSnapshot | None
    curr: ItemSnapshot | None
    new_history_tail: str = ""
    changed_fields: tuple[str, ...] = ()
    disappearance_reason: str | None = None  # for REMOVED

    @property
    def display_item(self) -> ItemSnapshot:
        """The item to render for this delta (curr if present, else prev)."""
        item = self.curr or self.prev
        if item is None:
            raise ValueError(f"delta {self.key} has no item")
        return item


@dataclass(frozen=True)
class DiffResult:
    """Full comparison of two snapshots."""

    prev: Snapshot
    curr: Snapshot
    deltas: tuple[ItemDelta, ...]
    scope_matches: bool

    @property
    def counts(self) -> dict[ChangeKind, int]:
        out: dict[ChangeKind, int] = dict.fromkeys(ChangeKind, 0)
        for d in self.deltas:
            out[d.kind] += 1
        return out

    def to_dict(self) -> dict:
        counts = {k.value: v for k, v in self.counts.items()}
        return {
            "schema": SCHEMA_VERSION,
            "prev": {
                "kind": self.prev.kind,
                "name": self.prev.name,
                "captured_at": self.prev.captured_at,
                "scope_hash": self.prev.scope_hash,
            },
            "curr": {
                "kind": self.curr.kind,
                "name": self.curr.name,
                "captured_at": self.curr.captured_at,
                "scope_hash": self.curr.scope_hash,
            },
            "scope_matches": self.scope_matches,
            "counts": counts,
            "deltas": [
                {
                    "key": d.key,
                    "kind": d.kind.value,
                    "new_history_tail": d.new_history_tail,
                    "changed_fields": list(d.changed_fields),
                    "disappearance_reason": d.disappearance_reason,
                    "prev": d.prev.to_dict() if d.prev else None,
                    "curr": d.curr.to_dict() if d.curr else None,
                }
                for d in self.deltas
            ],
        }


# Suppress unused-import warnings for `field` (kept for future extensions).
_ = field
