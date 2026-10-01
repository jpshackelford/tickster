"""Snapshot and diff support for pr/issue/review list queries.

Captures a snapshot of a query's result set to disk so a later run of the
same query can be diffed against it, surfacing which rows are new, which
rows gained new events, and which rows fell out of scope since the previous
run. Lets an agent polling hourly reason about *change* instead of
rediscovering the full state each time.
"""

from src.snapshot.models import (
    KIND_ISSUE,
    KIND_PR,
    KIND_REVIEW,
    ChangeKind,
    DiffResult,
    ItemDelta,
    ItemSnapshot,
    Snapshot,
    SnapshotScope,
)

__all__ = [
    "KIND_ISSUE",
    "KIND_PR",
    "KIND_REVIEW",
    "ChangeKind",
    "DiffResult",
    "ItemDelta",
    "ItemSnapshot",
    "Snapshot",
    "SnapshotScope",
]
