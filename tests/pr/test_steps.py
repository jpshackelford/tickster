"""`tkt pr steps`: the Phase A rules, their output, the list column and snapshot diffs."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from src.__main__ import main
from src.board import config as board_config
from src.norms import store as norms_store
from src.norms.model import CI, Actors, Norms, Review
from src.pr.checks import OUTCOME_FAILED, OUTCOME_PASSED, OUTCOME_PENDING, CheckContext, PRChecks
from src.pr.cli import list_cmd as pr_list
from src.pr.cli import steps_cmd
from src.pr.history import process_pr_data
from src.pr.models import CIStatus, PRInfo, PRListResult, PRState
from src.pr.reports import MANUAL_TEST_STEPS
from src.pr.reviewers import ReviewerState
from src.pr.steps import (
    STEP_CI,
    STEP_FINDINGS,
    STEP_NAMES,
    STEP_REREVIEW,
    STEP_REVIEW,
    StepResult,
    StepStatus,
    evaluate_steps,
    needs_check_details,
    step_changes,
    step_statuses,
    steps_mark,
)
from src.snapshot import store
from src.snapshot.convert import item_from_pr, snapshot_from_prs
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import ItemSnapshot, Snapshot, SnapshotScope
from src.snapshot.render import render_diff

FIXTURES = Path(__file__).parent / "fixtures"
OLD = "0945b15" + "0" * 33
HEAD = "e66822d" + "0" * 33
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
AGENT_NORMS = Norms(actors=Actors(agent_logins=("all-hands-bot",)))

NEEDED, WAITING, DONE = StepStatus.NEEDED, StepStatus.WAITING, StepStatus.DONE
NA, UNKNOWN = StepStatus.NOT_APPLICABLE, StepStatus.UNKNOWN


def reviewer(
    login: str = "alice",
    *,
    actor_class: str | None = "human",
    state: str | None = None,
    commit: str | None = None,
    requested: bool = False,
    requested_at: str | None = None,
    submitted_at: str | None = None,
) -> ReviewerState:
    return ReviewerState(
        login=login,
        actor_class=actor_class,
        requested=requested,
        requested_by="author" if requested else None,
        requested_at=requested_at,
        latest_state=state,
        reviewed_commit=commit,
        on_head=commit == HEAD,
        submitted_at=submitted_at or ("2026-11-05T02:00:00Z" if state else None),
    )


def reviewed(login="alice", state="APPROVED", commit=HEAD, **kw) -> ReviewerState:
    return reviewer(login, state=state, commit=commit, **kw)


def asked(login="alice", **kw) -> ReviewerState:
    return reviewer(login, requested=True, **kw)


def pr_info(reviewers: tuple[ReviewerState, ...] | None = (), **overrides: Any) -> PRInfo:
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
        "mergeable": "MERGEABLE",
        "checks_state": "SUCCESS",
        "reviewers": reviewers,
    }
    fields.update(overrides)
    return PRInfo(**fields)


def step(results: tuple[StepResult, ...], name: str) -> StepResult:
    return next(r for r in results if r.step == name)


def status_of(name: str, pr: PRInfo, norms: Norms | None = None, checks=None) -> StepStatus:
    return step(evaluate_steps(pr, norms, checks), name).status


class TestReviewThePR:
    def test_draft_is_not_applicable(self):
        assert status_of(STEP_REVIEW, pr_info(is_draft=True)) is NA

    def test_reviewers_not_fetched_is_unknown(self):
        assert status_of(STEP_REVIEW, pr_info(None)) is UNKNOWN

    def test_nobody_reviewed_or_requested_is_needed(self):
        result = step(evaluate_steps(pr_info(()), None), STEP_REVIEW)
        assert result.status is NEEDED
        assert [e.text for e in result.evidence] == [
            "no counted reviewer has reviewed",
            "none requested",
        ]

    def test_requested_and_not_yet_reviewed_is_waiting(self):
        result = step(evaluate_steps(pr_info((asked("bob"),)), None), STEP_REVIEW)
        assert result.status is WAITING
        assert result.evidence[0].text == "bob requested by author"

    def test_any_review_state_is_done(self):
        for state in ("APPROVED", "COMMENTED", "CHANGES_REQUESTED"):
            assert status_of(STEP_REVIEW, pr_info((reviewed(state=state),))) is DONE

    def test_a_review_beats_a_pending_request_on_someone_else(self):
        assert status_of(STEP_REVIEW, pr_info((reviewed(), asked("bob")))) is DONE

    def test_dismissed_review_does_not_count(self):
        assert status_of(STEP_REVIEW, pr_info((reviewed(state="DISMISSED"),))) is NEEDED

    def test_default_counts_humans_only_when_no_agents_are_known(self):
        copilot = reviewed("copilot[bot]", actor_class="bot")
        assert status_of(STEP_REVIEW, pr_info((copilot,))) is NEEDED
        assert status_of(STEP_REVIEW, pr_info((reviewed("bob"),))) is DONE

    def test_agents_count_by_default_once_known(self):
        agent = reviewed("all-hands-bot", actor_class="agent")
        assert status_of(STEP_REVIEW, pr_info((agent,)), AGENT_NORMS) is DONE

    def test_humans_only_ignores_an_agent(self):
        norms = Norms(review=Review(count_reviews_from=("humans",)))
        agent = reviewed("all-hands-bot", actor_class="agent")
        assert status_of(STEP_REVIEW, pr_info((agent,)), norms) is NEEDED

    def test_bots_can_be_counted(self):
        norms = Norms(review=Review(count_reviews_from=("bots",)))
        assert status_of(STEP_REVIEW, pr_info((reviewed("x[bot]", actor_class="bot"),)), norms) is (
            DONE
        )

    def test_a_team_counts_as_humans(self):
        team = asked("team:core", actor_class=None)
        assert status_of(STEP_REVIEW, pr_info((team,))) is WAITING


class TestFixCI:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("SUCCESS", DONE),
            ("PENDING", WAITING),
            ("EXPECTED", WAITING),
            ("FAILURE", NEEDED),
            ("ERROR", NEEDED),
            ("MYSTERY", UNKNOWN),
        ],
    )
    def test_rollup_state(self, state, expected):
        assert status_of(STEP_CI, pr_info(checks_state=state)) is expected

    def test_no_checks_is_not_applicable(self):
        assert status_of(STEP_CI, pr_info(checks_state=None)) is NA

    def test_no_checks_while_mergeability_is_unknown_is_unknown(self):
        assert status_of(STEP_CI, pr_info(checks_state=None, mergeable="UNKNOWN")) is UNKNOWN

    def test_a_conflict_does_not_hide_the_rollup(self):
        pr = pr_info(checks_state="FAILURE", ci_status=CIStatus.CONFLICT, mergeable="CONFLICTING")
        assert status_of(STEP_CI, pr) is NEEDED

    def test_failure_evidence_names_the_rollup_and_head(self):
        result = step(evaluate_steps(pr_info(checks_state="FAILURE"), None), STEP_CI)
        assert result.evidence[0].text == "check rollup FAILURE on head e66822d"


class TestFixCIWithIgnoredChecks:
    norms = Norms(ci=CI(ignore_checks=("codecov/*",)))

    def ci(self, state, *checks: CheckContext):
        return status_of(STEP_CI, pr_info(checks_state=state), self.norms, list(checks))

    def test_failure_only_in_an_ignored_check_is_done(self):
        passed = CheckContext("test", OUTCOME_PASSED)
        assert self.ci("FAILURE", passed, CheckContext("codecov/patch", OUTCOME_FAILED)) is DONE

    def test_a_failure_elsewhere_is_still_needed(self):
        result = step(
            evaluate_steps(
                pr_info(checks_state="FAILURE"),
                self.norms,
                [CheckContext("test", OUTCOME_FAILED), CheckContext("codecov/patch", "failed")],
            ),
            STEP_CI,
        )
        assert result.status is NEEDED
        assert [e.ref for e in result.evidence] == ["test"]

    def test_pending_only_in_an_ignored_check_is_done(self):
        passed = CheckContext("test", OUTCOME_PASSED)
        assert self.ci("PENDING", passed, CheckContext("codecov/patch", OUTCOME_PENDING)) is DONE

    def test_pending_elsewhere_is_waiting(self):
        assert self.ci("PENDING", CheckContext("test", OUTCOME_PENDING)) is WAITING

    def test_nothing_left_after_ignoring_is_not_applicable(self):
        assert self.ci("FAILURE", CheckContext("codecov/project", OUTCOME_FAILED)) is NA

    def test_green_rollup_needs_no_details(self):
        assert not needs_check_details(pr_info(checks_state="SUCCESS"), self.norms)
        assert self.ci("SUCCESS") is DONE

    def test_details_are_only_needed_when_something_is_ignored(self):
        assert needs_check_details(pr_info(checks_state="FAILURE"), self.norms)
        assert needs_check_details(pr_info(checks_state="PENDING"), self.norms)
        assert not needs_check_details(pr_info(checks_state="FAILURE"), Norms())
        assert not needs_check_details(pr_info(checks_state="FAILURE"), None)

    def test_without_the_details_the_rollup_decides(self):
        pr = pr_info(checks_state="FAILURE")
        assert status_of(STEP_CI, pr, self.norms, None) is NEEDED


class TestAddressFindings:
    def test_unresolved_threads_are_needed(self):
        pr = pr_info((reviewed(state="COMMENTED"),), unresolved_thread_count=2)
        result = step(evaluate_steps(pr, None), STEP_FINDINGS)
        assert result.status is NEEDED
        assert result.evidence[0].text == "2 unresolved review threads"

    def test_one_thread_is_singular(self):
        pr = pr_info((reviewed(),), unresolved_thread_count=1)
        assert step(evaluate_steps(pr, None), STEP_FINDINGS).evidence[0].text == (
            "1 unresolved review thread"
        )

    def test_changes_requested_is_needed_even_with_no_threads(self):
        pr = pr_info((reviewed(state="CHANGES_REQUESTED"),))
        result = step(evaluate_steps(pr, None), STEP_FINDINGS)
        assert result.status is NEEDED
        assert result.evidence[0].text == "alice CHANGES_REQUESTED on e66822d"

    def test_changes_requested_by_an_uncounted_reviewer_is_not(self):
        norms = Norms(review=Review(count_reviews_from=("humans",)))
        agent = reviewed("all-hands-bot", state="CHANGES_REQUESTED", actor_class="agent")
        assert status_of(STEP_FINDINGS, pr_info((agent,)), norms) is DONE

    def test_reviewed_with_nothing_open_is_done(self):
        assert status_of(STEP_FINDINGS, pr_info((reviewed(),))) is DONE

    def test_no_reviews_is_not_applicable(self):
        assert status_of(STEP_FINDINGS, pr_info(())) is NA
        assert status_of(STEP_FINDINGS, pr_info((asked(),))) is NA

    def test_reviewers_not_fetched_is_unknown(self):
        assert status_of(STEP_FINDINGS, pr_info(None)) is UNKNOWN


class TestRequestReReview:
    def test_review_on_an_older_head_with_no_request_is_needed(self):
        pr = pr_info((reviewed(commit=OLD, state="COMMENTED"),))
        result = step(evaluate_steps(pr, None), STEP_REREVIEW)
        assert result.status is NEEDED
        assert [e.text for e in result.evidence] == [
            "alice COMMENTED on 0945b15",
            "head is e66822d",
            "no pending request",
        ]

    def test_a_pending_rerequest_is_waiting(self):
        old = reviewed(
            commit=OLD,
            requested=True,
            requested_at="2026-11-05T03:00:00Z",
            submitted_at="2026-11-05T02:00:00Z",
        )
        result = step(evaluate_steps(pr_info((old,)), None), STEP_REREVIEW)
        assert result.status is WAITING
        assert result.evidence[0].text.startswith("alice requested by author")

    def test_a_rerequest_on_a_reviewer_already_on_head_is_waiting(self):
        again = reviewed(
            requested=True,
            requested_at="2026-11-05T03:00:00Z",
            submitted_at="2026-11-05T02:00:00Z",
        )
        assert status_of(STEP_REREVIEW, pr_info((again,))) is WAITING

    def test_a_rerequest_label_counts_as_a_request(self):
        norms = Norms(review=Review(rerequest_labels=("review-this",)))
        pr = pr_info((reviewed(commit=OLD),), labels=("review-this",))
        result = step(evaluate_steps(pr, norms), STEP_REREVIEW)
        assert result.status is WAITING
        assert result.evidence[0].kind == "label"

    def test_a_label_not_in_the_settings_is_ignored(self):
        pr = pr_info((reviewed(commit=OLD),), labels=("review-this",))
        assert status_of(STEP_REREVIEW, pr) is NEEDED

    def test_all_reviews_on_head_is_done(self):
        pr = pr_info((reviewed("a"), reviewed("b", state="COMMENTED")))
        assert status_of(STEP_REREVIEW, pr) is DONE

    def test_one_stale_reviewer_among_current_ones_is_needed(self):
        pr = pr_info((reviewed("a"), reviewed("b", commit=OLD)))
        result = step(evaluate_steps(pr, None), STEP_REREVIEW)
        assert result.status is NEEDED
        assert result.evidence[0].text.startswith("b ")

    def test_needed_beats_waiting_when_one_reviewer_is_unrequested(self):
        pending = reviewed(
            "a",
            commit=OLD,
            requested=True,
            requested_at="2026-11-05T03:00:00Z",
            submitted_at="2026-11-05T02:00:00Z",
        )
        pr = pr_info((pending, reviewed("b", commit=OLD)))
        assert status_of(STEP_REREVIEW, pr) is NEEDED

    def test_no_reviews_is_not_applicable(self):
        assert status_of(STEP_REREVIEW, pr_info(())) is NA
        assert status_of(STEP_REREVIEW, pr_info((asked(),))) is NA

    def test_an_uncounted_reviewer_does_not_need_a_rereview(self):
        pr = pr_info((reviewed("x[bot]", commit=OLD, actor_class="bot"),))
        assert status_of(STEP_REREVIEW, pr) is NA

    def test_unknown_head_is_unknown(self):
        assert status_of(STEP_REREVIEW, pr_info((reviewed(),), head_sha=None)) is UNKNOWN

    def test_reviewers_not_fetched_is_unknown(self):
        assert status_of(STEP_REREVIEW, pr_info(None)) is UNKNOWN


class TestClosedPRs:
    @pytest.mark.parametrize("state", [PRState.MERGED, PRState.CLOSED])
    def test_every_step_is_not_applicable(self, state):
        results = evaluate_steps(pr_info((reviewed(commit=OLD),), state=state), None)
        assert [r.status for r in results] == [NA] * len(STEP_NAMES)
        assert results[0].evidence[0].text == f"PR is {state.value}"


class TestResults:
    def test_steps_come_in_a_fixed_order(self):
        assert tuple(r.step for r in evaluate_steps(pr_info(()), None)) == STEP_NAMES

    def test_line_shows_status_then_evidence(self):
        pr = pr_info((reviewed(commit=OLD, state="COMMENTED", login="enyst"),))
        line = step(evaluate_steps(pr, None), STEP_REREVIEW).line()
        assert line == (
            "request re-review: needed — enyst COMMENTED on 0945b15, "
            "head is e66822d, no pending request"
        )

    def test_to_dict_has_step_status_and_evidence(self):
        data = step(evaluate_steps(pr_info(()), None), STEP_REVIEW).to_dict()
        assert set(data) == {"step", "status", "evidence"}
        assert data["status"] == "needed"
        assert data["evidence"][0] == {
            "kind": "review",
            "text": "no counted reviewer has reviewed",
        }

    def test_explain_is_only_included_on_request(self):
        result = step(evaluate_steps(pr_info(()), None), STEP_REVIEW)
        assert "explain" not in result.to_dict()
        assert result.to_dict(explain=True)["explain"] == list(result.explain)

    def test_evidence_carries_its_reference(self):
        pr = pr_info((reviewed(commit=OLD),))
        evidence = step(evaluate_steps(pr, None), STEP_REREVIEW).evidence
        assert [e.ref for e in evidence] == [OLD, HEAD, None]
        assert evidence[0].to_dict()["ref"] == OLD

    def test_explain_names_the_settings_and_facts(self):
        pr = pr_info((reviewed(commit=OLD),))
        why = "\n".join(step(evaluate_steps(pr, None), STEP_REREVIEW).explain)
        assert "[review] count_reviews_from = [humans, agents] (default (no norms file))" in why
        assert "[review] rerequest_labels" in why
        assert "head is e66822d" in why
        assert "alice: reviewed 0945b15, not on head, no request pending" in why

    def test_explain_says_when_settings_come_from_a_norms_file(self):
        why = "\n".join(step(evaluate_steps(pr_info(()), Norms()), STEP_REVIEW).explain)
        assert "from .agents/tickster.toml" in why


class TestMarks:
    def results(self, *statuses: StepStatus):
        return tuple(StepResult(n, s) for n, s in zip(STEP_NAMES, statuses, strict=True))

    def test_upper_needed_lower_waiting_dot_otherwise(self):
        marks = steps_mark(self.results(NEEDED, WAITING, DONE, NA, NEEDED, WAITING, DONE))
        assert marks == "Rc..Mt."

    def test_unknown_and_not_configured(self):
        marks = steps_mark(
            self.results(UNKNOWN, StepStatus.NOT_CONFIGURED, NEEDED, WAITING, NEEDED, NA, NEEDED)
        )
        assert marks == "?-FaM.X"

    def test_a_report_beyond_manual_test_has_no_column(self):
        extra = (*self.results(*[DONE] * len(STEP_NAMES)), StepResult("docs review", NEEDED))
        assert steps_mark(extra) == "......."

    def test_step_changes_name_old_and_new(self):
        prev = {STEP_REREVIEW: "done", STEP_CI: "needed", STEP_REVIEW: "done"}
        curr = {STEP_REREVIEW: "needed", STEP_CI: "needed", STEP_REVIEW: "done"}
        assert step_changes(prev, curr) == ("request re-review: done → needed",)

    def test_step_changes_follow_step_order_and_skip_unshared_steps(self):
        prev = {STEP_REREVIEW: "done", STEP_REVIEW: "needed"}
        curr = {STEP_REREVIEW: "waiting", STEP_REVIEW: "done", STEP_CI: "done"}
        assert step_changes(prev, curr) == (
            "review the PR: needed → done",
            "request re-review: done → waiting",
        )


def recorded(name: str, norms: Norms | None = None) -> tuple[StepResult, ...]:
    norms_store.set_loader(lambda _repo: norms)
    pr = process_pr_data(json.loads((FIXTURES / name).read_text()), "jpshackelford")
    return evaluate_steps(pr, norms)


class TestRecordedFixtures:
    def test_sdk_6338_review_on_an_older_head_needs_a_rerequest(self):
        results = recorded("steps_sdk_6338_stale_review.json")
        result = step(results, STEP_REREVIEW)
        assert result.status is NEEDED
        assert [e.text for e in result.evidence] == [
            "enyst COMMENTED on 0945b15",
            "head is e66822d",
            "no pending request",
        ]
        assert step(results, STEP_REVIEW).status is DONE
        assert step(results, STEP_CI).status is DONE
        assert step(results, STEP_FINDINGS).status is DONE

    def test_sdk_6480_bot_requested_is_waiting_then_approving_is_done(self):
        waiting = recorded("steps_sdk_6480_bot_requested.json", AGENT_NORMS)
        review = step(waiting, STEP_REVIEW)
        assert review.status is WAITING
        assert review.evidence[0].text.startswith("all-hands-bot requested by jpshackelford")
        assert step(waiting, STEP_REREVIEW).status is NA

        approved = recorded("steps_sdk_6480_bot_approved.json", AGENT_NORMS)
        assert step(approved, STEP_REVIEW).status is DONE
        assert step(approved, STEP_REVIEW).evidence[0].text == "all-hands-bot APPROVED on e66822d"
        assert step(approved, STEP_REREVIEW).status is DONE

    def test_the_bot_is_an_agent_only_through_the_norms(self):
        pr = process_pr_data(
            json.loads((FIXTURES / "steps_sdk_6480_bot_requested.json").read_text()), "jp"
        )
        assert pr.reviewers is not None and pr.reviewers[0].actor_class == "human"
        norms_store.set_loader(lambda _repo: AGENT_NORMS)
        pr = process_pr_data(
            json.loads((FIXTURES / "steps_sdk_6480_bot_requested.json").read_text()), "jp"
        )
        assert pr.reviewers is not None and pr.reviewers[0].actor_class == "agent"
        humans_only = Norms(
            actors=AGENT_NORMS.actors, review=Review(count_reviews_from=("humans",))
        )
        assert status_of(STEP_REVIEW, pr, humans_only) is NEEDED

    def test_labels_and_rollup_state_are_read_from_the_pr(self):
        data = json.loads((FIXTURES / "steps_sdk_6338_stale_review.json").read_text())
        data["labels"] = {"nodes": [{"name": "review-this"}, None]}
        data["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["state"] = "FAILURE"
        pr = process_pr_data(data, "jp")
        assert (pr.labels, pr.checks_state) == (("review-this",), "FAILURE")

    def test_a_pr_without_labels_or_checks(self):
        data = json.loads((FIXTURES / "steps_sdk_6338_stale_review.json").read_text())
        del data["labels"]
        data["commits"] = {"nodes": []}
        pr = process_pr_data(data, "jp")
        assert (pr.labels, pr.checks_state) == ((), None)


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

    def get_prs_by_ref(self, refs: list[str]) -> PRListResult:
        wanted = {r.lower() for r in refs}
        return PRListResult(prs=[p for p in self.prs if f"{p.repo}#{p.number}".lower() in wanted])


class FakeChecksClient:
    contexts: list[CheckContext] = []
    calls: list[tuple[str, int]] = []
    closed = False

    def get_pr_checks(self, repo: str, number: int) -> PRChecks:
        self.calls.append((repo, number))
        return PRChecks(repo, number, CIStatus.RED, contexts=list(self.contexts))

    def close(self) -> None:
        FakeChecksClient.closed = True


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    monkeypatch.setattr(board_config, "TKT_HOME", tmp_path)
    monkeypatch.setattr(board_config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(board_config, "CACHE_FILE", tmp_path / "board-cache.db")
    monkeypatch.setattr(FakePRClient, "prs", [])
    monkeypatch.setattr(FakeChecksClient, "contexts", [])
    monkeypatch.setattr(FakeChecksClient, "calls", [])
    monkeypatch.setattr(FakeChecksClient, "closed", False)
    monkeypatch.setattr(steps_cmd, "PRClient", FakePRClient)
    monkeypatch.setattr(steps_cmd, "ChecksClient", FakeChecksClient)
    monkeypatch.setattr(pr_list, "PRClient", FakePRClient)
    monkeypatch.setattr(pr_list, "_get_repos", lambda *_: None)
    monkeypatch.setattr(pr_list, "console", Console(width=200, color_system=None))
    return FakePRClient


def stale_pr(**overrides: Any) -> PRInfo:
    return pr_info((reviewed("enyst", "COMMENTED", OLD),), **overrides)


class TestCmdSteps:
    def test_text_has_one_line_per_step(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert steps_cmd.cmd_steps(refs=["o/r#1"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "o/r#1"
        assert [line.split(":")[0].strip() for line in lines[1:]] == list(STEP_NAMES)
        assert lines[4].strip() == (
            "request re-review: needed — enyst COMMENTED on 0945b15, "
            "head is e66822d, no pending request"
        )

    def test_json_is_the_only_thing_on_stdout(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert steps_cmd.cmd_steps(refs=["o/r#1"], output_format="json") == 0
        captured = capsys.readouterr()
        [pr] = json.loads(captured.out)
        assert captured.err == ""
        assert pr["pr"] == "o/r#1"
        assert [s["step"] for s in pr["steps"]] == list(STEP_NAMES)
        rereview = pr["steps"][3]
        assert rereview["status"] == "needed"
        assert {e["ref"] for e in rereview["evidence"] if "ref" in e} == {OLD, HEAD}
        assert "explain" not in rereview

    def test_norms_warnings_stay_off_stdout(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]

        def warn_loader(_repo: str) -> None:
            norms_store._warn("bad norms")

        norms_store.set_loader(warn_loader)
        assert steps_cmd.cmd_steps(refs=["o/r#1"], output_format="json") == 0
        captured = capsys.readouterr()
        json.loads(captured.out)
        assert "bad norms" in captured.err

    def test_explain_names_the_settings_and_facts_for_each_rule(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert steps_cmd.cmd_steps(refs=["o/r#1"], explain=True) == 0
        out = capsys.readouterr().out
        assert out.count("why:") >= len(STEP_NAMES) * 2
        assert "[review] count_reviews_from = [humans, agents]" in out
        assert "[ci] ignore_checks" in out
        assert "[review] rerequest_labels" in out
        assert "check rollup of head e66822d is SUCCESS" in out
        assert "unresolved review threads: 0" in out

    def test_json_explain(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert steps_cmd.cmd_steps(refs=["o/r#1"], output_format="json", explain=True) == 0
        [pr] = json.loads(capsys.readouterr().out)
        assert all(s["explain"] for s in pr["steps"])

    def test_several_prs_in_the_order_asked(self, fake_client, capsys):
        fake_client.prs = [pr_info(number=1), pr_info(number=2)]
        refs = ["https://github.com/o/r/pull/2", "o/r#1"]
        assert steps_cmd.cmd_steps(refs=refs, output_format="json") == 0
        assert [p["pr"] for p in json.loads(capsys.readouterr().out)] == ["o/r#2", "o/r#1"]

    @pytest.mark.usefixtures("fake_client")
    def test_unknown_pr_is_an_error_on_stderr(self, capsys):
        assert steps_cmd.cmd_steps(refs=["o/r#9"], output_format="json") == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "PR not found: o/r#9" in captured.err

    @pytest.mark.usefixtures("fake_client")
    def test_bad_ref_is_an_error(self, capsys):
        assert steps_cmd.cmd_steps(refs=["nonsense"]) == 1
        assert "Invalid PR reference" in capsys.readouterr().err

    @pytest.mark.usefixtures("fake_client")
    def test_ignored_checks_are_fetched_only_when_they_matter(self):
        norms_store.set_loader(lambda _repo: Norms(ci=CI(ignore_checks=("codecov/*",))))
        FakeChecksClient.contexts = [
            CheckContext("test", OUTCOME_PASSED),
            CheckContext("codecov/patch", OUTCOME_FAILED),
        ]
        steps = steps_cmd.collect_steps(
            [pr_info(number=1, checks_state="FAILURE"), pr_info(number=2, checks_state="SUCCESS")]
        )
        assert step(steps["o/r#1"], STEP_CI).status is DONE
        assert step(steps["o/r#2"], STEP_CI).status is DONE
        assert FakeChecksClient.calls == [("o/r", 1)]
        assert FakeChecksClient.closed

    @pytest.mark.usefixtures("fake_client")
    def test_no_checks_client_without_ignored_checks(self):
        steps_cmd.collect_steps([pr_info(checks_state="FAILURE")])
        assert FakeChecksClient.calls == [] and not FakeChecksClient.closed

    def test_the_cli_routes_to_the_command(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert main(["pr", "steps", "o/r#1", "--format", "json"]) == 0
        assert json.loads(capsys.readouterr().out)[0]["pr"] == "o/r#1"

    def test_the_cli_passes_the_list_flag_through(self, fake_client, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        fake_client.prs = [stale_pr()]
        assert main(["pr", "list", "--steps"]) == 0
        assert "...A" in capsys.readouterr().out


class TestListColumn:
    def test_output_is_unchanged_without_steps(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list() == 0
        out = capsys.readouterr().out
        assert "Steps" not in out and "Steps:" not in out
        fake_client.prs = [pr_info(None)]
        assert pr_list.cmd_list() == 0
        assert capsys.readouterr().out == out

    def test_steps_flag_adds_a_column_and_the_legend(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(show_steps=True) == 0
        out = capsys.readouterr().out
        assert "Steps" in out
        assert "...A" in out
        assert "Steps: r review, c fix CI, f review findings, a re-review, " in out
        assert "m manual test, t test findings, x retest." in out

    def test_a_pr_that_needs_everything_it_can(self, fake_client, capsys):
        fake_client.prs = [
            pr_info(
                (reviewed("a", "CHANGES_REQUESTED", OLD),),
                checks_state="FAILURE",
                unresolved_thread_count=1,
            )
        ]
        assert pr_list.cmd_list(show_steps=True) == 0
        assert ".CFA" in capsys.readouterr().out

    def test_the_table_stays_within_80_columns_by_default(self, fake_client, capsys, monkeypatch):
        monkeypatch.setattr(pr_list, "console", Console(width=80, color_system=None))
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list() == 0
        lines = capsys.readouterr().out.splitlines()
        assert all(
            len(line) <= 80 for line in lines if not line.startswith(("Filters:", "History:"))
        )


def snapshot_of(*prs: PRInfo, with_steps: bool = True) -> Snapshot:
    steps = {f"{p.repo}#{p.number}": evaluate_steps(p, None) for p in prs}
    return snapshot_from_prs(
        list(prs), scope=SnapshotScope(), name="s", steps=steps if with_steps else None
    )


def only_delta(prev: Snapshot, curr: Snapshot):
    [delta] = diff_snapshots(prev, curr).deltas
    return delta


class TestSnapshots:
    def test_statuses_are_recorded_and_round_trip(self):
        snap = snapshot_of(stale_pr())
        assert snap.items[0].steps == {
            STEP_REVIEW: "done",
            STEP_CI: "done",
            STEP_FINDINGS: "done",
            STEP_REREVIEW: "needed",
            **dict.fromkeys(MANUAL_TEST_STEPS, "not configured"),
        }
        again = Snapshot.from_dict(json.loads(json.dumps(snap.to_dict())))
        assert again.items[0].steps == snap.items[0].steps

    def test_not_recorded_stays_out_of_the_json(self):
        item = item_from_pr(stale_pr())
        assert item.steps is None and "steps" not in item.to_dict()
        assert ItemSnapshot.from_dict(item.to_dict()).steps is None

    def test_item_records_the_given_results(self):
        results = evaluate_steps(stale_pr(), None)
        assert item_from_pr(stale_pr(), results).steps == step_statuses(results)

    def test_diff_reports_the_transition(self):
        done = pr_info((reviewed("enyst", "COMMENTED", HEAD),))
        delta = only_delta(snapshot_of(done), snapshot_of(stale_pr()))
        assert delta.kind.value == "changed"
        assert delta.step_changes == ("request re-review: done → needed",)
        assert "steps" in delta.changed_fields

    def test_unchanged_statuses_do_not_flag_the_row(self):
        delta = only_delta(snapshot_of(stale_pr()), snapshot_of(stale_pr()))
        assert delta.kind.value == "unchanged" and delta.step_changes == ()

    def test_a_snapshot_without_steps_is_not_compared(self):
        delta = only_delta(snapshot_of(stale_pr(), with_steps=False), snapshot_of(stale_pr()))
        assert delta.kind.value == "unchanged"

    def test_json_lists_transitions_only_when_present(self):
        done = pr_info((reviewed("enyst", "COMMENTED", HEAD),))
        prev, curr = snapshot_of(done), snapshot_of(stale_pr())
        data = diff_snapshots(prev, curr).to_dict()
        assert data["deltas"][0]["step_changes"] == ["request re-review: done → needed"]
        assert "step_changes" not in diff_snapshots(prev, prev).to_dict()["deltas"][0]

    def test_table_note_names_the_transition(self):
        done = pr_info((reviewed("enyst", "COMMENTED", HEAD),))
        console = Console(width=300, color_system=None, record=True)
        render_diff(diff_snapshots(snapshot_of(done), snapshot_of(stale_pr())), console=console)
        out = console.export_text()
        assert "request re-review: done → needed" in out
        assert "Step notes" in out

    def test_watch_with_steps_reports_a_review_going_stale(self, fake_client, capsys):
        fake_client.prs = [pr_info((reviewed("enyst", "COMMENTED", HEAD),))]
        assert pr_list.cmd_list(watch_name="w", show_steps=True) == 0
        capsys.readouterr()
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(watch_name="w", show_steps=True) == 0
        assert "request re-review: done → needed" in capsys.readouterr().out
        assert store.load("pr", "w").items[0].steps[STEP_REREVIEW] == "needed"

    def test_watch_without_steps_still_records_the_statuses(self, fake_client):
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(watch_name="w") == 0
        assert store.load("pr", "w").items[0].steps[STEP_REREVIEW] == "needed"

    def test_snapshot_without_steps_records_the_statuses(self, fake_client):
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(snapshot_name="s") == 0
        assert store.load("pr", "s").items[0].steps[STEP_REREVIEW] == "needed"


class TestStepsAlwaysRecorded:
    """`--steps` is only the table column; snapshots and JSON always carry the statuses."""

    def test_json_has_steps_for_every_item_without_steps_flag(self, fake_client, capsys):
        fake_client.prs = [stale_pr(), pr_info(number=2)]
        assert pr_list.cmd_list(output_format="json") == 0
        items = json.loads(capsys.readouterr().out)["items"]
        assert [it["key"] for it in items] == ["o/r#1", "o/r#2"]
        assert items[0]["steps"][STEP_REREVIEW] == "needed"
        assert all(set(it["steps"]) == {*STEP_NAMES, *MANUAL_TEST_STEPS} for it in items)

    def test_json_keeps_stdout_clean_and_hides_the_column(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(output_format="json") == 0
        captured = capsys.readouterr()
        json.loads(captured.out)
        assert "Steps:" not in captured.out and captured.err == ""

    def test_watch_json_records_the_statuses_in_the_saved_snapshot(self, fake_client, capsys):
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(watch_name="w", output_format="json") == 0
        capsys.readouterr()
        assert store.load("pr", "w").items[0].steps[STEP_REREVIEW] == "needed"

    def test_a_step_move_shows_in_watch_json_without_steps_flag(self, fake_client, capsys):
        fake_client.prs = [pr_info((reviewed("enyst", "COMMENTED", HEAD),))]
        assert pr_list.cmd_list(watch_name="w", output_format="json") == 0
        capsys.readouterr()
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(watch_name="w", output_format="json") == 0
        [delta] = [
            d for d in json.loads(capsys.readouterr().out)["deltas"] if d["kind"] == "changed"
        ]
        assert delta["step_changes"] == ["request re-review: done → needed"]
        assert "steps" in delta["changed_fields"]

    def test_watch_table_without_steps_ignores_a_step_move(self, fake_client, capsys):
        fake_client.prs = [pr_info(checks_state="SUCCESS")]
        assert pr_list.cmd_list(watch_name="w") == 0
        capsys.readouterr()
        fake_client.prs = [pr_info(checks_state="FAILURE")]
        assert pr_list.cmd_list(watch_name="w") == 0
        out = capsys.readouterr().out
        assert "+0 new, *0 changed, -0 gone, 1 unchanged" in out
        assert "fix CI" not in out
        assert store.load("pr", "w").items[0].steps[STEP_CI] == "needed"

    def test_watch_table_with_steps_still_reports_the_move(self, fake_client, capsys):
        fake_client.prs = [pr_info(checks_state="SUCCESS")]
        assert pr_list.cmd_list(watch_name="w", show_steps=True) == 0
        capsys.readouterr()
        fake_client.prs = [pr_info(checks_state="FAILURE")]
        assert pr_list.cmd_list(watch_name="w", show_steps=True) == 0
        out = capsys.readouterr().out
        assert "*1 changed" in out and "fix CI: done → needed" in out

    def test_a_baseline_without_steps_is_not_compared(self, fake_client, capsys):
        store.save(snapshot_of(stale_pr(), with_steps=False))
        fake_client.prs = [stale_pr()]
        assert pr_list.cmd_list(diff_name="s", output_format="json") == 0
        [delta] = json.loads(capsys.readouterr().out)["deltas"]
        assert delta["kind"] == "unchanged"

    def test_the_cli_help_calls_steps_the_table_column(self, capsys):
        with pytest.raises(SystemExit):
            main(["pr", "list", "--help"])
        help_text = " ".join(capsys.readouterr().out.split())
        assert "Only the table column" in help_text
        assert "Snapshots record the statuses" not in help_text


class TestStepCalls:
    @pytest.fixture
    def ignoring_codecov(self):
        norms_store.set_loader(lambda _repo: Norms(ci=CI(ignore_checks=("codecov/*",))))
        FakeChecksClient.contexts = [CheckContext("test", OUTCOME_PASSED)]

    @pytest.mark.usefixtures("ignoring_codecov")
    def test_plain_table_makes_no_step_calls(self, fake_client, capsys):
        fake_client.prs = [pr_info(checks_state="FAILURE")]
        assert pr_list.cmd_list() == 0
        assert FakeChecksClient.calls == []
        assert "Steps" not in capsys.readouterr().out

    @pytest.mark.usefixtures("ignoring_codecov")
    @pytest.mark.parametrize(
        "flags",
        [
            {"output_format": "json"},
            {"snapshot_name": "s"},
            {"watch_name": "s"},
            {"diff_name": "s"},
        ],
    )
    def test_snapshot_diff_and_json_evaluate_the_steps(self, fake_client, flags):
        store.save(snapshot_of(pr_info(), with_steps=False))
        fake_client.prs = [pr_info(checks_state="FAILURE")]
        assert pr_list.cmd_list(**flags) == 0
        assert FakeChecksClient.calls == [("o/r", 1)]

    def test_json_without_norms_makes_no_extra_calls(self, fake_client, monkeypatch):
        def forbidden(*_args: Any, **_kw: Any) -> None:
            raise AssertionError("a repo with no norms needs no extra GitHub call")

        monkeypatch.setattr(steps_cmd, "ChangesClient", forbidden)
        fake_client.prs = [stale_pr(checks_state="FAILURE"), pr_info(number=2)]
        assert pr_list.cmd_list(output_format="json") == 0
        assert FakeChecksClient.calls == []
