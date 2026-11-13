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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.date_window import DateWindow
from src.issue.models import Milestone
from src.pr.reviewers import ReviewerState
from src.snapshot.rows import (
    KIND_ISSUE,
    KIND_PR,
    KIND_REVIEW,
    ROW_FIELDS,
    VALID_KINDS,
    as_bool,
    as_int,
    as_opt_int,
    as_opt_str,
    as_opt_strs,
    as_str,
    decode_row,
    encode_field,
    read_field,
)

SCHEMA_VERSION = 2

__all__ = ["KIND_ISSUE", "KIND_PR", "KIND_REVIEW", "VALID_KINDS"]


class ChangeKind(Enum):
    """How an item differs between two snapshots."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class WindowScope:
    """A date window as typed, so rolling windows stay comparable day to day.

    A relative window records ``since_days`` (not the date it resolves to
    today); an absolute one records its bounds as ISO dates.
    """

    field: str
    since_days: int | None = None
    after: str | None = None
    before: str | None = None

    @classmethod
    def from_window(cls, window: DateWindow | None) -> WindowScope | None:
        if window is None:
            return None
        if window.since_days is not None:
            return cls(field=window.field, since_days=window.since_days)
        return cls(
            field=window.field,
            after=window.after.isoformat() if window.after else None,
            before=window.before.isoformat() if window.before else None,
        )

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "since_days": self.since_days,
            "after": self.after,
            "before": self.before,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WindowScope:
        return cls(
            field=read_field(data, "field", as_str),
            since_days=read_field(data, "since_days", as_opt_int),
            after=read_field(data, "after", as_opt_str),
            before=read_field(data, "before", as_opt_str),
        )

    def describe(self) -> str:
        if self.since_days is not None:
            return f"{self.field} since {self.since_days}d ago"
        if self.after and self.before:
            return f"{self.field} {self.after}..{self.before}"
        if self.after:
            return f"{self.field} ≥ {self.after}"
        return f"{self.field} ≤ {self.before}"


@dataclass(frozen=True)
class SnapshotScope:
    """The query filter set that produced a snapshot.

    Two snapshots can only be meaningfully diffed when their scopes match
    (same board, author or all-authors, repos, refs, states, labels, PR filter, sort, limit,
    date window). `fingerprint`
    yields a stable short digest used to detect scope drift between runs.

    The `from_{pr,issue,review}_args` factories are the only supported way
    to build a scope from CLI inputs — they encode which filter fields each
    kind actually honors, so new CLI filters can't silently diverge from the
    scope hash. Constructing `SnapshotScope(...)` directly is still allowed
    for tests and round-trips but discouraged elsewhere.
    """

    board: str | None = None
    author: str | None = None
    all_authors: bool = False  # pr/issue list: --all-authors
    reviewer: str | None = None
    # Repos actually queried (explicit --repo, else the board's list at run time),
    # sorted, so editing a board's repos is flagged as a scope change.
    repos: tuple[str, ...] | None = None
    refs: tuple[str, ...] | None = None  # explicit owner/repo#N args, sorted
    states: tuple[str, ...] | None = None
    labels: tuple[str, ...] | None = None
    not_labels: tuple[str, ...] | None = None  # issue list: --not-label, lowercased and sorted
    exclude_authors: tuple[str, ...] | None = None
    include_all: bool = False  # review: --all
    pr_filter: str | None = None  # issue list: "no-pr" (--no-pr) or "has-pr" (--has-pr)
    blocked_filter: str | None = None  # issue list: "blocked" (--blocked) or "unblocked"
    sort: tuple[str, ...] | None = None  # issue list: --sort keys, in the order given
    limit: int = 100
    window: WindowScope | None = None

    def to_dict(self) -> dict:
        return {
            "board": self.board,
            "author": self.author,
            "all_authors": self.all_authors,
            "reviewer": self.reviewer,
            "repos": list(self.repos) if self.repos else None,
            "refs": list(self.refs) if self.refs else None,
            "states": list(self.states) if self.states else None,
            "labels": list(self.labels) if self.labels else None,
            "not_labels": list(self.not_labels) if self.not_labels else None,
            "exclude_authors": list(self.exclude_authors) if self.exclude_authors else None,
            "include_all": self.include_all,
            "pr_filter": self.pr_filter,
            "blocked_filter": self.blocked_filter,
            "sort": list(self.sort) if self.sort else None,
            "limit": self.limit,
            "window": self.window.to_dict() if self.window else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SnapshotScope:
        window = read_field(data, "window", lambda w: w)
        return cls(
            board=read_field(data, "board", as_opt_str),
            author=read_field(data, "author", as_opt_str),
            all_authors=read_field(data, "all_authors", as_bool),
            reviewer=read_field(data, "reviewer", as_opt_str),
            repos=read_field(data, "repos", as_opt_strs),
            refs=read_field(data, "refs", as_opt_strs),
            states=read_field(data, "states", as_opt_strs),
            labels=read_field(data, "labels", as_opt_strs),
            not_labels=read_field(data, "not_labels", as_opt_strs),
            exclude_authors=read_field(data, "exclude_authors", as_opt_strs),
            include_all=read_field(data, "include_all", as_bool),
            pr_filter=read_field(data, "pr_filter", as_opt_str),
            blocked_filter=read_field(data, "blocked_filter", as_opt_str),
            sort=read_field(data, "sort", as_opt_strs),
            limit=read_field(data, "limit", as_int),
            window=WindowScope.from_dict(window) if window is not None else None,
        )

    @classmethod
    def from_pr_args(
        cls,
        *,
        board: str | None,
        author: str | None,
        reviewer: str | None,
        repos: list[str] | None,
        refs: list[str] | None,
        states: list[str] | None,
        limit: int,
        window: DateWindow | None = None,
        all_authors: bool = False,
    ) -> SnapshotScope:
        """Build the scope that `pr list` queries contribute to the hash."""
        return cls(
            board=board,
            author=author,
            all_authors=all_authors,
            reviewer=reviewer,
            repos=tuple(sorted(repos)) if repos else None,
            refs=tuple(sorted(refs)) if refs else None,
            states=tuple(states) if states else None,
            limit=limit,
            window=WindowScope.from_window(window),
        )

    @classmethod
    def from_issue_args(
        cls,
        *,
        board: str | None,
        author: str | None,
        repos: list[str] | None,
        refs: list[str] | None,
        states: list[str] | None,
        labels: list[str] | None,
        limit: int,
        window: DateWindow | None = None,
        all_authors: bool = False,
        not_labels: list[str] | None = None,
        pr_filter: str | None = None,
        blocked_filter: str | None = None,
        sort: Sequence[str] | None = None,
    ) -> SnapshotScope:
        """Build the scope that `issue list` queries contribute to the hash."""
        return cls(
            board=board,
            author=author,
            all_authors=all_authors,
            repos=tuple(sorted(repos)) if repos else None,
            refs=tuple(sorted(refs)) if refs else None,
            states=tuple(states) if states else None,
            labels=tuple(labels) if labels else None,
            not_labels=tuple(sorted({lbl.lower() for lbl in not_labels})) if not_labels else None,
            pr_filter=pr_filter,
            blocked_filter=blocked_filter,
            sort=tuple(sort) if sort else None,
            limit=limit,
            window=WindowScope.from_window(window),
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
        window: DateWindow | None = None,
    ) -> SnapshotScope:
        """Build the scope that `review` queries contribute to the hash."""
        return cls(
            board=board,
            author=author,
            reviewer=reviewer,
            repos=tuple(sorted(repos)) if repos else None,
            states=tuple(states) if states else None,
            exclude_authors=tuple(exclude_authors) if exclude_authors else None,
            include_all=include_all,
            limit=limit,
            window=WindowScope.from_window(window),
        )

    def fingerprint(self) -> str:
        """Stable short digest of the scope, used to detect scope drift."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def _as_list(value: Any) -> list:
    if not isinstance(value, list):
        raise TypeError(value)
    return value


@dataclass(frozen=True)
class ItemSnapshot:
    """One row: an issue, PR or review.

    The attributes are the row keys (see `rows.ROW_FIELDS`). A row serializes only
    the keys of its `kind`; the attributes of other kinds keep their neutral defaults.
    `ref` is "owner/repo#NNN" and identifies the row across runs.
    """

    ref: str
    kind: str
    repo: str
    number: int
    url: str
    title: str
    history: str
    state: str
    author: str
    created_at: str  # ISO-8601 UTC
    last_activity: str  # ISO-8601 UTC
    labels: tuple[str, ...] = ()
    linked_pr: str | None = None  # issue
    closed_at: str | None = None  # issue: ISO-8601 UTC; None while open
    open_blockers: tuple[str, ...] = ()  # issue: refs of open blockers ("?" = unreadable)
    blocking: int = 0  # issue: open issues this one blocks
    parent: str | None = None  # issue: parent issue ref
    milestone: Milestone | None = None  # issue
    draft: bool = False  # pr / review
    ci: str = ""  # pr / review
    unresolved_threads: int = 0  # pr / review
    head: str | None = None  # pr / review: full head commit SHA
    review_decision: str | None = None  # pr / review: GitHub reviewDecision
    merge_state: str | None = None  # pr / review: GitHub mergeStateStatus
    mergeable: str | None = None  # pr / review: GitHub mergeable
    reviewers: tuple[ReviewerState, ...] = ()  # pr / review: per-reviewer state
    step_status: dict[str, str] | None = None  # pr: step name to status; None = not evaluated
    review_status: str = ""  # review
    wait_seconds: float = 0.0  # review

    def to_dict(self) -> dict:
        return {name: encode_field(name, getattr(self, name)) for name in ROW_FIELDS[self.kind]}

    @classmethod
    def from_dict(cls, data: Any) -> ItemSnapshot:
        return cls(**decode_row(data))


@dataclass(frozen=True)
class Snapshot:
    """A full captured query result."""

    kind: str  # KIND_PR | KIND_ISSUE | KIND_REVIEW
    name: str
    captured_at: str  # ISO-8601 UTC
    scope: SnapshotScope
    items: tuple[ItemSnapshot, ...]
    schema: int = SCHEMA_VERSION
    has_more: bool = False  # the query matched more rows than `--limit` kept

    @property
    def scope_hash(self) -> str:
        return self.scope.fingerprint()

    @property
    def items_by_ref(self) -> dict[str, ItemSnapshot]:
        return {it.ref: it for it in self.items}

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "kind": self.kind,
            "name": self.name,
            "captured_at": self.captured_at,
            "scope": self.scope.to_dict(),
            "scope_hash": self.scope_hash,
            "has_more": self.has_more,
            "items": [it.to_dict() for it in self.items],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Snapshot:
        """Read a snapshot; `ValueError` says why `data` is not one written by this tkt."""
        if not isinstance(data, dict):
            raise ValueError("the top level is not a JSON object")
        schema = read_field(data, "schema", lambda v: v)
        if schema != SCHEMA_VERSION:
            raise ValueError(f"schema {schema}, this tkt writes schema {SCHEMA_VERSION}")
        kind = read_field(data, "kind", as_str)
        if kind not in VALID_KINDS:
            raise ValueError(f"field 'kind' has the wrong type: {kind!r}")
        scope = read_field(data, "scope", SnapshotScope.from_dict)
        raw_items = read_field(data, "items", _as_list)
        items = tuple(ItemSnapshot.from_dict(it) for it in raw_items)
        for it in items:
            if it.kind != kind:
                raise ValueError(f"a {it.kind} row in a {kind} snapshot")
        return cls(
            schema=schema,
            kind=kind,
            name=read_field(data, "name", as_str),
            captured_at=read_field(data, "captured_at", as_str),
            scope=scope,
            items=items,
            has_more=read_field(data, "has_more", as_bool),
        )

    @classmethod
    def make(
        cls,
        *,
        kind: str,
        name: str,
        scope: SnapshotScope,
        items: list[ItemSnapshot],
        has_more: bool = False,
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
            has_more=has_more,
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
    reviewer_changes: tuple[str, ...] = ()  # per-reviewer transitions, e.g. "bob ↻ re-requested"
    step_changes: tuple[str, ...] = ()  # e.g. "request re-review: done → needed"
    blocker_note: str = ""  # issue: "unblocked" | "blocked" | "blockers changed"
    events_since: tuple[dict, ...] | None = None  # `pr list --format json`: new timeline events
    events_truncated: bool = False  # the timeline fetch hit its cap
    steps: tuple[dict, ...] | None = None  # `pr list --format json`: step results with evidence

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
    baseline_found: bool = True

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
            "baseline": "found" if self.baseline_found else "missing",
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
    data = {
        "key": d.key,
        "kind": d.kind.value,
        "new_history_tail": d.new_history_tail,
        "changed_fields": list(d.changed_fields),
        "disappearance_reason": d.disappearance_reason,
        "prev": d.prev.to_dict() if (include_bodies and d.prev) else None,
        "curr": d.curr.to_dict() if (include_bodies and d.curr) else None,
    }
    if d.reviewer_changes:
        data["reviewer_changes"] = list(d.reviewer_changes)
    if d.step_changes:
        data["step_changes"] = list(d.step_changes)
    if d.blocker_note:
        data["blocker_note"] = d.blocker_note
    if d.events_since is not None:
        data["events_since"] = list(d.events_since)
    if d.events_truncated:
        data["events_truncated"] = True
    if d.steps is not None:
        data["steps"] = list(d.steps)
    return data
