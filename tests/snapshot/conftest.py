"""Shared fixtures for snapshot tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.board import config as board_config
from src.snapshot.models import (
    ItemSnapshot,
    Snapshot,
    SnapshotScope,
)
from src.snapshot.rows import item_url


@pytest.fixture
def tkt_home(tmp_path: Path, monkeypatch) -> Path:
    """Point TKT_HOME at a tmp dir so snapshot store writes don't escape."""
    monkeypatch.setattr(board_config, "TKT_HOME", tmp_path)
    monkeypatch.setattr(board_config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(board_config, "CACHE_FILE", tmp_path / "board-cache.db")
    return tmp_path


def make_item(
    *,
    ref: str = "owner/repo#1",
    kind: str = "pr",
    history: str = "oC",
    state: str = "open",
    ci: str | None = None,
    labels: tuple[str, ...] = (),
    unresolved: int = 0,
    last_activity: str = "2026-09-30T22:00:00Z",
    linked_pr: str | None = None,
    review_status: str | None = None,
    **fields,
) -> ItemSnapshot:
    """Convenience constructor for ItemSnapshot in tests.

    `ci` defaults to "green" for pr and review rows and is unused for issues;
    `review_status` makes the row a review row.
    """
    if review_status is not None:
        kind = "review"
        fields["review_status"] = review_status
    if kind != "issue":
        fields["ci"] = "green" if ci is None else ci
        fields["unresolved_threads"] = unresolved
    repo, _, num = ref.partition("#")
    return ItemSnapshot(
        ref=ref,
        kind=kind,
        repo=repo,
        number=int(num),
        url=item_url(repo, kind, int(num)),
        title="t",
        history=history,
        state=state,
        author="octocat",
        created_at="2026-09-01T00:00:00Z",
        last_activity=last_activity,
        labels=labels,
        linked_pr=linked_pr,
        **fields,
    )


def make_snapshot(
    *,
    kind: str = "pr",
    name: str = "test",
    items: list[ItemSnapshot] | None = None,
    scope: SnapshotScope | None = None,
    captured_at: str = "2026-09-30T22:00:00Z",
    has_more: bool = False,
) -> Snapshot:
    return Snapshot(
        kind=kind,
        name=name,
        captured_at=captured_at,
        scope=scope or SnapshotScope(),
        items=tuple(items or []),
        has_more=has_more,
    )
