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
from dataclasses import asdict, dataclass
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
    (same board, author, repos, states, labels, limit). `fingerprint`
    yields a stable short digest used to detect scope drift between runs.

    The `from_{pr,issue,review}_args` factories are the only supported way
    to build a scope from CLI inputs — they encode which filter fields each
    kind actually honors, so new CLI filters can't silently diverge from the
    scope hash. Constructing `SnapshotScope(...)` directly is still allowed
    for tests and round-trips but discouraged elsewhere.
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

    @classmethod
    def from_pr_args(
        cls,
        *,
        board: str | None,
        author: str | None,
        reviewer: str | None,
        repos: list[str] | None,
        states: list[str] | None,
        limit: int,
    ) -> SnapshotScope:
        """Build the scope that `pr list` queries contribute to the hash."""
        return cls(
            board=board,
            author=author,
            reviewer=reviewer,
            repos=tuple(repos) if repos else None,
            states=tuple(states) if states else None,
            limit=limit,
        )

    @classmethod
    def from_issue_args(
        cls,
        *,
        board: str | None,
        author: str | None,
        repos: list[str] | None,
        states: list[str] | None,
        labels: list[str] | None,
        limit: int,
    ) -> SnapshotScope:
        """Build the scope that `issue list` queries contribute to the hash."""
        return cls(
            board=board,
            author=author,
            repos=tuple(repos) if repos else None,
            states=tuple(states) if states else None,
            labels=tuple(labels) if labels else None,
            limit=limit,
        )

    @classmethod
    def from_review_args(
        cls,
        *,
        board: str | None,
        author: str | None,
        reviewer: str | None,
        repos: list[str] | None,
        states: list[str] | None,
        exclude_authors: list[str] | None,
        include_all: bool,
        limit: int,
    ) -> SnapshotScope:
        """Build the scope that `review` queries contribute to the hash."""
        return cls(
            board=board,
            author=author,
            reviewer=reviewer,
            repos=tuple(repos) if repos else None,
            states=tuple(states) if states else None,
            exclude_authors=tuple(exclude_authors) if exclude_authors else None,
            include_all=include_all,
            limit=limit,
        )

    def fingerprint(self) -> str:
        """Stable short digest of the scope, used to detect scope drift."""
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
        return self.scope.fingerprint()

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
        schema = int(data.get("schema", SCHEMA_VERSION))
        if schema != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported snapshot schema version: {schema} "
                f"(this build understands {SCHEMA_VERSION}); "
                "delete the snapshot or upgrade/downgrade tkt"
            )
        kind = data["kind"]
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid snapshot kind: {kind!r}")
        return cls(
            schema=schema,
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
            "deltas": [_delta_to_dict(d) for d in self.deltas],
        }


def _delta_to_dict(d: ItemDelta) -> dict:
    """Serialize a delta.

    For UNCHANGED entries we skip the full `prev`/`curr` bodies — they are
    byte-for-byte duplicates of each other, and a 100-row snapshot would
    otherwise emit ~200 full item bodies to describe "nothing happened".
    Consumers can always re-load the baseline/current snapshots to recover
    the untouched rows.
    """
    include_bodies = d.kind is not ChangeKind.UNCHANGED
    return {
        "key": d.key,
        "kind": d.kind.value,
        "new_history_tail": d.new_history_tail,
        "changed_fields": list(d.changed_fields),
        "disappearance_reason": d.disappearance_reason,
        "prev": d.prev.to_dict() if (include_bodies and d.prev) else None,
        "curr": d.curr.to_dict() if (include_bodies and d.curr) else None,
    }
