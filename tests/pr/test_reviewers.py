"""Per-reviewer PR state: records, derived values, snapshots, diffs and the list column."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from rich.console import Console

from src.board import config as board_config
from src.norms import store as norms_store
from src.norms.model import Actors, Norms
from src.pr.cli import list_cmd as pr_list
from src.pr.history import process_pr_data
from src.pr.models import CIStatus, PRInfo, PRListResult, PRState
from src.pr.reviewers import (
    TEAM_UNKNOWN,
    ReviewerState,
    build_reviewers,
    compact_reviewers,
    named_reviewers,
    requested_reviewer_login,
    reviewer_changes,
)
from src.snapshot import store
from src.snapshot.convert import item_from_pr
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import Snapshot, SnapshotScope
from src.snapshot.render import render_diff

OLD = "0945b15" + "0" * 33
HEAD = "e66822d" + "0" * 33
REQUESTED_AT = "2026-11-05T02:13:00Z"
SUBMITTED_AT = "2026-11-05T02:33:00Z"
AFTER_REVIEW = "2026-11-05T03:00:00Z"
NORMS = Norms(actors=Actors(agent_logins=("all-hands-bot",)))
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def request(login: str | None = None, *, slug: str | None = None, code_owner: bool = False):
    if slug is not None:
        reviewer: dict | None = {"__typename": "Team", "slug": slug}
    elif login is None:
        reviewer = None
    else:
        reviewer = {"__typename": "User", "login": login}
    return {"asCodeOwner": code_owner, "requestedReviewer": reviewer}


def review(login: str, state: str, oid: str, at: str = SUBMITTED_AT):
    return {"author": {"login": login}, "state": state, "submittedAt": at, "commit": {"oid": oid}}


def requested_event(login: str, at: str, actor: str = "alice"):
    return {
        "__typename": "ReviewRequestedEvent",
        "createdAt": at,
        "actor": {"login": actor},
        "requestedReviewer": {"__typename": "User", "login": login},
    }


def pr_data(*, requests=(), reviews=(), events=(), head: str = HEAD) -> dict:
    return {
        "repository": {"nameWithOwner": "owner/repo"},
        "number": 1,
        "title": "Test PR",
        "author": {"login": "alice"},
        "createdAt": "2026-11-05T01:00:00Z",
        "closedAt": None,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "headRefOid": head,
        "reviewThreads": {"nodes": []},
        "reviewRequests": {"nodes": list(requests)},
        "latestReviews": {"nodes": list(reviews)},
        "commits": {"nodes": []},
        "timelineItems": {"nodes": list(events)},
    }


def by_login(reviewers: tuple[ReviewerState, ...] | None) -> dict[str, ReviewerState]:
    assert reviewers is not None
    return {r.login: r for r in reviewers}


@pytest.fixture
def with_norms():
    norms_store.set_loader(lambda _repo: NORMS)


class TestRecords:
    def test_not_fetched_is_none(self):
        data = pr_data()
        del data["reviewRequests"], data["latestReviews"]
        assert build_reviewers(data, "alice") is None

    def test_review_on_old_head_without_request_needs_rereview(self):
        data = pr_data(reviews=[review("enyst", "APPROVED", OLD)])
        enyst = by_login(build_reviewers(data, "jp"))["enyst"]
        assert (enyst.latest_state, enyst.reviewed_commit, enyst.on_head) == (
            "APPROVED",
            OLD,
            False,
        )
        assert enyst.rereview_needed
        assert not enyst.requested and not enyst.waiting and not enyst.rereview_requested

    def test_rerequest_after_that_review_is_waiting_not_needed(self):
        data = pr_data(
            requests=[request("enyst")],
            reviews=[review("enyst", "APPROVED", OLD)],
            events=[requested_event("enyst", AFTER_REVIEW, actor="jp")],
        )
        enyst = by_login(build_reviewers(data, "jp"))["enyst"]
        assert enyst.requested and enyst.waiting and enyst.rereview_requested
        assert not enyst.rereview_needed
        assert (enyst.requested_by, enyst.requested_at) == ("jp", AFTER_REVIEW)

    def test_request_older_than_the_review_is_not_waiting(self):
        data = pr_data(
            requests=[request("enyst")],
            reviews=[review("enyst", "COMMENTED", HEAD)],
            events=[requested_event("enyst", REQUESTED_AT)],
        )
        enyst = by_login(build_reviewers(data, "jp"))["enyst"]
        assert enyst.requested and not enyst.waiting and not enyst.rereview_requested

    def test_request_with_unknown_time_after_a_review_counts_as_rerequest(self):
        data = pr_data(requests=[request("enyst")], reviews=[review("enyst", "APPROVED", OLD)])
        enyst = by_login(build_reviewers(data, "jp"))["enyst"]
        assert enyst.waiting and enyst.rereview_requested
        assert enyst.requested_by is None

    def test_agent_requested_then_approved_on_head(self):
        requested = pr_data(
            requests=[request("all-hands-bot")],
            events=[requested_event("all-hands-bot", REQUESTED_AT)],
        )
        bot = by_login(build_reviewers(requested, "jp", NORMS))["all-hands-bot"]
        assert (bot.requested, bot.waiting, bot.latest_state) == (True, True, None)
        assert bot.actor_class == "agent"
        assert not bot.rereview_needed

        approved_pr = pr_data(
            reviews=[review("all-hands-bot", "APPROVED", HEAD)],
            events=[requested_event("all-hands-bot", REQUESTED_AT)],
        )
        bot = by_login(build_reviewers(approved_pr, "jp", NORMS))["all-hands-bot"]
        assert (bot.requested, bot.waiting) == (False, False)
        assert (bot.latest_state, bot.on_head, bot.actor_class) == ("APPROVED", True, "agent")

    def test_request_and_review_merge_into_one_record(self):
        data = pr_data(
            requests=[request("bob", code_owner=True)],
            reviews=[review("BOB", "CHANGES_REQUESTED", HEAD, "2026-11-05T01:30:00Z")],
            events=[requested_event("bob", AFTER_REVIEW)],
        )
        [bob] = build_reviewers(data, "jp") or ()
        assert bob.as_code_owner and bob.requested and bob.latest_state == "CHANGES_REQUESTED"

    def test_latest_request_event_wins_and_other_items_are_ignored(self):
        data = pr_data(
            requests=[request("bob")],
            events=[
                requested_event("bob", "2026-11-05T05:00:00Z", actor="carol"),
                requested_event("bob", "2026-11-05T01:00:00Z", actor="alice"),
                {"__typename": "ReviewRequestedEvent", "createdAt": REQUESTED_AT},
                {"__typename": "IssueComment", "createdAt": REQUESTED_AT},
                None,
            ],
        )
        [bob] = build_reviewers(data, "jp") or ()
        assert (bob.requested_by, bob.requested_at) == ("carol", "2026-11-05T05:00:00Z")

    def test_reviewers_are_sorted_and_classified(self):
        data = pr_data(
            requests=[request("zed"), request("jp"), None],
            reviews=[
                review("dependabot[bot]", "COMMENTED", HEAD),
                review("all-hands-bot", "APPROVED", HEAD),
                None,
            ],
        )
        records = build_reviewers(data, "jp", NORMS) or ()
        assert [(r.login, r.actor_class) for r in records] == [
            ("all-hands-bot", "agent"),
            ("dependabot[bot]", "bot"),
            ("jp", "me"),
            ("zed", "human"),
        ]

    def test_deleted_reviewer_is_ghost_and_commitless_review_is_off_head(self):
        data = pr_data(reviews=[{"author": None, "state": "APPROVED", "submittedAt": SUBMITTED_AT}])
        [ghost] = build_reviewers(data, "jp") or ()
        assert ghost.login == "ghost" and ghost.reviewed_commit is None and not ghost.on_head

    def test_json_carries_the_derived_values(self):
        data = pr_data(reviews=[review("enyst", "APPROVED", OLD)])
        [enyst] = build_reviewers(data, "jp") or ()
        as_json = enyst.to_dict()
        assert as_json["rereview_needed"] is True
        assert as_json["waiting"] is False and as_json["rereview_requested"] is False
        assert {"requested", "latest_state", "reviewed_commit", "on_head", "actor_class"} <= set(
            as_json
        )
        assert ReviewerState.from_dict(as_json) == enyst


class TestTeams:
    def test_readable_team_is_named_by_slug(self):
        [team] = build_reviewers(pr_data(requests=[request(slug="core")]), "jp") or ()
        assert team.login == "team:core" and team.actor_class is None and team.requested

    def test_unreadable_team_is_team_unknown_and_logged(self, caplog):
        data = pr_data(requests=[request(None), request("bob")])
        with caplog.at_level(logging.WARNING):
            records = by_login(build_reviewers(data, "jp"))
        assert records[TEAM_UNKNOWN].requested and records[TEAM_UNKNOWN].actor_class is None
        assert "could not be read" in caplog.text

    def test_requested_reviewer_login_forms(self):
        assert requested_reviewer_login({"__typename": "Bot", "login": "x"}) == "x"
        assert requested_reviewer_login({"__typename": "Team", "slug": "core"}) == "team:core"
        assert requested_reviewer_login(None) == TEAM_UNKNOWN
        assert requested_reviewer_login({"__typename": "Mannequin"}) == "ghost"

    def test_process_pr_data_survives_an_unreadable_team(self):
        data = pr_data(
            requests=[request(None)],
            events=[
                {
                    "__typename": "ReviewRequestedEvent",
                    "createdAt": REQUESTED_AT,
                    "actor": {"login": "alice"},
                    "requestedReviewer": None,
                }
            ],
        )
        info = process_pr_data(data, "jp")
        assert by_login(info.reviewers)[TEAM_UNKNOWN].requested_by == "alice"
        assert "H" in info.history


class TestProcessPrData:
    @pytest.mark.usefixtures("with_norms")
    def test_uses_the_repo_norms_for_actor_class(self):
        data = pr_data(reviews=[review("all-hands-bot", "APPROVED", HEAD)])
        info = process_pr_data(data, "jp")
        assert by_login(info.reviewers)["all-hands-bot"].actor_class == "agent"

    def test_truncated_connection_is_flagged(self):
        data = pr_data()
        assert process_pr_data(data, "jp").reviewers_truncated is False
        data["latestReviews"]["truncated"] = True
        assert process_pr_data(data, "jp").reviewers_truncated is True

    def test_history_string_is_unchanged_by_reviewer_fields(self):
        bare = pr_data()
        del bare["reviewRequests"], bare["latestReviews"]
        busy = pr_data(requests=[request("bob")], reviews=[review("bob", "APPROVED", OLD)])
        assert process_pr_data(busy, "jp").history == process_pr_data(bare, "jp").history


def state(login: str = "bob", **fields: Any) -> ReviewerState:
    return ReviewerState(login=login, actor_class="human", **fields)


def approved(oid: str = HEAD, on_head: bool = True, login: str = "bob", **fields: Any):
    return state(
        login,
        latest_state="APPROVED",
        reviewed_commit=oid,
        on_head=on_head,
        submitted_at=SUBMITTED_AT,
        **fields,
    )


class TestChanges:
    def test_new_request(self):
        assert reviewer_changes((), (state(requested=True),)) == ("bob requested",)

    def test_rerequest_after_a_review(self):
        prev = (approved(OLD, False),)
        curr = (approved(OLD, False, requested=True, requested_at=AFTER_REVIEW),)
        assert reviewer_changes(prev, curr) == ("bob ↻ re-requested",)

    def test_bot_approves_on_head(self):
        prev = (state("all-hands-bot", requested=True),)
        curr = (approved(login="all-hands-bot"),)
        assert reviewer_changes(prev, curr) == ("all-hands-bot approved on head",)

    def test_review_on_an_older_commit_names_it(self):
        assert reviewer_changes((), (approved(OLD, False),)) == ("bob approved on 0945b15",)

    def test_review_goes_stale_after_a_push(self):
        assert reviewer_changes((approved(),), (approved(on_head=False),)) == (
            "bob review now on old head",
        )

    def test_request_removed(self):
        assert reviewer_changes((state(requested=True),), (state(),)) == ("bob request removed",)
        assert reviewer_changes((state(requested=True),), ()) == ("bob request removed",)

    def test_review_dismissed(self):
        dismissed = replace(approved(), latest_state="DISMISSED")
        assert reviewer_changes((approved(),), (dismissed,)) == ("bob review dismissed",)

    def test_changes_requested_and_commented_verbs(self):
        changes = replace(approved(), latest_state="CHANGES_REQUESTED")
        commented = replace(approved(), latest_state="COMMENTED")
        assert reviewer_changes((), (changes,)) == ("bob requested changes on head",)
        assert reviewer_changes((), (commented,)) == ("bob commented on head",)

    def test_vanished_review(self):
        assert reviewer_changes((approved(),), ()) == ("bob review gone",)

    def test_no_change_is_silent(self):
        assert reviewer_changes((approved(),), (approved(),)) == ()

    def test_review_that_answers_a_request_is_not_also_a_removal(self):
        assert reviewer_changes((state(requested=True),), (approved(),)) == (
            "bob approved on head",
        )


def pr_info(reviewers, **overrides: Any) -> PRInfo:
    fields: dict[str, Any] = {
        "repo": "o/r",
        "number": 1,
        "title": "t",
        "state": PRState.OPEN,
        "ci_status": CIStatus.GREEN,
        "history": "oHA",
        "created_at": NOW,
        "closed_at": None,
        "last_activity": NOW,
        "author": "octocat",
        "head_sha": HEAD,
        "reviewers": reviewers,
    }
    fields.update(overrides)
    return PRInfo(**fields)


def snapshot_of(*prs: PRInfo, name: str = "s") -> Snapshot:
    return Snapshot(
        kind="pr",
        name=name,
        captured_at="2026-11-05T12:00:00Z",
        scope=SnapshotScope(),
        items=tuple(item_from_pr(p) for p in prs),
    )


class TestSnapshot:
    def test_round_trip_keeps_reviewers(self):
        snap = snapshot_of(pr_info((approved(), state("zed", requested=True))))
        again = Snapshot.from_dict(json.loads(snap.to_json()), "pr", "s")
        assert again.items[0].reviewers == snap.items[0].reviewers
        raw = snap.to_dict()["items"][0]["reviewers"]
        assert raw[0]["login"] == "bob" and raw[0]["on_head"] is True
        assert raw[1]["waiting"] is True

    def test_a_pr_without_reviewers_has_an_empty_list(self):
        row = item_from_pr(pr_info(())).to_dict()
        assert row["reviewers"] == []
        assert item_from_pr(pr_info(None)).to_dict()["reviewers"] == []


def only_delta(prev: PRInfo, curr: PRInfo):
    [delta] = diff_snapshots(snapshot_of(prev), snapshot_of(curr)).deltas
    return delta


class TestDiff:
    def test_review_going_stale_after_a_push_is_the_only_change(self):
        prev = pr_info((approved(),))
        curr = pr_info((approved(on_head=False),), head_sha="f" * 40)
        delta = only_delta(prev, curr)
        assert delta.change.value == "changed"
        assert delta.reviewer_changes == ("bob review now on old head",)
        assert "reviewers" in delta.changed_fields

    def test_unchanged_reviewers_do_not_flag_the_row(self):
        delta = only_delta(pr_info((approved(),)), pr_info((approved(),)))
        assert delta.change.value == "unchanged" and delta.reviewer_changes == ()

    def test_json_lists_transitions_only_when_present(self):
        prev = snapshot_of(pr_info((state(requested=True),)))
        curr = snapshot_of(pr_info((approved(),)))
        data = diff_snapshots(prev, curr).to_dict()
        assert data["deltas"][0]["reviewer_changes"] == ["bob approved on head"]
        assert "reviewer_changes" not in diff_snapshots(prev, prev).to_dict()["deltas"][0]

    def test_table_note_and_legend_name_the_transitions(self):
        prev = snapshot_of(pr_info((approved(),)))
        curr = snapshot_of(pr_info((approved(on_head=False),), head_sha="f" * 40))
        console = Console(width=300, color_system=None, record=True)
        render_diff(diff_snapshots(prev, curr), console=console)
        out = console.export_text()
        assert "bob review now on old head" in out
        assert "Per-reviewer notes" in out


class TestCompactRendering:
    def reviewers(self):
        return (
            approved(login="a"),
            approved(login="b"),
            replace(approved(login="c"), latest_state="CHANGES_REQUESTED"),
            state("d", requested=True),
            approved(OLD, False, login="e", requested=True, requested_at=AFTER_REVIEW),
            approved(OLD, False, login="f"),
            replace(approved(login="g"), latest_state="COMMENTED"),
            replace(approved(login="h"), latest_state="DISMISSED"),
        )

    def test_counts(self):
        assert compact_reviewers(self.reviewers()) == "✓2 ✗1 ~1 ⊘1 •1 ↻1 !1"

    def test_names(self):
        assert named_reviewers(self.reviewers()) == "a✓ b✓ c✗ d• e↻ f! g~ h⊘"

    def test_none_and_empty(self):
        assert compact_reviewers(None) == compact_reviewers(()) == "--"
        assert named_reviewers(None) == named_reviewers(()) == "--"


class FakePRClient:
    prs: list[PRInfo] = []

    def __enter__(self) -> FakePRClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_current_user(self) -> str:
        return "octocat"

    def list_prs_by_author(self, *_: Any, **__: Any) -> PRListResult:
        return PRListResult(prs=list(self.prs))


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    monkeypatch.setattr(board_config, "TKT_HOME", tmp_path)
    monkeypatch.setattr(board_config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(board_config, "CACHE_FILE", tmp_path / "board-cache.db")
    monkeypatch.setattr(FakePRClient, "prs", [])
    monkeypatch.setattr(pr_list, "PRClient", FakePRClient)
    monkeypatch.setattr(pr_list, "_get_repos", lambda *_: None)
    monkeypatch.setattr(pr_list, "console", Console(width=200, color_system=None))
    return FakePRClient


class TestListColumn:
    def prs(self):
        return [pr_info((approved(login="all-hands-bot"), state("bob", requested=True)))]

    def test_default_table_is_unchanged(self, fake_client, capsys):
        fake_client.prs = self.prs()
        assert pr_list.cmd_list() == 0
        with_reviewers = capsys.readouterr().out
        fake_client.prs = [pr_info(None)]
        assert pr_list.cmd_list() == 0
        assert capsys.readouterr().out == with_reviewers
        assert "Reviewers" not in with_reviewers and "✓" not in with_reviewers

    def test_reviewers_flag_adds_counts_and_legend(self, fake_client, capsys):
        fake_client.prs = self.prs()
        assert pr_list.cmd_list(show_reviewers=True) == 0
        out = capsys.readouterr().out
        assert "Reviewers" in out and "✓1 •1" in out
        assert "Reviewers: ✓ approved on head" in out

    def test_names_flag_names_them(self, fake_client, capsys):
        fake_client.prs = self.prs()
        assert pr_list.cmd_list(reviewer_names=True) == 0
        assert "all-hands-bot✓ bob•" in capsys.readouterr().out

    def test_truncated_reviewers_are_marked(self, fake_client, capsys):
        fake_client.prs = [replace(self.prs()[0], reviewers_truncated=True)]
        assert pr_list.cmd_list(show_reviewers=True) == 0
        assert "✓1 •1…" in capsys.readouterr().out

    def test_watch_reports_a_bot_approving(self, fake_client, capsys):
        fake_client.prs = [pr_info((state("all-hands-bot", requested=True),))]
        assert pr_list.cmd_list(watch_name="w") == 0
        capsys.readouterr()
        fake_client.prs = [pr_info((approved(login="all-hands-bot"),))]
        assert pr_list.cmd_list(watch_name="w") == 0
        assert "all-hands-bot approved on head" in capsys.readouterr().out
        assert store.load("pr", "w").items[0].reviewers == (approved(login="all-hands-bot"),)
