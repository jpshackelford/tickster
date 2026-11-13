"""On-disk snapshot store tests."""

from __future__ import annotations

import json

import pytest

from src.snapshot import store
from src.snapshot.models import Snapshot

from .conftest import make_item, make_snapshot


def test_save_and_load_roundtrip(tkt_home):  # noqa: ARG001
    snap = make_snapshot(name="hourly", items=[make_item(ref="a/b#1")])
    path = store.save(snap)
    assert path.exists()
    assert path.name == "pr-hourly.json"

    loaded = store.load("pr", "hourly")
    assert loaded.name == "hourly"
    assert loaded.kind == "pr"
    assert len(loaded.items) == 1
    assert loaded.items[0].ref == "a/b#1"


def test_save_overwrites_named_snapshot(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="hourly", items=[make_item(ref="a/b#1")]))
    store.save(
        make_snapshot(
            name="hourly",
            items=[make_item(ref="a/b#1"), make_item(ref="a/b#2")],
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
    store.save(make_snapshot(kind="issue", name="hourly", items=[make_item(kind="issue")]))

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
    return make_snapshot(name="x", items=[make_item(ref="a/b#1")]).to_dict()


def _notices(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def _schema_1_dict() -> dict:
    data = _good_dict()
    data["schema"] = 1
    return data


def _without(data: dict, key: str) -> dict:
    del data[key]
    return data


def _row_without(key: str) -> dict:
    data = _good_dict()
    del data["items"][0][key]
    return data


def _row_with(key: str, value) -> dict:
    data = _good_dict()
    data["items"][0][key] = value
    return data


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (json.dumps(_schema_1_dict()), "schema 1, this tkt writes schema 2"),
        ('{"schema": 2, "kind": "pr", "items": [', "invalid JSON at line 1 column 39"),
        ("", "invalid JSON at line 1 column 1"),
        ("[]", "the top level is not a JSON object"),
        (json.dumps(_without(_good_dict(), "items")), "missing field 'items'"),
        (json.dumps(_row_without("head")), "missing field 'head'"),
        (json.dumps(_row_with("events", [])), "unexpected field 'events'"),
        (json.dumps(_row_with("number", "1")), "field 'number' has the wrong type"),
        (json.dumps(_row_with("draft", 0)), "field 'draft' has the wrong type"),
    ],
)
def test_load_discards_an_unreadable_file_with_one_notice(tkt_home, caplog, text, reason):  # noqa: ARG001
    path = _write("pr-x.json", text)

    with pytest.raises(FileNotFoundError, match=r"snapshot not found: pr/x"):
        store.load("pr", "x")

    assert not path.exists()
    assert _notices(caplog) == [f"tkt: discarded snapshot pr/x: {reason}"]

    caplog.clear()
    with pytest.raises(FileNotFoundError):
        store.load("pr", "x")
    assert _notices(caplog) == []


def test_load_pending_discards_an_unreadable_file_and_says_pending_baseline(tkt_home, caplog):  # noqa: ARG001
    path = store.pending_path_for("pr", "x")
    path.parent.mkdir()
    path.write_text(json.dumps(_schema_1_dict()))

    with pytest.raises(FileNotFoundError, match="pending baseline not found: pr/x"):
        store.load_pending("pr", "x")

    assert not path.exists()
    assert _notices(caplog) == [
        "tkt: discarded pending baseline pr/x: schema 1, this tkt writes schema 2"
    ]


def test_load_reads_a_row_of_another_kind_as_unreadable(tkt_home, caplog):  # noqa: ARG001
    data = make_snapshot(kind="issue", name="x", items=[make_item(ref="a/b#1")]).to_dict()
    _write("issue-x.json", json.dumps(data))

    with pytest.raises(FileNotFoundError):
        store.load("issue", "x")

    assert _notices(caplog) == ["tkt: discarded snapshot issue/x: a pr row in a issue snapshot"]


def test_list_discards_a_schema_1_file_and_skips_a_foreign_file(tkt_home, caplog):  # noqa: ARG001
    store.save(make_snapshot(name="good", items=[make_item()]))
    old = _write("issue-old.json", json.dumps(_schema_1_dict()))
    foreign = _write("notes.json", json.dumps({"kind": "pr", "hello": "world"}))
    _write("pr-trunc.json", '{"kind": "pr", "items": [')

    records = store.list_()

    assert [r.name for r in records] == ["good"]
    assert not old.exists()
    assert foreign.exists()
    assert sorted(_notices(caplog)) == [
        "tkt: discarded snapshot issue/old: schema 1, this tkt writes schema 2",
        "tkt: discarded snapshot pr/trunc: invalid JSON at line 1 column 26",
    ]
    assert store.list_() == records


def test_list_reads_the_item_count_of_each_snapshot(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="two", items=[make_item(ref="a/b#1"), make_item(ref="a/b#2")]))

    [record] = store.list_()

    assert (record.kind, record.name, record.item_count) == ("pr", "two", 2)


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
    path = store.save_pending(make_snapshot(name="poll", items=[make_item(ref="a/b#1")]))
    assert path == store.snapshots_dir() / "pending" / "pr-poll.json"
    assert not store.exists("pr", "poll")
    assert store.list_() == []
    assert store.load_pending("pr", "poll").items[0].ref == "a/b#1"


def test_ack_replaces_baseline_and_deletes_pending(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll", items=[make_item(ref="a/b#1")]))
    store.save_pending(make_snapshot(name="poll", items=[make_item(ref="a/b#2")]))

    assert store.ack("pr", "poll") is True

    assert [it.ref for it in store.load("pr", "poll").items] == ["a/b#2"]
    assert not store.has_pending("pr", "poll")


def test_ack_without_pending_changes_nothing(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll", items=[make_item(ref="a/b#1")]))
    before = store.path_for("pr", "poll").read_bytes()

    assert store.ack("pr", "poll") is False

    assert store.path_for("pr", "poll").read_bytes() == before


def test_ack_of_a_corrupt_pending_file_keeps_the_baseline(tkt_home):  # noqa: ARG001
    store.save(make_snapshot(name="poll", items=[make_item(ref="a/b#1")]))
    store.pending_path_for("pr", "poll").parent.mkdir()
    store.pending_path_for("pr", "poll").write_text("{")

    with pytest.raises(FileNotFoundError, match="pending baseline not found: pr/poll"):
        store.ack("pr", "poll")

    assert not store.has_pending("pr", "poll")

    assert [it.ref for it in store.load("pr", "poll").items] == ["a/b#1"]


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
    store.save(make_snapshot(name="x", items=[make_item(ref="a/b#1")]))
    store.save(make_snapshot(name="x.pending", items=[make_item(ref="a/b#2")]))
    store.save_pending(make_snapshot(name="x", items=[make_item(ref="a/b#3")]))

    assert [it.ref for it in store.load("pr", "x.pending").items] == ["a/b#2"]
    assert [it.ref for it in store.load("pr", "x").items] == ["a/b#1"]
    assert [it.ref for it in store.load_pending("pr", "x").items] == ["a/b#3"]
    pending = {r.name: r.pending for r in store.list_()}
    assert pending == {"x": True, "x.pending": False}


def test_a_document_without_a_snapshot_key_takes_its_name_from_the_file(tkt_home):  # noqa: ARG001
    path = store.save(make_snapshot(name="hourly", items=[make_item(ref="a/b#1")]))
    doc = json.loads(path.read_text())
    del doc["snapshot"]
    path.write_text(json.dumps(doc))
    loaded = store.load("pr", "hourly")
    assert loaded.name == "hourly"
    assert loaded.items[0].ref == "a/b#1"
    assert [r.name for r in store.list_("pr")] == ["hourly"]


def test_a_file_with_the_old_top_level_keys_is_discarded(tkt_home, caplog):  # noqa: ARG001
    path = store.save(make_snapshot(name="hourly", items=[make_item(ref="a/b#1")]))
    doc = json.loads(path.read_text())
    path.write_text(json.dumps({**doc, "kind": "pr", "scope_hash": "abc"}))
    with pytest.raises(FileNotFoundError):
        store.load("pr", "hourly")
    assert not path.exists()
    assert "unexpected field" in caplog.text
