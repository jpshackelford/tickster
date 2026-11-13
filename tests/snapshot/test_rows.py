"""The row: one object for an issue, PR or review, in the list JSON and on disk."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.issue.history import process_issue_data
from src.issue.models import Milestone
from src.norms import store as norms_store
from src.pr.history import process_pr_data
from src.pr.reviewers import ReviewerState
from src.review.github_api import ReviewClient
from src.show.issue import build_issue_show
from src.show.pr import build_pr_show
from src.snapshot.convert import item_from_issue, item_from_pr, item_from_review
from src.snapshot.models import ItemSnapshot
from src.snapshot.rows import ROW_FIELDS, item_url
from tests.show.builders import HEAD, comment, conn, issue_node, login, pr_node, review, ts

from .conftest import make_item

OLD_NAMES = (
    "key",
    "ci_status",
    "is_draft",
    "head_sha",
    "unresolved_thread_count",
    "events",
    "steps",
)
ISSUE_ONLY = {"linked_pr", "closed_at", "open_blockers", "blocking", "parent", "milestone"}
PR_ONLY = {
    "draft",
    "ci",
    "unresolved_threads",
    "head",
    "review_decision",
    "merge_state",
    "mergeable",
    "reviewers",
    "step_status",
}
REVIEW_ONLY = {"review_status", "wait_seconds"}


def full_item(kind: str) -> ItemSnapshot:
    if kind == "issue":
        return make_item(
            kind="issue",
            linked_pr="o/r#9",
            closed_at="2026-11-05T10:45:40Z",
            open_blockers=("o/r#2", "?"),
            blocking=2,
            parent="o/r#1",
            milestone=Milestone("v2", "2026-12-01T00:00:00Z"),
            labels=("bug",),
        )
    reviewer = ReviewerState(login="bob", actor_class="human", requested=True)
    return make_item(
        kind=kind,
        draft=True,
        head="a" * 40,
        review_decision="APPROVED",
        merge_state="CLEAN",
        mergeable="MERGEABLE",
        reviewers=(reviewer,),
        step_status={"review": "done"} if kind == "pr" else None,
        **({"review_status": "review", "wait_seconds": 12.5} if kind == "review" else {}),
    )


@pytest.mark.parametrize("kind", ["issue", "pr", "review"])
class TestRowShape:
    def test_to_dict_has_exactly_the_keys_of_its_kind_in_order(self, kind):
        assert list(full_item(kind).to_dict()) == list(ROW_FIELDS[kind])

    def test_to_dict_from_dict_to_dict_is_identical(self, kind):
        row = json.loads(json.dumps(full_item(kind).to_dict()))
        assert ItemSnapshot.from_dict(row).to_dict() == row
        assert ItemSnapshot.from_dict(row) == full_item(kind)

    def test_no_key_of_another_kind_or_an_old_name(self, kind):
        keys = set(full_item(kind).to_dict())
        foreign = {
            "issue": PR_ONLY | REVIEW_ONLY,
            "pr": ISSUE_ONLY | REVIEW_ONLY,
            "review": ISSUE_ONLY,
        }[kind]
        assert not keys & foreign
        assert not keys & set(OLD_NAMES)


def test_the_field_table_lists_the_pr_fields_in_review_rows_too():
    assert set(ROW_FIELDS["review"]) == set(ROW_FIELDS["pr"]) | REVIEW_ONLY
    assert set(ROW_FIELDS["issue"]) - ISSUE_ONLY == set(ROW_FIELDS["pr"]) - PR_ONLY


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("issue", "https://github.com/o/r/issues/5"),
        ("pr", "https://github.com/o/r/pull/5"),
        ("review", "https://github.com/o/r/pull/5"),
    ],
)
def test_item_url(kind, expected):
    assert item_url("o/r", kind, 5) == expected


def _mutated(kind: str, key: str, value) -> dict:
    row = full_item(kind).to_dict()
    row[key] = value
    return row


def _without(kind: str, key: str) -> dict:
    row = full_item(kind).to_dict()
    del row[key]
    return row


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (_without("pr", "head"), "missing field 'head'"),
        (_without("issue", "closed_at"), "missing field 'closed_at'"),
        (_without("review", "wait_seconds"), "missing field 'wait_seconds'"),
        (_mutated("pr", "events", []), "unexpected field 'events'"),
        (_mutated("pr", "key", "o/r#1"), "unexpected field 'key'"),
        (_mutated("issue", "draft", False), "unexpected field 'draft'"),
        (_mutated("pr", "closed_at", None), "unexpected field 'closed_at'"),
        (_mutated("pr", "number", "5"), "field 'number' has the wrong type"),
        (_mutated("pr", "number", True), "field 'number' has the wrong type"),
        (_mutated("pr", "labels", "bug"), "field 'labels' has the wrong type"),
        (_mutated("pr", "labels", [1]), "field 'labels' has the wrong type"),
        (_mutated("pr", "draft", 0), "field 'draft' has the wrong type"),
        (
            _mutated("pr", "unresolved_threads", 1.5),
            "field 'unresolved_threads' has the wrong type",
        ),
        (_mutated("pr", "step_status", ["a"]), "field 'step_status' has the wrong type"),
        (_mutated("pr", "step_status", {"a": 1}), "field 'step_status' has the wrong type"),
        (_mutated("pr", "reviewers", [{"login": "bob"}]), "field 'reviewers' has the wrong type"),
        (_mutated("pr", "reviewers", "bob"), "field 'reviewers' has the wrong type"),
        (_mutated("issue", "milestone", {"due_on": None}), "field 'milestone' has the wrong type"),
        (_mutated("issue", "milestone", "v2"), "field 'milestone' has the wrong type"),
        (_mutated("issue", "open_blockers", None), "field 'open_blockers' has the wrong type"),
        (_mutated("review", "wait_seconds", "1"), "field 'wait_seconds' has the wrong type"),
        (_mutated("review", "wait_seconds", False), "field 'wait_seconds' has the wrong type"),
        (_mutated("pr", "kind", "bogus"), "field 'kind' has the wrong type"),
        ([], "a row is not a JSON object"),
    ],
)
def test_from_dict_rejects(row, message):
    with pytest.raises(ValueError, match=message):
        ItemSnapshot.from_dict(row)


def test_a_wait_time_may_be_an_integer():
    row = _mutated("review", "wait_seconds", 60)
    assert ItemSnapshot.from_dict(row).wait_seconds == 60


@pytest.fixture(autouse=True)
def _no_norms():
    norms_store.set_loader(lambda _repo: None)


PR_LABELS = conn([{"name": "bug"}, {"name": "ready"}])


def _pr_node(**overrides) -> dict:
    timeline = [review("R1", "bob", "APPROVED", ts(11), HEAD)]
    return pr_node(
        timeline,
        labels=PR_LABELS,
        latestReviews=conn(
            [
                {
                    "author": login("bob"),
                    "state": "APPROVED",
                    "submittedAt": ts(11),
                    "commit": {"oid": HEAD},
                }
            ]
        ),
        reviewRequests=conn(
            [
                {
                    "asCodeOwner": False,
                    "requestedReviewer": {"__typename": "User", "login": "carol"},
                }
            ]
        ),
        **overrides,
    )


PR_SHARED = (
    "ref",
    "kind",
    "repo",
    "number",
    "url",
    "title",
    "state",
    "author",
    "labels",
    "history",
    "created_at",
    "last_activity",
    "draft",
    "ci",
    "unresolved_threads",
    "head",
    "review_decision",
    "merge_state",
    "mergeable",
    "reviewers",
)
ISSUE_SHARED = (
    "ref",
    "kind",
    "repo",
    "number",
    "url",
    "title",
    "state",
    "author",
    "labels",
    "history",
    "created_at",
    "last_activity",
    "linked_pr",
    "closed_at",
    "open_blockers",
    "blocking",
    "parent",
    "milestone",
)


def _same(row: dict, shown: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        assert key in row and key in shown, key
        assert row[key] == shown[key], key


def test_a_pr_row_and_pr_show_agree_key_by_key():
    node = _pr_node(isDraft=True, state="OPEN")
    row = item_from_pr(process_pr_data(node, "alice")).to_dict()
    shown = build_pr_show(node, "alice", 600).to_dict()

    _same(json.loads(json.dumps(row)), json.loads(json.dumps(shown)), PR_SHARED)
    assert row["labels"] == ["bug", "ready"]
    assert row["head"] == HEAD
    assert row["url"] == "https://github.com/o/r/pull/7"
    assert [r["login"] for r in row["reviewers"]] == ["bob", "carol"]


def test_an_open_issue_row_and_issue_show_agree_key_by_key():
    node = issue_node(
        [comment("bob", ts(10), "hi")],
        blockedBy={
            "totalCount": 1,
            "nodes": [
                {"number": 3, "state": "OPEN", "repository": {"nameWithOwner": "o/r"}},
            ],
        },
        blocking={
            "totalCount": 2,
            "nodes": [
                {"number": n, "state": "OPEN", "repository": {"nameWithOwner": "o/r"}}
                for n in (7, 8)
            ],
        },
        parent={"number": 1, "repository": {"nameWithOwner": "o/r"}},
        milestone={"title": "v2", "dueOn": "2026-12-01T00:00:00Z"},
    )
    row = item_from_issue(process_issue_data(node, "alice")).to_dict()
    shown = build_issue_show(node, "alice", 600).to_dict()

    _same(json.loads(json.dumps(row)), json.loads(json.dumps(shown)), ISSUE_SHARED)
    assert row["closed_at"] is None and shown["closed_at"] is None
    assert row["open_blockers"] == ["o/r#3"] and row["blocking"] == 2
    assert row["milestone"] == {"title": "v2", "due_on": "2026-12-01T00:00:00Z"}
    assert row["url"] == "https://github.com/o/r/issues/40"


def test_a_closed_issue_has_closed_at_in_the_row_and_in_show():
    node = issue_node([], state="CLOSED", closedAt=ts(12, 30))
    row = item_from_issue(process_issue_data(node, "alice")).to_dict()
    shown = build_issue_show(node, "alice", 600).to_dict()

    assert row["closed_at"] == "2026-11-05T12:30:00Z"
    assert shown["closed_at"] == row["closed_at"]


def _review_info():
    client = ReviewClient.__new__(ReviewClient)
    info = client._process_pr_for_reviewer(_pr_node(isDraft=True), "carol")
    assert info is not None
    return info


def test_review_info_carries_the_pr_fields_from_the_data_it_already_has():
    info = _review_info()

    assert info.created_at.isoformat() == "2026-11-05T10:00:00+00:00"
    assert info.labels == ("bug", "ready")
    assert info.draft is True
    assert info.head_sha == HEAD
    assert info.review_decision == "APPROVED"
    assert info.merge_state == "CLEAN"
    assert [r.login for r in info.reviewers] == ["bob", "carol"]


def test_a_review_row_has_the_pr_keys_plus_review_status_and_wait_seconds():
    row = item_from_review(_review_info()).to_dict()

    assert list(row) == list(ROW_FIELDS["review"])
    assert row["step_status"] is None
    assert row["kind"] == "review"
    assert row["url"] == "https://github.com/o/r/pull/7"
    assert row["draft"] is True and row["head"] == HEAD
    assert row["labels"] == ["bug", "ready"]
    assert isinstance(row["wait_seconds"], float)
    assert ItemSnapshot.from_dict(json.loads(json.dumps(row))).to_dict() == row


def test_the_review_row_matches_the_pr_row_for_the_shared_pr_keys():
    node = _pr_node()
    pr_row = item_from_pr(process_pr_data(node, "carol")).to_dict()
    client = ReviewClient.__new__(ReviewClient)
    info = client._process_pr_for_reviewer(node, "carol")
    assert info is not None
    review_row = item_from_review(info).to_dict()

    for key in ("labels", "draft", "ci", "head", "mergeable", "merge_state", "reviewers"):
        assert review_row[key] == pr_row[key], key


def test_a_snapshot_with_a_schema_1_file_is_discarded_end_to_end(tmp_path: Path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    path = snapshots / "issue-hourly.json"
    path.write_text(json.dumps({"schema": 1, "kind": "issue", "name": "hourly", "items": []}))
    env = {"PATH": "/usr/bin:/bin", "TKT_HOME": str(tmp_path), "HOME": str(tmp_path)}

    proc = subprocess.run(
        [sys.executable, "-m", "src", "snapshot", "show", "issue/hourly", "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).parents[2],
        check=False,
    )

    assert proc.stdout == ""
    assert proc.stderr.splitlines()[0] == (
        "tkt: discarded snapshot issue/hourly: schema 1, this tkt writes schema 2"
    )
    assert not path.exists()
