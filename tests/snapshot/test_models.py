"""Model-level tests: scope hashing, snapshot (de)serialization."""

from datetime import UTC, datetime

import pytest

from src.date_window import build_date_window, field_flag_names
from src.snapshot.models import ItemSnapshot, Snapshot, SnapshotScope, WindowScope


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
        refs=None,
        states=["open"],
        limit=100,
    )
    assert direct == via_factory


def test_scope_from_issue_args_includes_labels():
    scope = SnapshotScope.from_issue_args(
        board="oh",
        author="me",
        repos=["a/b"],
        refs=None,
        states=["open"],
        labels=["bug"],
        limit=50,
    )
    assert scope.labels == ("bug",)
    assert scope.limit == 50


def _pr_scope(refs: list[str] | None) -> SnapshotScope:
    return SnapshotScope.from_pr_args(
        board=None, author=None, reviewer=None, repos=None, refs=refs, states=None, limit=100
    )


def _issue_scope(refs: list[str] | None) -> SnapshotScope:
    return SnapshotScope.from_issue_args(
        board=None, author=None, repos=None, refs=refs, states=None, labels=None, limit=100
    )


def test_scope_fingerprint_distinguishes_explicit_refs():
    for make in (_pr_scope, _issue_scope):
        a = make(["o/r#1", "o/r#2"])
        assert a.fingerprint() != make(["o/r#7"]).fingerprint()
        assert a.fingerprint() != make(None).fingerprint()


def test_scope_fingerprint_ignores_ref_order():
    for make in (_pr_scope, _issue_scope):
        assert make(["o/r#2", "o/r#1"]) == make(["o/r#1", "o/r#2"])
        assert make(["o/r#2", "o/r#1"]).fingerprint() == make(["o/r#1", "o/r#2"]).fingerprint()


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
        refs=("a/b#1", "a/b#2"),
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
            ref="a/b#1",
            kind="pr",
            repo="a/b",
            number=1,
            url="https://github.com/a/b/pull/1",
            title="hi",
            history="oCr",
            state="open",
            author="octocat",
            created_at="2026-09-01T00:00:00Z",
            last_activity="2026-09-30T22:00:00Z",
            labels=("bug",),
            ci="green",
            unresolved_threads=2,
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


def test_from_dict_rejects_another_schema_version():
    data = Snapshot.make(kind="pr", name="x", scope=SnapshotScope(), items=[]).to_dict()
    data["schema"] = 1
    with pytest.raises(ValueError, match="schema 1, this tkt writes schema 2"):
        Snapshot.from_dict(data)


def test_scope_to_dict_always_has_every_key():
    assert set(SnapshotScope().to_dict()) == {
        "board",
        "author",
        "all_authors",
        "reviewer",
        "repos",
        "refs",
        "states",
        "labels",
        "not_labels",
        "exclude_authors",
        "include_all",
        "pr_filter",
        "blocked_filter",
        "sort",
        "limit",
        "window",
    }
    assert SnapshotScope().to_dict()["window"] is None


def test_scope_from_dict_requires_every_key():
    data = SnapshotScope().to_dict()
    del data["not_labels"]
    with pytest.raises(ValueError, match="missing field 'not_labels'"):
        SnapshotScope.from_dict(data)


def test_scope_from_dict_rejects_a_wrong_type():
    data = SnapshotScope().to_dict()
    data["limit"] = "100"
    with pytest.raises(ValueError, match="field 'limit' has the wrong type"):
        SnapshotScope.from_dict(data)


def test_window_scope_to_dict_has_every_key_and_requires_them():
    window = WindowScope(field="merged", since_days=14)
    assert window.to_dict() == {
        "field": "merged",
        "since_days": 14,
        "after": None,
        "before": None,
    }
    assert WindowScope.from_dict(window.to_dict()) == window
    with pytest.raises(ValueError, match="missing field 'before'"):
        WindowScope.from_dict({"field": "merged", "since_days": 14, "after": None})


def test_scope_without_window_roundtrips_as_none():
    data = SnapshotScope(board="oh").to_dict()
    assert SnapshotScope.from_dict(data).window is None


def test_window_changes_the_fingerprint():
    base = SnapshotScope(board="oh")
    rolling = SnapshotScope(board="oh", window=WindowScope(field="merged", since_days=14))
    other_days = SnapshotScope(board="oh", window=WindowScope(field="merged", since_days=7))
    other_field = SnapshotScope(board="oh", window=WindowScope(field="created", since_days=14))
    fingerprints = {s.fingerprint() for s in (base, rolling, other_days, other_field)}
    assert len(fingerprints) == 4


def test_rolling_window_fingerprint_does_not_depend_on_todays_date():
    def scope_on(day: datetime) -> SnapshotScope:
        window = build_date_window(
            ["merged"],
            date_field="merged",
            flag_names=field_flag_names("merged"),
            since_days=14,
            now=day,
        )
        return SnapshotScope.from_pr_args(
            board="oh", author=None, reviewer=None, repos=None, refs=None,
            states=["merged"], limit=100, window=window,
        )  # fmt: skip

    monday = datetime(2026, 9, 7, tzinfo=UTC)
    tuesday = datetime(2026, 9, 8, tzinfo=UTC)
    assert scope_on(monday).fingerprint() == scope_on(tuesday).fingerprint()


def test_absolute_window_is_stored_as_dates():
    window = build_date_window(
        ["open"],
        date_field="updated",
        flag_names=field_flag_names("updated"),
        after="2026-08-01",
        before="2026-08-31",
    )
    scope = WindowScope.from_window(window)
    assert scope is not None
    assert scope == WindowScope(field="updated", after="2026-08-01", before="2026-08-31")
    assert scope.to_dict() == {
        "field": "updated",
        "since_days": None,
        "after": "2026-08-01",
        "before": "2026-08-31",
    }


def test_scope_with_window_roundtrips():
    for window in (
        WindowScope(field="merged", since_days=0),
        WindowScope(field="closed", before="2026-08-31"),
        WindowScope(field="updated", after="2026-08-01", before="2026-08-31"),
    ):
        scope = SnapshotScope(board="oh", window=window)
        restored = SnapshotScope.from_dict(scope.to_dict())
        assert restored == scope
        assert restored.fingerprint() == scope.fingerprint()


@pytest.mark.parametrize("kind", ["pr", "issue", "review"])
def test_factories_record_the_window(kind):
    window = build_date_window(
        ["open"], date_field="updated", flag_names=field_flag_names("updated"), since_days=7
    )
    common = {"board": None, "author": None, "repos": None, "states": ["open"], "limit": 100}
    if kind == "pr":
        scope = SnapshotScope.from_pr_args(reviewer=None, refs=None, window=window, **common)
    elif kind == "issue":
        scope = SnapshotScope.from_issue_args(refs=None, labels=None, window=window, **common)
    else:
        scope = SnapshotScope.from_review_args(
            reviewer=None, exclude_authors=None, include_all=False, window=window, **common
        )
    assert scope.window == WindowScope(field="updated", since_days=7)


def test_describe_window_scope():
    assert WindowScope(field="merged", since_days=14).describe() == "merged since 14d ago"
    assert WindowScope(field="merged", after="2026-08-01").describe() == "merged ≥ 2026-08-01"
    assert WindowScope(field="merged", before="2026-08-01").describe() == "merged ≤ 2026-08-01"
    both = WindowScope(field="merged", after="2026-08-01", before="2026-08-31")
    assert both.describe() == "merged 2026-08-01..2026-08-31"
