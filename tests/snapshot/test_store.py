"""On-disk snapshot store tests."""

from __future__ import annotations

import pytest

from src.snapshot import store
from src.snapshot.models import Snapshot

from .conftest import make_item, make_snapshot


def test_save_and_load_roundtrip(tkt_home):  # noqa: ARG001
    snap = make_snapshot(name="hourly", items=[make_item(key="a/b#1")])
    path = store.save(snap)
    assert path.exists()
    assert path.name == "pr-hourly.json"

    loaded = store.load("pr", "hourly")
    assert loaded.name == "hourly"
    assert loaded.kind == "pr"
    assert len(loaded.items) == 1
    assert loaded.items[0].key == "a/b#1"


def test_save_overwrites_named_snapshot(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="hourly", items=[make_item(key="a/b#1")]))
    store.save(
        make_snapshot(
            name="hourly",
            items=[make_item(key="a/b#1"), make_item(key="a/b#2")],
        )
    )
    assert len(store.load("pr", "hourly").items) == 2


def test_load_missing_raises(tkt_home):  # noqa: ARG001
    with pytest.raises(FileNotFoundError):
        store.load("pr", "nope")


def test_delete(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="hourly", items=[make_item()]))
    assert store.exists("pr", "hourly")
    assert store.delete("pr", "hourly") is True
    assert not store.exists("pr", "hourly")
    assert store.delete("pr", "hourly") is False


def test_list_filters_by_kind(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(kind="pr", name="hourly", items=[make_item()]))
    store.save(make_snapshot(kind="issue", name="hourly", items=[make_item()]))

    all_recs = store.list_()
    assert {(r.kind, r.name) for r in all_recs} == {
        ("pr", "hourly"),
        ("issue", "hourly"),
    }

    pr_only = store.list_(kind="pr")
    assert [(r.kind, r.name) for r in pr_only] == [("pr", "hourly")]


def test_slugify_rejects_empty(tkt_home):  # noqa: ARG001
    with pytest.raises(ValueError):
        store.slugify("///")


def test_slugify_normalizes_unsafe_chars(tkt_home):  # noqa: ARG001
    assert store.slugify("a/b/c d") == "a-b-c-d"
    assert store.slugify("my snapshot!") == "my-snapshot"


def test_rejects_invalid_kind(tkt_home):  # noqa: ARG001
    with pytest.raises(ValueError):
        store.save(
            Snapshot(
                kind="bogus",  # type: ignore[arg-type]
                name="x",
                captured_at="2026-01-01T00:00:00Z",
                scope=make_snapshot().scope,
                items=(),
            )
        )
