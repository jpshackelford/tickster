"""Model-level tests: scope hashing, snapshot (de)serialization."""

from src.snapshot.models import ItemSnapshot, Snapshot, SnapshotScope


def test_scope_hash_stable_across_equal_scopes():
    s1 = SnapshotScope(board="oh", repos=("a/b", "c/d"), states=("open",), limit=100)
    s2 = SnapshotScope(board="oh", repos=("a/b", "c/d"), states=("open",), limit=100)
    assert s1.fingerprint() == s2.fingerprint()


def test_scope_hash_sensitive_to_fields():
    base = SnapshotScope(board="oh", repos=("a/b",))
    assert base.fingerprint() != SnapshotScope(board="other", repos=("a/b",)).fingerprint()
    assert base.fingerprint() != SnapshotScope(board="oh", repos=("x/y",)).fingerprint()
    assert base.fingerprint() != SnapshotScope(board="oh", repos=("a/b",), limit=50).fingerprint()


def test_scope_from_pr_args_matches_direct_construction():
    direct = SnapshotScope(
        board="oh",
        author="me",
        reviewer="octocat",
        repos=("a/b",),
        states=("open",),
        limit=100,
    )
    via_factory = SnapshotScope.from_pr_args(
        board="oh",
        author="me",
        reviewer="octocat",
        repos=["a/b"],
        states=["open"],
        limit=100,
    )
    assert direct == via_factory


def test_scope_from_issue_args_includes_labels():
    scope = SnapshotScope.from_issue_args(
        board="oh",
        author="me",
        repos=["a/b"],
        states=["open"],
        labels=["bug"],
        limit=50,
    )
    assert scope.labels == ("bug",)
    assert scope.limit == 50


def test_scope_from_review_args_includes_exclude_and_include_all():
    scope = SnapshotScope.from_review_args(
        board="oh",
        author=None,
        reviewer="octocat",
        repos=["a/b"],
        states=["open"],
        exclude_authors=["dependabot[bot]"],
        include_all=True,
        limit=100,
    )
    assert scope.exclude_authors == ("dependabot[bot]",)
    assert scope.include_all is True


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
    assert data["scope_hash"] == scope.fingerprint()

    restored = Snapshot.from_dict(data)
    assert restored.kind == snap.kind
    assert restored.name == snap.name
    assert restored.scope == scope
    assert restored.scope_hash == scope.fingerprint()
    assert restored.items == snap.items


def test_from_dict_rejects_unknown_schema_version():
    import pytest

    data = Snapshot.make(kind="pr", name="x", scope=SnapshotScope(), items=[]).to_dict()
    data["schema"] = 999
    with pytest.raises(ValueError, match="unsupported snapshot schema version"):
        Snapshot.from_dict(data)
