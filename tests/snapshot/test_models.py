"""Model-level tests: scope hashing, snapshot (de)serialization."""

from src.snapshot.models import ItemSnapshot, Snapshot, SnapshotScope


def test_scope_hash_stable_across_equal_scopes():
    s1 = SnapshotScope(board="oh", repos=("a/b", "c/d"), states=("open",), limit=100)
    s2 = SnapshotScope(board="oh", repos=("a/b", "c/d"), states=("open",), limit=100)
    assert s1.hash_() == s2.hash_()


def test_scope_hash_sensitive_to_fields():
    base = SnapshotScope(board="oh", repos=("a/b",))
    assert base.hash_() != SnapshotScope(board="other", repos=("a/b",)).hash_()
    assert base.hash_() != SnapshotScope(board="oh", repos=("x/y",)).hash_()
    assert base.hash_() != SnapshotScope(board="oh", repos=("a/b",), limit=50).hash_()


def test_scope_roundtrip():
    s = SnapshotScope(
        board="oh",
        author="me",
        reviewer="octocat",
        repos=("a/b",),
        states=("open",),
        labels=("bug",),
        exclude_authors=("dependabot[bot]",),
        include_all=True,
        limit=42,
    )
    assert SnapshotScope.from_dict(s.to_dict()) == s


def test_snapshot_roundtrip_preserves_items_and_scope_hash():
    scope = SnapshotScope(board="oh", repos=("a/b",), states=("open",))
    items = [
        ItemSnapshot(
            key="a/b#1",
            repo="a/b",
            number=1,
            title="hi",
            history="oCr",
            state="open",
            author="octocat",
            last_activity="2026-09-30T22:00:00Z",
            labels=("bug",),
            ci_status="green",
            unresolved_thread_count=2,
        )
    ]
    snap = Snapshot.make(kind="pr", name="hourly", scope=scope, items=items)
    data = snap.to_dict()
    assert data["scope_hash"] == scope.hash_()

    restored = Snapshot.from_dict(data)
    assert restored.kind == snap.kind
    assert restored.name == snap.name
    assert restored.scope == scope
    assert restored.scope_hash == scope.hash_()
    assert restored.items == snap.items
