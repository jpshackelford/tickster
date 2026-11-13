"""Dependency facts in issue snapshots, diffs and the `issue list` output."""

from __future__ import annotations

import io
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from rich.console import Console

from src.issue.cli import list_cmd as issue_list
from src.issue.models import IssueInfo, IssueListResult, IssueState, Milestone
from src.snapshot import store
from src.snapshot.convert import item_from_issue, snapshot_from_issues
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import ChangeKind, ItemSnapshot, Snapshot, SnapshotScope
from src.snapshot.render import render_diff

from .conftest import make_item, make_snapshot

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
DEPS = ("open_blockers", "blocking", "parent", "milestone")


def issue_item(key: str = "o/r#1", **deps) -> ItemSnapshot:
    return replace(make_item(key=key), **{"open_blockers": (), **deps})


def issue_snapshot(*items: ItemSnapshot) -> Snapshot:
    return make_snapshot(kind="issue", items=list(items))


def issue_info(number: int = 1, **overrides) -> IssueInfo:
    fields = {
        "repo": "o/r",
        "number": number,
        "title": "t",
        "state": IssueState.OPEN,
        "history": "o",
        "linked_pr": None,
        "labels": [],
        "created_at": NOW,
        "closed_at": None,
        "last_activity": NOW,
        "author": "octocat",
    }
    return IssueInfo(**{**fields, **overrides})


class TestSnapshotItem:
    def test_an_item_without_recorded_facts_has_none_of_the_keys(self):
        data = make_item().to_dict()

        assert not set(DEPS) & set(data)

    def test_an_old_snapshot_file_loads_and_resaves_byte_for_byte(self):
        old = make_snapshot(
            kind="issue",
            items=[make_item(key="o/r#1"), make_item(key="o/r#2")],
            scope=SnapshotScope(states=("open",)),
        )
        text = json.dumps(old.to_dict(), indent=2)

        reloaded = Snapshot.from_dict(json.loads(text))

        assert all(it.open_blockers is None for it in reloaded.items)
        assert json.dumps(reloaded.to_dict(), indent=2) == text

    def test_recorded_facts_round_trip(self):
        item = issue_item(
            open_blockers=("o/r#2", "?"),
            blocking=3,
            parent="o/r#9",
            milestone=Milestone("v2", "2026-12-01T00:00:00Z"),
        )

        data = item.to_dict()

        assert data["open_blockers"] == ["o/r#2", "?"]
        assert data["blocking"] == 3
        assert data["parent"] == "o/r#9"
        assert data["milestone"] == {"title": "v2", "due_on": "2026-12-01T00:00:00Z"}
        assert ItemSnapshot.from_dict(json.loads(json.dumps(data))) == item

    def test_recorded_empty_facts_keep_their_keys(self):
        data = issue_item().to_dict()

        assert data["open_blockers"] == []
        assert data["blocking"] == 0
        assert data["parent"] is None
        assert data["milestone"] is None
        assert ItemSnapshot.from_dict(data) == issue_item()

    def test_issue_snapshots_always_record_the_facts(self):
        info = issue_info(
            open_blockers=["o/r#2"], blocking=1, parent="o/r#9", milestone=Milestone("v2")
        )

        item = item_from_issue(info)

        assert item.open_blockers == ("o/r#2",)
        assert item.blocking == 1
        assert item.parent == "o/r#9"
        assert item.milestone == Milestone("v2", None)
        assert item_from_issue(issue_info()).open_blockers == ()


class TestDiff:
    def test_last_blocker_going_away_marks_the_row_unblocked(self):
        prev = issue_snapshot(issue_item(open_blockers=("o/r#121",)))
        curr = issue_snapshot(issue_item(open_blockers=()))

        [delta] = diff_snapshots(prev, curr).deltas

        assert delta.kind is ChangeKind.CHANGED
        assert delta.changed_fields == ("open_blockers",)
        assert delta.blocker_note == "unblocked"

    def test_first_blocker_appearing_marks_the_row_blocked(self):
        prev = issue_snapshot(issue_item())
        curr = issue_snapshot(issue_item(open_blockers=("o/r#5",)))

        [delta] = diff_snapshots(prev, curr).deltas

        assert delta.blocker_note == "blocked"

    def test_one_blocker_replacing_another_is_blockers_changed(self):
        prev = issue_snapshot(issue_item(open_blockers=("o/r#5",)))
        curr = issue_snapshot(issue_item(open_blockers=("o/r#5", "o/r#6")))

        [delta] = diff_snapshots(prev, curr).deltas

        assert delta.blocker_note == "blockers changed"

    @pytest.mark.parametrize(
        "changed",
        [
            {"blocking": 2},
            {"parent": "o/r#9"},
            {"milestone": Milestone("v2", None)},
        ],
    )
    def test_a_change_in_blocking_parent_or_milestone_alone_leaves_the_row_unchanged(self, changed):
        prev = issue_snapshot(issue_item(blocking=1))
        curr = issue_snapshot(replace(issue_item(blocking=1), **changed))

        [delta] = diff_snapshots(prev, curr).deltas

        assert delta.kind is ChangeKind.UNCHANGED
        assert delta.changed_fields == ()

    def test_a_baseline_without_the_facts_does_not_flag_every_row(self):
        prev = issue_snapshot(make_item(key="o/r#1"))
        curr = issue_snapshot(issue_item(open_blockers=("o/r#5",)))

        [delta] = diff_snapshots(prev, curr).deltas

        assert delta.kind is ChangeKind.UNCHANGED

    def test_json_diff_names_the_field_and_the_note(self):
        prev = issue_snapshot(issue_item(open_blockers=("o/r#121",)))
        curr = issue_snapshot(issue_item())

        data = diff_snapshots(prev, curr).to_dict()

        [delta] = data["deltas"]
        assert delta["changed_fields"] == ["open_blockers"]
        assert delta["blocker_note"] == "unblocked"

    def test_table_note_says_unblocked(self):
        prev = issue_snapshot(issue_item(open_blockers=("o/r#121",)))
        curr = issue_snapshot(issue_item())
        out = io.StringIO()

        render_diff(
            diff_snapshots(prev, curr),
            console=Console(file=out, width=200, color_system=None),
        )

        assert "unblocked" in out.getvalue()


@pytest.fixture
def console(monkeypatch) -> io.StringIO:
    out = io.StringIO()
    monkeypatch.setattr(issue_list, "console", Console(file=out, width=200, color_system=None))
    return out


def table_lines(out: io.StringIO) -> list[str]:
    return [line.split() for line in out.getvalue().splitlines() if line.strip()]


class TestListTable:
    ISSUES = [
        issue_info(1, open_blockers=["o/r#7", "x/y#3"], blocking=0),
        issue_info(2, blocking=4),
    ]

    def test_deps_adds_blocked_by_and_blocks_columns(self, console):
        issue_list._print_issue_table(self.ISSUES, show_deps=True)

        lines = table_lines(console)
        header = lines[0]
        first, second = (line for line in lines if line[0] == "o/r")
        assert header[header.index("PR") + 1 : header.index("Labels")] == [
            "Blocked",
            "by",
            "Blocks",
        ]
        assert "#7,x/y#3" in first
        assert second[second.index("--") :][:3] == ["--", "--", "4"]

    def test_the_default_table_has_neither_column(self, console):
        issue_list._print_issue_table(self.ISSUES)

        assert "Blocked" not in console.getvalue()
        assert "Blocks" not in console.getvalue()

    def test_deps_flag_reaches_the_table_and_adds_a_legend(self, console, monkeypatch):
        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def get_current_user(self) -> str:
                return "octocat"

            def list_issues_by_author(self, *_, **__):
                return IssueListResult(issues=TestListTable.ISSUES)

        monkeypatch.setattr(issue_list, "IssueClient", Client)
        monkeypatch.setattr(issue_list, "_get_repos", lambda *_: None)

        assert issue_list.cmd_list(show_deps=True) == 0

        text = console.getvalue()
        assert "Blocked by" in text
        assert "? = one you cannot read" in text


@pytest.mark.usefixtures("tkt_home")
class TestListJson:
    def test_json_rows_carry_the_four_facts(self, monkeypatch, capsys):
        info = issue_info(
            1,
            open_blockers=["o/r#7"],
            blocking=2,
            parent="o/r#9",
            milestone=Milestone("v2", "2026-12-01T00:00:00Z"),
        )

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def get_current_user(self) -> str:
                return "octocat"

            def list_issues_by_author(self, *_, **__):
                return IssueListResult(issues=[info, issue_info(2)])

        monkeypatch.setattr(issue_list, "IssueClient", Client)
        monkeypatch.setattr(issue_list, "_get_repos", lambda *_: None)

        assert issue_list.cmd_list(output_format="json") == 0

        first, second = json.loads(capsys.readouterr().out)["items"]
        assert first["open_blockers"] == ["o/r#7"]
        assert first["blocking"] == 2
        assert first["parent"] == "o/r#9"
        assert first["milestone"] == {"title": "v2", "due_on": "2026-12-01T00:00:00Z"}
        assert second["open_blockers"] == []
        assert second["parent"] is None
        assert second["milestone"] is None

    def test_watch_reports_the_blocker_closing(self, monkeypatch, console):
        issues = [issue_info(1, open_blockers=["o/r#7"])]

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def get_current_user(self) -> str:
                return "octocat"

            def list_issues_by_author(self, *_, **__):
                return IssueListResult(issues=issues)

        monkeypatch.setattr(issue_list, "IssueClient", Client)
        monkeypatch.setattr(issue_list, "_get_repos", lambda *_: None)

        assert issue_list.cmd_list(watch_name="deps") == 0
        issues[:] = [issue_info(1)]
        console.truncate(0)
        console.seek(0)
        assert issue_list.cmd_list(watch_name="deps") == 0

        assert "unblocked" in console.getvalue()
        assert store.load("issue", "deps").items[0].open_blockers == ()


def test_snapshot_from_issues_scope_round_trip():
    snap = snapshot_from_issues(
        [issue_info(open_blockers=["o/r#2"])], scope=SnapshotScope(), name="n"
    )

    assert Snapshot.from_dict(snap.to_dict()).items == snap.items
