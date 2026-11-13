"""Model-level tests: scope hashing, snapshot (de)serialization."""

import json
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
    snap = Snapshot.make(kind="pr", name="hourly", scope=scope, items=items, total_count=1)
    data = snap.to_dict()
    assert "scope_hash" not in data

    restored = Snapshot.from_dict(data, "pr")
    assert restored.kind == snap.kind
    assert restored.name == snap.name
    assert restored.captured_at == snap.captured_at
    assert restored.scope == scope
    assert restored.scope_hash == scope.fingerprint()
    assert restored.items == snap.items
    assert restored.total_count == 1
    assert restored.to_json() == snap.to_json()


def test_document_has_only_the_compact_keys_in_order():
    snap = Snapshot.make(kind="issue", name="", scope=SnapshotScope(limit=5), items=[])
    assert list(snap.to_dict()) == ["schema", "filters", "total_count", "has_more", "items"]
    assert snap.to_dict() == {
        "schema": 2,
        "filters": {"limit": 5},
        "total_count": None,
        "has_more": False,
        "items": [],
    }


def test_named_snapshot_gets_a_snapshot_key_after_schema():
    snap = Snapshot.make(kind="issue", name="nightly", scope=SnapshotScope(), items=[])
    data = snap.to_dict()
    assert list(data)[:2] == ["schema", "snapshot"]
    assert data["snapshot"] == {"name": "nightly", "captured_at": snap.captured_at}


def test_to_json_is_the_indented_document():
    snap = Snapshot.make(kind="pr", name="x", scope=SnapshotScope(), items=[])
    assert json.loads(snap.to_json()) == snap.to_dict()
    assert snap.to_json().startswith('{\n  "schema": 2,')


def test_from_dict_takes_the_name_from_the_caller_without_a_snapshot_key():
    data = Snapshot.make(kind="pr", name="", scope=SnapshotScope(), items=[]).to_dict()
    restored = Snapshot.from_dict(data, "pr", "fromfile")
    assert restored.name == "fromfile"
    assert restored.captured_at == ""


def test_from_dict_reads_total_count_and_has_more():
    snap = Snapshot.make(
        kind="pr", name="n", scope=SnapshotScope(), items=[], has_more=True, total_count=None
    )
    assert Snapshot.from_dict(snap.to_dict(), "pr").total_count is None
    data = {**snap.to_dict(), "total_count": 31}
    assert Snapshot.from_dict(data, "pr").total_count == 31


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("total_count", "3", "field 'total_count' has the wrong type"),
        ("has_more", None, "field 'has_more' has the wrong type"),
        ("kind", "pr", "unexpected field 'kind'"),
        ("scope_hash", "abc", "unexpected field 'scope_hash'"),
        ("snapshot", [], "field 'snapshot' has the wrong type"),
        ("filters", [], "field 'filters' has the wrong type"),
    ],
)
def test_from_dict_rejects_a_bad_top_level_key(key, value, message):
    data = Snapshot.make(kind="pr", name="x", scope=SnapshotScope(), items=[]).to_dict()
    data[key] = value
    with pytest.raises(ValueError, match=message):
        Snapshot.from_dict(data, "pr")


def test_from_dict_rejects_the_old_layout():
    old = {
        "schema": 2,
        "kind": "pr",
        "name": "x",
        "captured_at": "2026-09-01T00:00:00Z",
        "scope": SnapshotScope().to_dict(),
        "scope_hash": "abc",
        "has_more": False,
        "items": [],
    }
    with pytest.raises(ValueError, match="unexpected field"):
        Snapshot.from_dict(old, "pr")


def test_from_dict_rejects_a_row_of_another_kind():
    data = Snapshot.make(kind="pr", name="x", scope=SnapshotScope(), items=[]).to_dict()
    data["items"] = [
        ItemSnapshot(
            ref="a/b#1", kind="issue", repo="a/b", number=1, url="u", title="t", history="O",
            state="open", author="a", created_at="2026-09-01T00:00:00Z",
            last_activity="2026-09-01T00:00:00Z",
        ).to_dict()
    ]  # fmt: skip
    with pytest.raises(ValueError, match="a issue row in a pr snapshot"):
        Snapshot.from_dict(data, "pr")


def test_from_dict_rejects_another_schema_version():
    data = Snapshot.make(kind="pr", name="x", scope=SnapshotScope(), items=[]).to_dict()
    data["schema"] = 1
    with pytest.raises(ValueError, match="schema 1, this tkt writes schema 2"):
        Snapshot.from_dict(data, "pr")


def test_scope_to_dict_omits_unset_keys_but_keeps_limit():
    assert SnapshotScope().to_dict() == {"limit": 100}


def test_scope_to_dict_keeps_set_keys():
    scope = SnapshotScope(
        author="octocat",
        repos=("a/b",),
        states=("open",),
        pr_filter="no-pr",
        all_authors=True,
        window=WindowScope(field="created", since_days=14),
    )
    assert scope.to_dict() == {
        "author": "octocat",
        "all_authors": True,
        "repos": ["a/b"],
        "states": ["open"],
        "pr_filter": "no-pr",
        "limit": 100,
        "window": {"field": "created", "since_days": 14},
    }


def test_scope_from_dict_reads_a_missing_key_as_unset():
    scope = SnapshotScope.from_dict({"limit": 7})
    assert scope == SnapshotScope(limit=7)


def test_scope_from_dict_requires_the_limit():
    with pytest.raises(ValueError, match="missing field 'limit'"):
        SnapshotScope.from_dict({"author": "me"})


def test_scope_from_dict_rejects_an_unknown_key():
    with pytest.raises(ValueError, match="unexpected field 'nope'"):
        SnapshotScope.from_dict({"limit": 1, "nope": 1})


def test_scope_from_dict_rejects_a_wrong_type():
    data = SnapshotScope().to_dict()
    data["limit"] = "100"
    with pytest.raises(ValueError, match="field 'limit' has the wrong type"):
        SnapshotScope.from_dict(data)


def test_window_scope_to_dict_omits_unset_keys():
    window = WindowScope(field="merged", since_days=14)
    assert window.to_dict() == {"field": "merged", "since_days": 14}
    assert WindowScope(field="merged", since_days=0).to_dict() == {
        "field": "merged",
        "since_days": 0,
    }
    assert WindowScope.from_dict(window.to_dict()) == window
    with pytest.raises(ValueError, match="missing field 'field'"):
        WindowScope.from_dict({"since_days": 14})
    with pytest.raises(ValueError, match="unexpected field 'x'"):
        WindowScope.from_dict({"field": "merged", "x": 1})


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
    assert scope.to_dict() == {"field": "updated", "after": "2026-08-01", "before": "2026-08-31"}


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
