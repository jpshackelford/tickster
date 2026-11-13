"""PR head SHA, review decision and merge state in snapshots and diffs."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.pr.cli import list_cmd as pr_list
from src.pr.github_api import PR_FIELDS_FRAGMENT
from src.pr.history import process_pr_data
from src.pr.models import CIStatus, PRInfo, PRListResult, PRState
from src.snapshot import store
from src.snapshot.convert import item_from_pr
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import ChangeKind, ItemSnapshot
from src.snapshot.render import render_diff

from .conftest import make_item, make_snapshot

SHA_A = "a" * 40
SHA_B = "b" * 40
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _item(**overrides: Any) -> ItemSnapshot:
    fields: dict[str, Any] = {
        "head_sha": SHA_A,
        "review_decision": "APPROVED",
        "merge_state": "CLEAN",
        "mergeable": "MERGEABLE",
    }
    fields.update(overrides)
    return replace(make_item(key="o/r#1"), **fields)


def _changed_fields(prev: ItemSnapshot, curr: ItemSnapshot) -> tuple[str, ...]:
    [delta] = diff_snapshots(make_snapshot(items=[prev]), make_snapshot(items=[curr])).deltas
    return delta.changed_fields


def _pr(**overrides: Any) -> PRInfo:
    fields: dict[str, Any] = {
        "repo": "o/r",
        "number": 1,
        "title": "t",
        "state": PRState.OPEN,
        "ci_status": CIStatus.GREEN,
        "history": "oA",
        "created_at": NOW,
        "closed_at": None,
        "last_activity": NOW,
        "author": "octocat",
        "head_sha": SHA_A,
        "review_decision": "APPROVED",
        "merge_state": "CLEAN",
        "mergeable": "MERGEABLE",
    }
    fields.update(overrides)
    return PRInfo(**fields)


def _pr_data(**overrides: Any) -> dict:
    data = {
        "repository": {"nameWithOwner": "o/r"},
        "number": 1,
        "title": "t",
        "author": {"login": "octocat"},
        "createdAt": "2026-10-01T12:00:00Z",
        "closedAt": None,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "BEHIND",
        "reviewDecision": "CHANGES_REQUESTED",
        "headRefOid": SHA_A,
        "reviewThreads": {"nodes": []},
        "reviewRequests": {"nodes": []},
        "latestReviews": {"nodes": []},
        "commits": {"nodes": []},
        "timelineItems": {"nodes": []},
    }
    data.update(overrides)
    return data


class TestCapture:
    def test_fragment_requests_the_fields(self):
        for name in ("headRefOid", "reviewDecision", "mergeStateStatus", "mergeable"):
            assert name in PR_FIELDS_FRAGMENT

    def test_process_pr_data_reads_the_fields(self):
        info = process_pr_data(_pr_data(), "octocat")
        assert info.head_sha == SHA_A
        assert info.review_decision == "CHANGES_REQUESTED"
        assert info.merge_state == "BEHIND"
        assert info.mergeable == "MERGEABLE"

    def test_null_review_decision_is_none(self):
        assert process_pr_data(_pr_data(reviewDecision=None), "octocat").review_decision is None

    def test_snapshot_item_stores_the_four_fields(self):
        item = item_from_pr(_pr())
        assert (item.head_sha, item.review_decision, item.merge_state, item.mergeable) == (
            SHA_A,
            "APPROVED",
            "CLEAN",
            "MERGEABLE",
        )

    def test_fields_survive_a_json_round_trip(self):
        item = item_from_pr(_pr())
        assert ItemSnapshot.from_dict(json.loads(json.dumps(item.to_dict()))) == item

    def test_old_snapshot_file_without_the_fields_loads(self):
        data = item_from_pr(_pr()).to_dict()
        for name in ("head_sha", "review_decision", "merge_state", "mergeable"):
            del data[name]
        item = ItemSnapshot.from_dict(data)
        assert item.head_sha is None and item.merge_state is None

    def test_new_snapshot_file_with_unknown_keys_loads(self):
        data = {**item_from_pr(_pr()).to_dict(), "future_field": "x"}
        assert ItemSnapshot.from_dict(data).head_sha == SHA_A


class TestDiff:
    def test_push_with_ci_and_history_unchanged_is_a_changed_row(self):
        prev, curr = _item(), _item(head_sha=SHA_B)
        assert prev.ci_status == curr.ci_status and prev.history == curr.history
        [delta] = diff_snapshots(make_snapshot(items=[prev]), make_snapshot(items=[curr])).deltas
        assert delta.kind is ChangeKind.CHANGED
        assert delta.changed_fields == ("head_sha",)

    def test_identical_rows_are_unchanged(self):
        [delta] = diff_snapshots(
            make_snapshot(items=[_item()]), make_snapshot(items=[_item()])
        ).deltas
        assert delta.kind is ChangeKind.UNCHANGED

    def test_approval_keeps_reported_decision_next_to_a_head_change(self):
        prev, curr = _item(), _item(head_sha=SHA_B)
        assert curr.review_decision == "APPROVED"
        assert _changed_fields(prev, curr) == ("head_sha",)

    @pytest.mark.parametrize(
        ("overrides", "field_name"),
        [
            ({"review_decision": "CHANGES_REQUESTED"}, "review_decision"),
            ({"review_decision": None}, "review_decision"),
            ({"merge_state": "BEHIND"}, "merge_state"),
            ({"mergeable": "CONFLICTING"}, "mergeable"),
        ],
    )
    def test_each_field_marks_the_row_changed(self, overrides, field_name):
        assert _changed_fields(_item(), _item(**overrides)) == (field_name,)

    @pytest.mark.parametrize(
        ("prev_overrides", "curr_overrides"),
        [
            ({"merge_state": "UNKNOWN", "mergeable": "UNKNOWN"}, {}),
            ({}, {"merge_state": "UNKNOWN", "mergeable": "UNKNOWN"}),
            ({"mergeable": "UNKNOWN"}, {"mergeable": "CONFLICTING"}),
        ],
    )
    def test_unknown_mergeability_is_not_a_change(self, prev_overrides, curr_overrides):
        prev, curr = _item(**prev_overrides), _item(**curr_overrides)
        fields = _changed_fields(prev, curr)
        assert "mergeable" not in fields
        assert "merge_state" not in fields

    def test_unknown_to_known_alone_leaves_the_row_unchanged(self):
        prev = _item(merge_state="UNKNOWN", mergeable="UNKNOWN")
        [delta] = diff_snapshots(make_snapshot(items=[prev]), make_snapshot(items=[_item()])).deltas
        assert delta.kind is ChangeKind.UNCHANGED

    def test_unknown_does_not_hide_a_head_change(self):
        prev = _item(merge_state="UNKNOWN", mergeable="UNKNOWN")
        assert _changed_fields(prev, _item(head_sha=SHA_B)) == ("head_sha",)

    def test_baseline_without_the_fields_is_not_a_change(self):
        prev = _item(head_sha=None, review_decision=None, merge_state=None, mergeable=None)
        [delta] = diff_snapshots(make_snapshot(items=[prev]), make_snapshot(items=[_item()])).deltas
        assert delta.kind is ChangeKind.UNCHANGED

    def test_json_diff_names_the_field(self):
        result = diff_snapshots(
            make_snapshot(items=[_item()]), make_snapshot(items=[_item(head_sha=SHA_B)])
        )
        [delta] = result.to_dict()["deltas"]
        assert delta["changed_fields"] == ["head_sha"]
        assert delta["curr"]["head_sha"] == SHA_B


def _render(prev: ItemSnapshot, curr: ItemSnapshot, *, detail: bool = False) -> str:
    console = Console(width=200, color_system=None, record=True)
    diff = diff_snapshots(make_snapshot(items=[prev]), make_snapshot(items=[curr]))
    render_diff(diff, console=console, detail=detail)
    return console.export_text()


class TestRender:
    def test_default_diff_table_has_no_detail_columns(self):
        out = _render(_item(), _item(head_sha=SHA_B))
        for header in ("Head", "Review", "Merge"):
            assert header not in out
        assert SHA_B[:7] not in out

    def test_default_diff_note_names_the_changed_fields(self):
        prev = _item()
        curr = _item(head_sha=SHA_B, review_decision="CHANGES_REQUESTED", merge_state="BEHIND")
        out = _render(prev, curr)
        assert "head!; review!; merge!" in out

    def test_default_diff_note_is_empty_when_nothing_new_changed(self):
        out = _render(_item(), _item(state="closed"))
        row = next(line for line in out.splitlines() if "o/r" in line)
        assert "head!" not in row and "review!" not in row and "merge!" not in row

    def test_detail_adds_columns_and_marks_changed_values(self):
        out = _render(_item(), _item(head_sha=SHA_B, merge_state="BEHIND"), detail=True)
        row = next(line for line in out.splitlines() if "o/r" in line)
        assert "Head" in out and "Review" in out and "Merge" in out
        assert f"{SHA_B[:7]}!" in row
        assert "approved" in row and "approved!" not in row
        assert "behind!" in row

    def test_detail_ignored_for_issue_snapshots(self):
        console = Console(width=200, color_system=None, record=True)
        diff = diff_snapshots(
            make_snapshot(kind="issue", items=[make_item(key="o/r#1")]),
            make_snapshot(kind="issue", items=[make_item(key="o/r#1", state="closed")]),
        )
        render_diff(diff, console=console, detail=True)
        assert "Head" not in console.export_text()


class FakePRClient:
    prs: list[PRInfo] = []

    def __enter__(self) -> FakePRClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def list_prs_by_author(self, *_: Any, **__: Any) -> PRListResult:
        return PRListResult(prs=list(self.prs))


@pytest.fixture
def fake_client(monkeypatch, tkt_home) -> type[FakePRClient]:  # noqa: ARG001
    monkeypatch.setattr(FakePRClient, "prs", [])
    monkeypatch.setattr(pr_list, "PRClient", FakePRClient)
    monkeypatch.setattr(pr_list, "_get_repos", lambda *_: None)
    monkeypatch.setattr(pr_list, "console", Console(width=200, color_system=None))
    return FakePRClient


class TestPrList:
    def test_snapshot_stores_the_four_fields(self, fake_client):
        fake_client.prs = [_pr()]
        assert pr_list.cmd_list(snapshot_name="s") == 0
        [item] = store.load("pr", "s").items
        assert (item.head_sha, item.review_decision, item.merge_state, item.mergeable) == (
            SHA_A,
            "APPROVED",
            "CLEAN",
            "MERGEABLE",
        )

    def test_diff_reports_a_push_as_head_change(self, fake_client, capsys):
        fake_client.prs = [_pr()]
        assert pr_list.cmd_list(watch_name="w") == 0
        capsys.readouterr()

        fake_client.prs = [_pr(head_sha=SHA_B)]
        assert pr_list.cmd_list(watch_name="w") == 0
        out = capsys.readouterr().out
        assert "*1 changed" in out
        assert "head!" in out

    def test_diff_json_stdout_is_only_json(self, fake_client, capsys):
        fake_client.prs = [_pr()]
        assert pr_list.cmd_list(watch_name="w", output_format="json") == 0
        capsys.readouterr()

        fake_client.prs = [_pr(head_sha=SHA_B)]
        assert pr_list.cmd_list(watch_name="w", output_format="json", show_detail=True) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["deltas"][0]["changed_fields"] == ["head_sha"]

    def test_warm_up_unknown_is_not_reported(self, fake_client, capsys):
        fake_client.prs = [_pr(merge_state="UNKNOWN", mergeable="UNKNOWN")]
        assert pr_list.cmd_list(watch_name="w") == 0
        capsys.readouterr()

        fake_client.prs = [_pr()]
        assert pr_list.cmd_list(watch_name="w") == 0
        assert "*0 changed" in capsys.readouterr().out

    def test_default_table_is_unchanged_without_detail(self, fake_client, capsys):
        fake_client.prs = [_pr()]
        assert pr_list.cmd_list() == 0
        plain = capsys.readouterr().out
        fake_client.prs = [_pr(head_sha=None, review_decision=None, merge_state=None)]
        assert pr_list.cmd_list() == 0
        assert capsys.readouterr().out == plain
        for header in ("Head", "Review", "Merge"):
            assert header not in plain

    def test_detail_adds_columns(self, fake_client, capsys):
        fake_client.prs = [_pr()]
        assert pr_list.cmd_list(show_detail=True) == 0
        out = capsys.readouterr().out
        assert "Head" in out and "Review" in out and "Merge" in out
        assert SHA_A[:7] in out and "approved" in out and "clean" in out
