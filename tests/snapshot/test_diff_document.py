"""The diff document speaks the list document's vocabulary: `ref`, row `kind`, `change`."""

from __future__ import annotations

import pytest

from src.snapshot.diff import diff_snapshots
from src.snapshot.models import SCHEMA_VERSION, ChangeKind, ItemDelta
from src.snapshot.rows import ROW_FIELDS

from .conftest import make_item, make_snapshot

KINDS = ("issue", "pr", "review")
DELTA_KEYS = [
    "ref",
    "kind",
    "change",
    "new_history_tail",
    "changed_fields",
    "disappearance_reason",
    "prev",
    "curr",
]


def _item(kind: str, number: int, **fields):
    if kind == "review":
        fields["review_status"] = "review"
        fields.setdefault("wait_seconds", 60.0)
        return make_item(ref=f"o/r#{number}", **fields)
    return make_item(ref=f"o/r#{number}", kind=kind, **fields)


def _document(kind: str) -> dict:
    prev = make_snapshot(
        kind=kind,
        items=[
            _item(kind, 1),
            _item(kind, 2, history="oC"),
            _item(kind, 3),
        ],
    )
    curr = make_snapshot(
        kind=kind,
        items=[
            _item(kind, 1),
            _item(kind, 2, history="oCr", last_activity="2026-10-01T00:00:00Z"),
            _item(kind, 4),
        ],
    )
    return diff_snapshots(prev, curr).to_dict()


def _by_change(document: dict) -> dict[str, dict]:
    return {d["change"]: d for d in document["deltas"]}


@pytest.mark.parametrize("kind", KINDS)
def test_every_delta_has_exactly_the_documented_keys(kind):
    document = _document(kind)
    assert set(_by_change(document)) == {"added", "changed", "removed", "unchanged"}
    for delta in document["deltas"]:
        assert list(delta) == DELTA_KEYS
        assert "key" not in delta


@pytest.mark.parametrize("kind", KINDS)
def test_ref_and_row_kind_are_set_for_all_four_changes(kind):
    by_change = _by_change(_document(kind))
    assert {c: d["ref"] for c, d in by_change.items()} == {
        "added": "o/r#4",
        "changed": "o/r#2",
        "removed": "o/r#3",
        "unchanged": "o/r#1",
    }
    assert {d["kind"] for d in by_change.values()} == {kind}


@pytest.mark.parametrize("kind", KINDS)
def test_unchanged_delta_has_no_bodies_but_still_has_a_row_kind(kind):
    unchanged = _by_change(_document(kind))["unchanged"]
    assert unchanged["prev"] is None and unchanged["curr"] is None
    assert unchanged["kind"] == kind


@pytest.mark.parametrize("kind", KINDS)
def test_bodies_have_the_keys_of_a_list_row_of_that_kind(kind):
    by_change = _by_change(_document(kind))
    fields = list(ROW_FIELDS[kind])
    assert by_change["added"]["prev"] is None
    assert list(by_change["added"]["curr"]) == fields
    assert list(by_change["removed"]["prev"]) == fields
    assert by_change["removed"]["curr"] is None
    assert list(by_change["changed"]["prev"]) == fields
    assert list(by_change["changed"]["curr"]) == fields


@pytest.mark.parametrize("kind", KINDS)
def test_changed_fields_name_row_fields_only(kind):
    changed = _by_change(_document(kind))["changed"]["changed_fields"]
    assert changed == ["history", "last_activity"]
    assert set(changed) <= set(ROW_FIELDS[kind])


def test_history_rewritten_is_the_one_marker_that_is_not_a_row_field():
    prev = make_snapshot(items=[make_item(history="oCr")])
    curr = make_snapshot(items=[make_item(history="oCf")])
    [delta] = diff_snapshots(prev, curr).to_dict()["deltas"]
    assert delta["changed_fields"] == ["history", "history-rewritten"]
    assert set(delta["changed_fields"]) - set(ROW_FIELDS["pr"]) == {"history-rewritten"}


def test_a_delta_kind_is_the_row_kind_never_the_change_type():
    document = _document("pr")
    change_types = {c.value for c in ChangeKind}
    assert {d["kind"] for d in document["deltas"]}.isdisjoint(change_types)
    assert {d["change"] for d in document["deltas"]} == change_types


def test_item_delta_kind_comes_from_whichever_row_is_present():
    row = make_item(kind="issue")
    added = ItemDelta(ref=row.ref, change=ChangeKind.ADDED, prev=None, curr=row)
    removed = ItemDelta(ref=row.ref, change=ChangeKind.REMOVED, prev=row, curr=None)
    assert (added.kind, removed.kind) == ("issue", "issue")


def test_the_top_level_matches_the_list_document():
    prev = make_snapshot(items=[make_item()])
    curr = make_snapshot(items=[make_item(), make_item(ref="o/r#2")])
    document = diff_snapshots(prev, curr).to_dict()
    assert list(document) == [
        "schema",
        "prev",
        "curr",
        "baseline",
        "scope_matches",
        "counts",
        "deltas",
    ]
    assert document["schema"] == SCHEMA_VERSION == 2
    for side, snap in (("prev", prev), ("curr", curr)):
        assert document[side] == {
            "name": snap.name,
            "captured_at": snap.captured_at,
            "scope_hash": snap.scope_hash,
        }
