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


@pytest.fixture
def tkt_home(tmp_path: Path, monkeypatch) -> Path:
    """Point TKT_HOME at a tmp dir so snapshot store writes don't escape."""
    monkeypatch.setattr(board_config, "TKT_HOME", tmp_path)
    monkeypatch.setattr(board_config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(board_config, "CACHE_FILE", tmp_path / "board-cache.db")
    return tmp_path


def make_item(
    *,
    key: str = "owner/repo#1",
    history: str = "oC",
    state: str = "open",
    ci_status: str | None = "green",
    labels: tuple[str, ...] = (),
    unresolved: int = 0,
    last_activity: str = "2026-09-30T22:00:00Z",
    linked_pr: str | None = None,
    review_status: str | None = None,
) -> ItemSnapshot:
    """Convenience constructor for ItemSnapshot in tests."""
    repo, _, num = key.partition("#")
    return ItemSnapshot(
        key=key,
        repo=repo,
        number=int(num),
        title="t",
        history=history,
        state=state,
        author="octocat",
        last_activity=last_activity,
        labels=labels,
        ci_status=ci_status,
        unresolved_thread_count=unresolved,
        linked_pr=linked_pr,
        review_status=review_status,
    )


def make_snapshot(
    *,
    kind: str = "pr",
    name: str = "test",
    items: list[ItemSnapshot] | None = None,
    scope: SnapshotScope | None = None,
    captured_at: str = "2026-09-30T22:00:00Z",
) -> Snapshot:
    return Snapshot(
        kind=kind,
        name=name,
        captured_at=captured_at,
        scope=scope or SnapshotScope(),
        items=tuple(items or []),
    )
