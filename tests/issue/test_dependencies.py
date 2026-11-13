"""Dependency facts (blockers, blocking, parent, milestone) read from recorded GraphQL answers.

``fixtures/dependency_facts.json`` holds the answers GitHub gave on 2026-11-13 for
jpshackelford/tickster #120, #123, #124 and #127 and astral-sh/uv#14524 (the only
milestone with a due date among them); both repos are public.
"""

import json
from pathlib import Path

import pytest

from src.issue import dependencies
from src.issue.history import process_issue_data
from src.issue.models import Milestone

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "dependency_facts.json").read_text())


def issue_data(ref: str) -> dict:
    """A recorded dependency answer dressed as the rest of an issue node."""
    recorded = FIXTURES[ref]
    return {
        "number": recorded["number"],
        "title": "t",
        "state": recorded["state"],
        "createdAt": "2026-11-01T00:00:00Z",
        "closedAt": None,
        "author": {"login": "alice"},
        "repository": recorded["repository"],
        "labels": {"nodes": []},
        "timelineItems": {"nodes": []},
        **{k: recorded[k] for k in ("blockedBy", "blocking", "parent", "milestone")},
    }


def blocker(number: int, state: str, repo: str = "o/r") -> dict:
    return {"number": number, "state": state, "repository": {"nameWithOwner": repo}}


def blocked_by(*nodes: dict | None, total: int | None = None) -> dict:
    return {"blockedBy": {"totalCount": len(nodes) if total is None else total, "nodes": nodes}}


class TestRecordedIssues:
    def test_open_blockers_are_listed_and_closed_ones_are_left_out(self):
        info = process_issue_data(issue_data("jpshackelford/tickster#127"), "alice")

        assert FIXTURES["jpshackelford/tickster#127"]["blockedBy"]["totalCount"] == 6
        assert info.open_blockers == [
            "jpshackelford/tickster#122",
            "jpshackelford/tickster#124",
            "jpshackelford/tickster#126",
        ]
        assert info.parent == "jpshackelford/tickster#120"

    def test_only_closed_blockers_leave_the_issue_unblocked(self):
        info = process_issue_data(issue_data("jpshackelford/tickster#124"), "alice")

        assert FIXTURES["jpshackelford/tickster#124"]["blockedBy"]["totalCount"] == 2
        assert info.open_blockers == []
        assert info.blocking == 1

    def test_blocking_counts_open_issues_and_a_parent_is_a_ref(self):
        info = process_issue_data(issue_data("jpshackelford/tickster#123"), "alice")

        assert info.blocking == 2
        assert info.parent == "jpshackelford/tickster#120"
        assert info.open_blockers == []

    def test_milestone_has_title_and_utc_due_date(self):
        info = process_issue_data(issue_data("astral-sh/uv#14524"), "alice")

        assert info.milestone == Milestone(title="v0.8.0", due_on="2025-07-17T00:00:00Z")

    def test_an_issue_with_none_of_these_has_empty_facts(self):
        info = process_issue_data(issue_data("jpshackelford/tickster#120"), "alice")

        assert info.open_blockers == []
        assert info.blocking == 0
        assert info.parent is None
        assert info.milestone is None


class TestOpenBlockers:
    def test_two_open_blockers_in_two_repos_are_sorted_by_repo_then_number(self):
        data = blocked_by(blocker(10, "OPEN", "o/r"), blocker(9, "OPEN", "a/b"), blocker(2, "OPEN"))

        assert dependencies.open_blockers(data) == ["a/b#9", "o/r#2", "o/r#10"]

    def test_a_closed_blocker_is_not_open(self):
        data = blocked_by(blocker(1, "CLOSED"), blocker(2, "OPEN"))

        assert dependencies.open_blockers(data) == ["o/r#2"]

    def test_each_unreadable_blocker_is_a_question_mark_after_the_refs(self):
        data = blocked_by(blocker(5, "OPEN"), None, total=4)

        assert dependencies.open_blockers(data) == ["o/r#5", "?", "?", "?"]

    def test_nothing_unreadable_when_every_node_is_there(self):
        assert dependencies.open_blockers(blocked_by(blocker(1, "CLOSED"))) == []

    def test_a_node_without_the_connection_has_no_blockers(self):
        assert dependencies.open_blockers({}) == []


class TestMilestone:
    def test_no_due_date(self):
        data = {"milestone": {"title": "v2", "dueOn": None}}

        assert dependencies.milestone(data) == Milestone(title="v2", due_on=None)

    def test_due_date_with_an_offset_is_converted_to_utc(self):
        data = {"milestone": {"title": "v2", "dueOn": "2026-12-01T01:00:00+02:00"}}

        milestone = dependencies.milestone(data)

        assert milestone is not None
        assert milestone.due_on == "2026-11-30T23:00:00Z"


class TestDepsLine:
    def test_all_parts_with_own_repo_refs_shortened(self):
        line = dependencies.deps_line(
            ["o/r#121", "o/r#123"], 1, "o/r#120", Milestone("v2", None), "o/r"
        )

        assert line == "blocked by: #121, #123  blocks: 1  parent: #120  milestone: v2"

    def test_empty_parts_are_left_out(self):
        assert dependencies.deps_line([], 2, None, None, "o/r") == "blocks: 2"

    def test_nothing_to_say(self):
        assert dependencies.deps_line([], 0, None, None, "o/r") is None

    @pytest.mark.parametrize(("ref", "short"), [("x/y#4", "x/y#4"), ("?", "?"), ("o/r#4", "#4")])
    def test_short_ref_keeps_other_repos_and_unreadable_blockers(self, ref, short):
        assert dependencies.short_ref(ref, "o/r") == short
