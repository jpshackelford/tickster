"""On-disk snapshot store tests."""

from __future__ import annotations

import json

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


def _write(name: str, text: str):
    path = store.snapshots_dir() / name
    path.write_text(text)
    return path


def _good_dict() -> dict:
    return make_snapshot(name="x", items=[make_item(key="a/b#1")]).to_dict()


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('{"schema": 1, "kind": "pr", "items": [', "invalid JSON at line 1"),
        ("", "invalid JSON at line 1"),
        ("[]", "the top level is not a JSON object"),
    ],
)
def test_load_names_the_snapshot_and_file_when_the_json_is_unusable(
    tkt_home,  # noqa: ARG001
    text,
    reason,
):  # noqa: ARG001
    path = _write("pr-x.json", text)
    with pytest.raises(store.SnapshotFormatError) as exc:
        store.load("pr", "x")
    message = str(exc.value)
    assert message.startswith("snapshot pr/x cannot be read (")
    assert str(path) in message
    assert reason in message
    assert message.endswith("Delete it with: tkt snapshot rm pr/x")


def test_load_reports_the_missing_top_level_field(tkt_home):  # noqa: ARG001
    data = _good_dict()
    del data["items"]
    _write("pr-x.json", json.dumps(data))
    with pytest.raises(store.SnapshotFormatError, match="missing the required field 'items'"):
        store.load("pr", "x")


def test_load_reports_the_missing_field_of_a_row(tkt_home):  # noqa: ARG001
    data = _good_dict()
    data["items"][0] = {"key": "a/b#1"}
    _write("pr-x.json", json.dumps(data))
    with pytest.raises(store.SnapshotFormatError, match="missing the required field 'repo'"):
        store.load("pr", "x")


def test_load_reports_an_unsupported_schema_version_with_the_file(tkt_home):  # noqa: ARG001
    data = _good_dict()
    data["schema"] = 99
    _write("pr-x.json", json.dumps(data))
    with pytest.raises(store.SnapshotFormatError, match="unsupported snapshot schema version: 99"):
        store.load("pr", "x")


def test_load_accepts_a_minimal_older_snapshot(tkt_home):  # noqa: ARG001
    older = {
        "schema": 1,
        "kind": "pr",
        "name": "x",
        "captured_at": "2026-01-01T00:00:00Z",
        "scope": {"limit": 100},
        "items": [{"key": "a/b#1", "repo": "a/b", "number": 1}],
    }
    _write("pr-x.json", json.dumps(older))
    assert [it.key for it in store.load("pr", "x").items] == ["a/b#1"]


def test_list_skips_unreadable_files_with_one_warning_each(
    tkt_home,  # noqa: ARG001
    caplog,
):
    store.save(make_snapshot(name="good", items=[make_item()]))
    _write("pr-trunc.json", '{"kind": "pr", "items": [')
    _write("pr-array.json", "[]")
    _write("pr-badtype.json", json.dumps({"kind": "pr", "name": "badtype", "items": None}))

    records = store.list_()

    assert sorted(r.name for r in records) == ["badtype", "good"]
    assert next(r for r in records if r.name == "badtype").item_count == 0
    warnings = sorted(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert len(warnings) == 2
    assert "pr-array.json" in warnings[0] and "not a JSON object" in warnings[0]
    assert "pr-trunc.json" in warnings[1]


def test_save_says_when_the_name_is_stored_under_another_name(tkt_home, caplog):  # noqa: ARG001
    path = store.save(make_snapshot(name="a/b c"))
    assert path.name == "pr-a-b-c.json"
    assert [r.getMessage() for r in caplog.records] == [
        "tkt: snapshot name 'a/b c' is stored as 'a-b-c'"
    ]


@pytest.mark.parametrize("name", ["hourly", "ts-20260101T000000Z", "v1.2_x"])
def test_save_is_silent_when_the_name_is_kept(tkt_home, caplog, name):  # noqa: ARG001
    store.save(make_snapshot(name=name))
    assert caplog.records == []


def test_pending_lives_in_its_own_directory(tkt_home):  # noqa: ARG001
    path = store.save_pending(make_snapshot(name="poll", items=[make_item(key="a/b#1")]))
    assert path == store.snapshots_dir() / "pending" / "pr-poll.json"
    assert not store.exists("pr", "poll")
    assert store.list_() == []
    assert store.load_pending("pr", "poll").items[0].key == "a/b#1"


def test_ack_replaces_baseline_and_deletes_pending(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll", items=[make_item(key="a/b#1")]))
    store.save_pending(make_snapshot(name="poll", items=[make_item(key="a/b#2")]))

    assert store.ack("pr", "poll") is True

    assert [it.key for it in store.load("pr", "poll").items] == ["a/b#2"]
    assert not store.has_pending("pr", "poll")


def test_ack_without_pending_changes_nothing(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll", items=[make_item(key="a/b#1")]))
    before = store.path_for("pr", "poll").read_bytes()

    assert store.ack("pr", "poll") is False

    assert store.path_for("pr", "poll").read_bytes() == before


def test_ack_of_a_corrupt_pending_file_keeps_the_baseline(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll", items=[make_item(key="a/b#1")]))
    store.pending_path_for("pr", "poll").parent.mkdir()
    store.pending_path_for("pr", "poll").write_text("{")

    with pytest.raises(store.SnapshotFormatError, match="pending baseline pr/poll"):
        store.ack("pr", "poll")

    assert [it.key for it in store.load("pr", "poll").items] == ["a/b#1"]


def test_delete_removes_the_pending_baseline_too(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll"))
    store.save_pending(make_snapshot(name="poll"))

    assert store.delete("pr", "poll") is True

    assert not store.exists("pr", "poll")
    assert not store.has_pending("pr", "poll")


def test_delete_of_a_pending_only_name_reports_removed(tkt_home):  # noqa: ARG001
    store.save_pending(make_snapshot(name="poll"))
    assert store.delete("pr", "poll") is True
    assert store.delete("pr", "poll") is False


def test_list_marks_only_snapshots_with_a_pending_baseline(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll"))
    store.save(make_snapshot(name="other"))
    store.save_pending(make_snapshot(name="poll"))

    assert {r.name: r.pending for r in store.list_()} == {"poll": True, "other": False}


def test_a_snapshot_named_x_pending_does_not_collide_with_the_pending_file_of_x(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="x", items=[make_item(key="a/b#1")]))
    store.save(make_snapshot(name="x.pending", items=[make_item(key="a/b#2")]))
    store.save_pending(make_snapshot(name="x", items=[make_item(key="a/b#3")]))

    assert [it.key for it in store.load("pr", "x.pending").items] == ["a/b#2"]
    assert [it.key for it in store.load("pr", "x").items] == ["a/b#1"]
    assert [it.key for it in store.load_pending("pr", "x").items] == ["a/b#3"]
    pending = {r.name: r.pending for r in store.list_()}
    assert pending == {"x": True, "x.pending": False}
