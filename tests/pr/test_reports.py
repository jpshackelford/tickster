"""`tkt pr steps`, Phase B: the report-based steps, over recorded public PR timelines.

The timelines are jpshackelford/tickster#61 and #62, recorded through the real PR
query (comment bodies cut to 300 characters), with the compare responses of the
ranges the tests ask about. ``pr_as_of`` replays a timeline up to a moment, so the PR
has the head and the comments it had then. Where the real history has no case (an
impact line, a failing report) a synthetic comment is added and named as one.
"""

from __future__ import annotations

import copy
import io
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console

from src.__main__ import main
from src.actors import ActorClass
from src.board import config as board_config
from src.board.github_api import GitHubClient
from src.norms import store as norms_store
from src.norms.model import Norms
from src.norms.schema import parse_norms
from src.pr.changes import REASON_ONLY_MERGES, ChangedFile, ChangesClient, PRChanges
from src.pr.cli import changes_cmd, steps_cmd
from src.pr.cli import list_cmd as pr_list
from src.pr.history import process_pr_data
from src.pr.models import PRInfo, PRListResult, PRState
from src.pr.reports import (
    ReportFacts,
    all_step_names,
    needs_pr_files,
    step_names,
    tested_commits,
)
from src.pr.steps import (
    STEP_NAMES,
    StepResult,
    StepStatus,
    evaluate_steps,
    step_changes,
    step_names_for,
    steps_mark,
)

FIXTURES = Path(__file__).parent / "fixtures"
REF_USER = "jpshackelford"

NEEDED, DONE, NA = StepStatus.NEEDED, StepStatus.DONE, StepStatus.NOT_APPLICABLE
UNKNOWN, NOT_CONFIGURED = StepStatus.UNKNOWN, StepStatus.NOT_CONFIGURED

TEST, FINDINGS, RETEST = step_names("manual_test")

# jpshackelford/tickster#62
BFF03B3 = "bff03b37c2a44624c2cac02403b80cccff502cf8"
AF8CDB1 = "af8cdb1d949ff100b040ebfe7a3ccc899b058cf1"
C77F38B = "c77f38b02084009d2ea4776562f8d97e273de78f"
HEAD_62 = "7ada92a0064056de4d47468a1252044f32e835d4"
BASE_62 = "df89f14d2afc1c412700b6889b28929f0952a160"
# jpshackelford/tickster#61
CEEE52D = "ceee52df66c16c70caead1a2648b1066fb22e7a3"
HEAD_61 = "1ba6a83bdc5ab47d9143718b62c256c73ada32f5"
BASE_61 = "0" * 40

# The moments of #62 the tests replay: the manual test report came at 11:09:51, the
# docs-only commit af8cdb1 at 11:16:20, the code fix c77f38b at 11:30:19.
BEFORE_REPORT = "2026-11-05T11:08:00Z"
ON_REPORT_HEAD = "2026-11-05T11:12:00Z"
AFTER_DOCS_PUSH = "2026-11-05T11:20:00Z"
AFTER_CODE_PUSH = "2026-11-05T11:35:00Z"

NORMS_TEXT = (FIXTURES / "tickster_norms.toml").read_text()
DOCS_REVIEW_TOML = """
[reports.docs_review]
required = false
marker = '^#+ *Documentation updated'
fail = 'needs docs'
"""


def load_norms(text: str = NORMS_TEXT) -> Norms:
    norms = parse_norms(text).norms
    assert norms is not None
    return norms


NORMS = load_norms()
REPORT = NORMS.reports["manual_test"]


def with_report(norms: Norms, **changes: Any) -> Norms:
    reports = dict(norms.reports, manual_test=replace(norms.reports["manual_test"], **changes))
    return replace(norms, reports=reports)


def with_impact(norms: Norms, **changes: Any) -> Norms:
    line = norms.reports["manual_test"].impact_line
    assert line is not None
    return with_report(norms, impact_line=replace(line, **changes))


def comment_node(at: str, login: str, body: str) -> dict:
    return {
        "__typename": "IssueComment",
        "author": {"login": login},
        "createdAt": at,
        "body": body,
    }


def recorded(number: int) -> dict:
    return json.loads((FIXTURES / f"reports_tickster_{number}.json").read_text())


def pr_as_of(
    number: int,
    at: str,
    norms: Norms | None = NORMS,
    synthetic: tuple[dict, ...] = (),
    **overrides: Any,
) -> PRInfo:
    """The recorded PR as it stood at ``at``: later events removed, it is open, and its
    head is the last commit before ``at``."""
    node = copy.deepcopy(recorded(number))

    def when(item: dict) -> str:
        return item.get("createdAt") or item["commit"]["committedDate"]

    kept = [
        i
        for i in node["timelineItems"]["nodes"]
        if i["__typename"] not in ("MergedEvent", "ClosedEvent") and when(i) <= at
    ]
    commits = [i for i in kept if i["__typename"] == "PullRequestCommit"]
    node.update(state="OPEN", closedAt=None, headRefOid=commits[-1]["commit"]["oid"])
    node["timelineItems"]["nodes"] = [*kept, *synthetic]
    node.update(overrides)
    norms_store.set_loader(lambda _repo: norms)
    return process_pr_data(node, REF_USER)


def pr_62(at: str = AFTER_CODE_PUSH, norms: Norms | None = NORMS, *synthetic: dict) -> PRInfo:
    return pr_as_of(62, at, norms, tuple(synthetic))


class FakeGitHub:
    """Serves one PR's REST endpoints from recorded compare responses.

    ``compares`` maps ``(start, head)`` (7-character prefixes) to a fixture file. A
    compare nobody recorded is a 500, so a test fails if the code asks for more.
    """

    def __init__(self, head: str, base: str, compares: dict[tuple[str, str], str]):
        self.head, self.base, self.compares = head, base, compares
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if "/pulls/" in path:
            return httpx.Response(
                200, json={"head": {"sha": self.head}, "base": {"sha": self.base}}
            )
        if "/compare/" in path:
            start, head = path.rsplit("/", 1)[1].split("...")
            name = self.compares.get((start[:7], head[:7]))
            if name is None:
                return httpx.Response(500, json={"message": f"unexpected call {path}"})
            return httpx.Response(200, json=json.loads((FIXTURES / name).read_text()))
        return httpx.Response(500)

    @property
    def compare_paths(self) -> list[str]:
        return [r.url.path.rsplit("/", 1)[1] for r in self.requests if "/compare/" in r.url.path]

    def client(self) -> ChangesClient:
        gh = GitHubClient.__new__(GitHubClient)
        gh._client = httpx.Client(transport=httpx.MockTransport(self.handle))
        client = ChangesClient.__new__(ChangesClient)
        client._client = gh
        return client


def fake_62(head: str = HEAD_62) -> FakeGitHub:
    return FakeGitHub(
        head,
        BASE_62,
        {
            ("bff03b3", "af8cdb1"): "compare_tickster_62_bff03b3_af8cdb1.json",
            ("bff03b3", "7ada92a"): "compare_tickster_62_bff03b3_7ada92a.json",
            ("af8cdb1", "7ada92a"): "compare_tickster_62_af8cdb1_7ada92a.json",
            ("df89f14", "7ada92a"): "compare_tickster_62_base_df89f14_7ada92a.json",
        },
    )


@pytest.fixture
def github(monkeypatch):
    """Route ``collect_steps``' changes client to a FakeGitHub the test chooses."""
    holder: dict[str, FakeGitHub] = {}

    def use(fake: FakeGitHub) -> FakeGitHub:
        holder["fake"] = fake
        monkeypatch.setattr(steps_cmd, "ChangesClient", fake.client)
        return fake

    return use


def steps_for(pr: PRInfo) -> dict[str, StepResult]:
    results = steps_cmd.collect_steps([pr])[f"{pr.repo}#{pr.number}"]
    return {r.step: r for r in results}


def statuses(steps: dict[str, StepResult], *names: str) -> list[StepStatus]:
    return [steps[n].status for n in names]


def explain_of(result: StepResult) -> str:
    return "\n".join(result.explain)


class TestNotConfigured:
    def test_without_a_norms_file_all_three_steps_are_not_configured(self):
        steps = steps_for(pr_as_of(62, AFTER_CODE_PUSH, norms=None))
        assert statuses(steps, TEST, FINDINGS, RETEST) == [NOT_CONFIGURED] * 3
        assert "no .agents/tickster.toml" in explain_of(steps[TEST])

    def test_a_norms_file_without_the_manual_test_report_is_not_configured_either(self):
        steps = steps_for(pr_as_of(62, AFTER_CODE_PUSH, norms=Norms()))
        assert statuses(steps, TEST, FINDINGS, RETEST) == [NOT_CONFIGURED] * 3
        assert "no [reports.manual_test]" in explain_of(steps[RETEST])

    def test_it_never_guesses_from_a_comment_that_looks_like_a_report(self, github):
        fake = github(fake_62())
        pr = pr_as_of(62, AFTER_CODE_PUSH, norms=None)
        assert any("Manual Test Results" in c.text for c in pr.comments or ()) is False
        steps_for(pr)
        assert fake.requests == []

    def test_the_other_steps_still_answer(self):
        steps = steps_for(pr_as_of(62, AFTER_CODE_PUSH, norms=None))
        assert len(steps) == len(STEP_NAMES)
        assert steps["review the PR"].status is not NOT_CONFIGURED


class TestManuallyTest:
    def test_no_report_on_a_required_report_is_needed(self, github):
        github(fake_62())
        steps = steps_for(pr_as_of(62, BEFORE_REPORT))
        assert steps[TEST].status is NEEDED
        assert steps[TEST].evidence[0].text == "no report"

    def test_a_report_makes_it_done(self, github):
        github(fake_62())
        steps = steps_for(pr_as_of(62, ON_REPORT_HEAD))
        result = steps[TEST]
        assert result.status is DONE
        assert (
            result.evidence[0].text == "report by jpshackelford at 2026-11-05T11:09:51Z on bff03b3"
        )

    def test_not_required_without_a_report_is_not_applicable(self):
        norms = with_report(NORMS, required=False)
        steps = steps_for(pr_as_of(62, BEFORE_REPORT, norms))
        assert steps[TEST].status is NA

    def test_not_required_with_a_report_is_done(self, github):
        github(fake_62())
        norms = with_report(NORMS, required=False)
        assert steps_for(pr_as_of(62, ON_REPORT_HEAD, norms))[TEST].status is DONE

    def test_only_paths_that_match_a_changed_file_still_need_the_report(self, github):
        fake = github(fake_62())
        norms = with_report(NORMS, only_paths=("src/**",))
        steps = steps_for(pr_as_of(62, BEFORE_REPORT, norms))
        assert steps[TEST].status is NEEDED
        assert "changed files match only_paths" in explain_of(steps[TEST])
        assert fake.compare_paths == [f"{BASE_62}...{HEAD_62}"]

    def test_only_paths_that_match_nothing_are_not_applicable(self, github):
        github(fake_62())
        norms = with_report(NORMS, only_paths=("infra/**",))
        steps = steps_for(pr_as_of(62, BEFORE_REPORT, norms))
        assert steps[TEST].status is NA
        assert steps[TEST].evidence[0].text == "no changed file matches only_paths"

    def test_empty_only_paths_never_reads_the_pr_files(self, github):
        fake = github(fake_62())
        steps_for(pr_as_of(62, BEFORE_REPORT))
        assert fake.requests == []

    def test_a_report_already_posted_never_reads_the_pr_files(self, github):
        fake = github(fake_62(head=BFF03B3))
        norms = with_report(NORMS, only_paths=("src/**",))
        pr = pr_as_of(62, ON_REPORT_HEAD, norms)
        assert not needs_pr_files(pr, norms)
        assert steps_for(pr)[TEST].status is DONE
        assert fake.requests == []

    def test_unfetched_pr_files_are_unknown(self):
        norms = with_report(NORMS, only_paths=("src/**",))
        result = evaluate_steps(pr_as_of(62, BEFORE_REPORT, norms), norms)
        assert result[4].status is UNKNOWN

    def test_a_truncated_timeline_cannot_say_no_report(self):
        pr = replace(pr_as_of(62, BEFORE_REPORT), timeline_truncated=True)
        assert evaluate_steps(pr, NORMS)[4].status is UNKNOWN

    def test_a_truncated_timeline_still_shows_a_report_it_found(self):
        pr = replace(pr_as_of(62, ON_REPORT_HEAD), timeline_truncated=True)
        assert evaluate_steps(pr, NORMS)[4].status is DONE

    def test_comments_not_fetched_is_unknown_for_all_three(self):
        pr = replace(pr_as_of(62, ON_REPORT_HEAD), comments=None)
        results = evaluate_steps(pr, NORMS)[4:7]
        assert [r.status for r in results] == [UNKNOWN] * 3
        assert "comments were not fetched" in results[0].explain[0]


class TestAddressTestFindings:
    def failing(self, at: str = "2026-11-05T11:10:00Z") -> dict:
        return comment_node(at, "jpshackelford", "## Manual Test Results for PR #62 ❌ FAIL\n")

    def test_no_report_is_not_applicable(self, github):
        github(fake_62())
        assert steps_for(pr_as_of(62, BEFORE_REPORT))[FINDINGS].status is NA

    def test_a_report_that_passes_is_done(self, github):
        github(fake_62(head=BFF03B3))
        result = steps_for(pr_as_of(62, ON_REPORT_HEAD))[FINDINGS]
        assert result.status is DONE
        assert "does not match" in explain_of(result)

    def test_a_latest_report_that_matches_fail_is_needed(self, github):
        github(fake_62(head=BFF03B3))
        pr = pr_as_of(62, ON_REPORT_HEAD, synthetic=(self.failing(),))
        result = steps_for(pr)[FINDINGS]
        assert result.status is NEEDED
        assert "fail = '❌ *FAIL' matches the latest report" in explain_of(result)

    def test_only_the_latest_report_counts(self, github):
        github(fake_62(head=BFF03B3))
        passing = comment_node(
            "2026-11-05T11:11:00Z", "jpshackelford", "## Manual Test Results (re-test)\n"
        )
        pr = pr_as_of(62, ON_REPORT_HEAD, synthetic=(self.failing(), passing))
        assert steps_for(pr)[FINDINGS].status is DONE

    def test_a_report_with_no_fail_pattern_never_fails(self, github):
        github(fake_62(head=BFF03B3))
        norms = with_report(NORMS, fail=None)
        pr = pr_as_of(62, ON_REPORT_HEAD, norms, (self.failing(),))
        result = steps_for(pr)[FINDINGS]
        assert result.status is DONE
        assert "no fail pattern" in explain_of(result)

    def test_fail_is_read_in_the_first_200_characters_like_the_marker(self, github):
        github(fake_62(head=BFF03B3))
        late = comment_node(
            "2026-11-05T11:10:00Z",
            "jpshackelford",
            "## Manual Test Results\n" + "x" * 200 + "❌ FAIL",
        )
        pr = pr_as_of(62, ON_REPORT_HEAD, synthetic=(late,))
        assert steps_for(pr)[FINDINGS].status is DONE

    def test_a_truncated_timeline_is_unknown(self):
        pr = replace(pr_as_of(62, ON_REPORT_HEAD), timeline_truncated=True)
        assert evaluate_steps(pr, NORMS)[5].status is UNKNOWN


class TestRetestAfterAFix:
    def test_no_report_is_not_applicable(self, github):
        github(fake_62())
        assert steps_for(pr_as_of(62, BEFORE_REPORT))[RETEST].status is NA

    def test_a_report_on_the_head_is_done_without_asking_github(self, github):
        fake = github(fake_62(head=BFF03B3))
        result = steps_for(pr_as_of(62, ON_REPORT_HEAD))[RETEST]
        assert result.status is DONE
        assert result.evidence[0].text == "report is on head bff03b3"
        assert fake.requests == []

    def test_a_docs_only_push_leaves_it_done(self, github):
        fake = github(fake_62(head=AF8CDB1))
        result = steps_for(pr_as_of(62, AFTER_DOCS_PUSH))[RETEST]
        assert result.status is DONE
        assert result.evidence[0].text == (
            "no significant change since bff03b3: all 1 changed files match ignore_paths"
        )
        assert fake.compare_paths == [f"{BFF03B3}...{AF8CDB1}"]

    def test_a_code_push_makes_it_needed(self, github):
        fake = github(fake_62())
        result = steps_for(pr_as_of(62, AFTER_CODE_PUSH))[RETEST]
        assert result.status is NEEDED
        assert result.evidence[0].text.startswith("significant change since bff03b3: ")
        assert fake.compare_paths == [f"{BFF03B3}...{HEAD_62}", f"{BASE_62}...{HEAD_62}"]

    def test_a_push_labelled_docs_that_touches_source_is_needed(self, github):
        github(
            FakeGitHub(
                HEAD_61,
                BASE_61,
                {("ceee52d", "1ba6a83"): "compare_tickster_61_ceee52d_1ba6a83.json"},
            )
        )
        pr = pr_as_of(61, "2026-11-05T11:10:00Z")
        result = steps_for(pr)[RETEST]
        assert result.status is NEEDED
        assert "src/board/macros.py +1 -1" in explain_of(result)
        assert "doc/board.md" in explain_of(result).split("ignore_paths: ")[1]

    def test_a_merge_from_base_alone_is_not_a_change(self):
        pr = pr_as_of(62, AFTER_CODE_PUSH)
        facts = ReportFacts(changes={BFF03B3: only_merges(BFF03B3)})
        assert evaluate_steps(pr, NORMS, report_facts=facts)[6].status is DONE

    def test_changes_not_fetched_is_unknown(self):
        result = evaluate_steps(pr_as_of(62, AFTER_CODE_PUSH), NORMS)[6]
        assert result.status is UNKNOWN
        assert "changes since bff03b3 were not fetched" in result.explain[0]

    def test_an_unknown_tested_commit_is_unknown(self):
        pr = pr_as_of(61, "2026-11-05T10:55:00Z", synthetic=(report_before_any_commit(),))
        assert evaluate_steps(pr, NORMS)[6].status is UNKNOWN

    def test_a_truncated_timeline_is_unknown(self):
        pr = replace(pr_as_of(62, AFTER_CODE_PUSH), timeline_truncated=True)
        assert evaluate_steps(pr, NORMS)[6].status is UNKNOWN


def only_merges(since: str):
    return PRChanges("o/r", 1, since, HEAD_62, False, [REASON_ONLY_MERGES])


def report_before_any_commit() -> dict:
    return comment_node("2026-11-05T10:00:00Z", "jpshackelford", "## Manual Test Results\n")


class TestWaiver:
    def none_line(self, at: str, login: str = "jpshackelford", value: str = "none") -> dict:
        return comment_node(at, login, f"Manual-test impact: {value} (docs only)\n")

    def retest(self, github, *synthetic: dict, norms: Norms = NORMS) -> StepResult:
        github(fake_62())
        return steps_for(pr_62(AFTER_CODE_PUSH, norms, *synthetic))[RETEST]

    def test_an_impact_line_none_from_an_allowed_actor_after_the_push_waives_it(self, github):
        result = self.retest(github, self.none_line("2026-11-05T11:33:00Z"))
        assert result.status is DONE
        assert [e.kind for e in result.evidence] == ["change", "impact"]
        assert result.evidence[1].text == "jpshackelford said none at 2026-11-05T11:33:00Z"
        assert "says 'none': waives the change" in explain_of(result)

    def test_the_same_line_from_a_disallowed_actor_does_not(self, github):
        result = self.retest(github, self.none_line("2026-11-05T11:33:00Z", login="mallory"))
        assert result.status is NEEDED
        assert "mallory (human)" in explain_of(result)
        assert "not from an allowed actor" in explain_of(result)

    def test_from_agents_alone_rejects_the_author_when_they_are_a_human(self, github):
        norms = with_impact(NORMS, from_=("agents",))
        result = self.retest(github, self.none_line("2026-11-05T11:33:00Z"), norms=norms)
        assert result.status is NEEDED

    def test_from_agents_accepts_a_listed_agent(self, github):
        norms = with_impact(NORMS, from_=("agents",))
        line = self.none_line("2026-11-05T11:33:00Z", login="openhands-agent")
        assert self.retest(github, line, norms=norms).status is DONE

    def test_from_humans_accepts_another_human(self, github):
        norms = with_impact(NORMS, from_=("humans",))
        line = self.none_line("2026-11-05T11:33:00Z", login="mallory")
        assert self.retest(github, line, norms=norms).status is DONE

    def test_a_line_posted_before_the_push_does_not_cover_it(self, github):
        result = self.retest(github, self.none_line(ON_REPORT_HEAD))
        assert result.status is NEEDED
        assert "is before the change: ignored" in explain_of(result)

    def test_a_line_posted_before_any_commit_cannot_cover_the_change(self, github):
        result = self.retest(github, self.none_line("2026-11-05T10:00:00Z"))
        assert result.status is NEEDED

    def test_a_line_between_two_pushes_does_not_cover_the_later_one(self, github):
        result = self.retest(github, self.none_line("2026-11-05T11:18:00Z"))
        assert result.status is NEEDED

    def test_a_line_after_the_last_real_commit_covers_the_merge_that_follows_it(self, github):
        result = self.retest(github, self.none_line("2026-11-05T11:30:19.500Z"))
        assert result.status is DONE

    def test_a_rerun_line_after_the_push_is_needed(self, github):
        result = self.retest(github, self.none_line("2026-11-05T11:33:00Z", value="rerun"))
        assert result.status is NEEDED
        assert result.evidence[-1].text == "jpshackelford said rerun at 2026-11-05T11:33:00Z"

    def test_the_latest_covering_line_decides(self, github):
        lines = (
            self.none_line("2026-11-05T11:33:00Z"),
            self.none_line("2026-11-05T11:34:00Z", value="rerun"),
        )
        assert self.retest(github, *lines).status is NEEDED

    def test_unassessed_rerun_needs_the_retest_when_no_line_covers_the_change(self, github):
        assert self.retest(github).status is NEEDED

    def test_unassessed_ignore_turns_the_unwaived_change_into_done(self, github):
        norms = with_impact(NORMS, unassessed="ignore")
        result = self.retest(github, norms=norms)
        assert result.status is DONE
        assert result.evidence[1].text == "unassessed, ignored"
        assert "unassessed = ignore" in explain_of(result)

    def test_unassessed_ignore_still_reruns_when_a_line_says_rerun(self, github):
        norms = with_impact(NORMS, unassessed="ignore")
        line = self.none_line("2026-11-05T11:33:00Z", value="rerun")
        assert self.retest(github, line, norms=norms).status is NEEDED

    def test_a_disallowed_line_leaves_the_decision_to_unassessed(self, github):
        norms = with_impact(NORMS, unassessed="ignore")
        line = self.none_line("2026-11-05T11:33:00Z", login="mallory")
        assert self.retest(github, line, norms=norms).status is DONE

    def test_a_report_without_an_impact_line_cannot_be_waived(self, github):
        norms = with_report(NORMS, impact_line=None)
        line = self.none_line("2026-11-05T11:33:00Z")
        result = self.retest(github, line, norms=norms)
        assert result.status is NEEDED
        assert "has no impact_line" in explain_of(result)

    def test_a_pattern_without_a_group_reads_the_whole_match(self, github):
        norms = with_impact(NORMS, pattern=re.compile("impact: none", re.IGNORECASE))
        assert (
            self.retest(github, self.none_line("2026-11-05T11:33:00Z"), norms=norms).status is DONE
        )

    def test_an_impact_line_does_not_waive_a_change_it_does_not_cover(self):
        pr = pr_62(AFTER_CODE_PUSH, NORMS, self.none_line("2026-11-05T11:33:00Z"))
        changes = ReportFacts(changes={BFF03B3: significant(BFF03B3, commits=())})
        assert evaluate_steps(pr, NORMS, report_facts=changes)[6].status is DONE

    def test_when_the_range_cannot_be_listed_only_the_current_head_covers_it(self):
        facts = ReportFacts(changes={BFF03B3: significant(BFF03B3, commits=())})
        early = pr_62(AFTER_CODE_PUSH, NORMS, self.none_line("2026-11-05T11:30:19.500Z"))
        assert evaluate_steps(early, NORMS, report_facts=facts)[6].status is NEEDED


def significant(since: str, commits=()):
    return PRChanges("o/r", 1, since, HEAD_62, True, ["history rewritten"], list(commits))


class TestSecondNamedReport:
    norms = load_norms(NORMS_TEXT + DOCS_REVIEW_TOML)
    DOCS, DOCS_FINDINGS, DOCS_REDO = step_names("docs_review")

    def test_the_names_come_from_the_report_name(self):
        assert (self.DOCS, self.DOCS_FINDINGS, self.DOCS_REDO) == (
            "docs review",
            "address docs review findings",
            "redo docs review after a fix",
        )
        assert step_names("manual_test") == (
            "manually test",
            "address test findings",
            "retest after a fix",
        )

    def test_a_repo_with_two_reports_lists_both_after_the_phase_a_steps(self):
        names = step_names_for(self.norms)
        assert names[:7] == tuple(STEP_NAMES)
        assert names[7:] == (self.DOCS, self.DOCS_FINDINGS, self.DOCS_REDO)
        assert all_step_names(self.norms) == names[4:]

    def test_the_second_report_has_its_own_steps(self, github):
        github(fake_62(head=AF8CDB1))
        steps = steps_for(pr_as_of(62, AFTER_DOCS_PUSH, self.norms))
        assert list(steps) == list(step_names_for(self.norms))
        assert statuses(steps, self.DOCS, self.DOCS_FINDINGS, self.DOCS_REDO) == [DONE] * 3
        assert "marker = '^#+ *Documentation updated' matched 1 of 2 comments" in explain_of(
            steps[self.DOCS]
        )

    def test_each_report_is_judged_against_its_own_tested_commit(self, github):
        fake = github(fake_62())
        steps = steps_for(pr_as_of(62, AFTER_CODE_PUSH, self.norms))
        assert steps[RETEST].status is NEEDED
        assert steps[self.DOCS_REDO].status is NEEDED
        assert steps[self.DOCS_REDO].evidence[1].ref == AF8CDB1
        starts = {p.split("...")[0] for p in fake.compare_paths}
        assert starts == {BFF03B3, AF8CDB1, BASE_62}

    def test_the_impact_line_of_one_report_does_not_waive_the_other(self, github):
        github(fake_62())
        line = comment_node("2026-11-05T11:33:00Z", "jpshackelford", "Manual-test impact: none")
        steps = steps_for(pr_as_of(62, AFTER_CODE_PUSH, self.norms, (line,)))
        assert steps[RETEST].status is DONE
        assert steps[self.DOCS_REDO].status is NEEDED

    def test_a_second_report_alone_still_lists_manual_test_as_not_configured(self):
        only_docs = load_norms("schema = 1\n" + DOCS_REVIEW_TOML)
        steps = {
            r.step: r for r in evaluate_steps(pr_as_of(62, AFTER_DOCS_PUSH, only_docs), only_docs)
        }
        assert statuses(steps, TEST, FINDINGS, RETEST) == [NOT_CONFIGURED] * 3
        assert steps[self.DOCS].status is DONE

    def test_the_list_column_shows_manual_test_only(self):
        results = evaluate_steps(pr_as_of(62, AFTER_DOCS_PUSH, self.norms), self.norms)
        assert len(results) == 10
        assert len(steps_mark(results)) == 7

    def test_snapshots_record_and_compare_every_step(self):
        prev = dict.fromkeys(step_names_for(self.norms), "done")
        curr = dict(prev, **{self.DOCS_REDO: "needed", RETEST: "needed"})
        assert step_changes(prev, curr) == (
            "retest after a fix: done → needed",
            "redo docs review after a fix: done → needed",
        )


class TestExplain:
    def test_it_names_the_marker_and_the_comment_it_matched(self, github):
        github(fake_62())
        explain = explain_of(steps_for(pr_62())[RETEST])
        assert (
            "[reports.manual_test] marker = '^#+ *Manual Test Results' matched 1 of 3 comments"
            in explain
        )
        assert (
            "the report is the latest match: jpshackelford at 2026-11-05T11:09:51Z; "
            "tested commit bff03b3"
        ) in explain

    def test_it_names_the_commits_and_files_that_made_the_change_significant(self, github):
        github(fake_62())
        explain = explain_of(steps_for(pr_62())[RETEST])
        assert 'commits that count: af8cdb1 "docs(pr): fix reproducible example' in explain
        assert "c77f38b \"fix(pr): don't count commits a merge-from-base" in explain
        assert "e8c7298" not in explain
        assert "files that count: .agents/tickster.toml +33 -0, " in explain
        assert ", and " in explain
        assert "files ignored by [commits] ignore_paths: " in explain
        assert "doc/usage.md" in explain.split("files ignored by [commits] ignore_paths: ")[1]

    def test_it_names_the_impact_line_settings_and_each_line_it_weighed(self, github):
        github(fake_62())
        line = comment_node("2026-11-05T11:33:00Z", "mallory", "manual-test impact: none")
        explain = explain_of(steps_for(pr_62(AFTER_CODE_PUSH, NORMS, line))[RETEST])
        assert "[reports.manual_test.impact_line] pattern = " in explain
        assert "from = [agents, author] unassessed = rerun" in explain
        assert "impact line by mallory (human) at 2026-11-05T11:33:00Z" in explain

    def test_a_long_file_list_is_cut_and_counted(self):
        files = [ChangedFile(f"src/f{i}.py", "modified", 1, 0) for i in range(14)]
        change = PRChanges("o/r", 1, BFF03B3, HEAD_62, True, ["14 files"], [], files)
        facts = ReportFacts(changes={BFF03B3: change})
        explain = explain_of(evaluate_steps(pr_62(), NORMS, report_facts=facts)[6])
        assert "src/f9.py +1 -0, and 4 more" in explain

    def test_the_text_output_shows_the_why_lines(self, fake_prs, github, capsys):
        github(fake_62())
        fake_prs.prs = [pr_62()]
        assert steps_cmd.cmd_steps(refs=["jpshackelford/tickster#62"], explain=True) == 0
        out = capsys.readouterr().out
        assert "retest after a fix: needed — significant change since bff03b3: " in out
        assert "    why: [reports.manual_test] marker = " in out

    def test_json_carries_the_evidence_and_the_explain_lines(self, fake_prs, github, capsys):
        github(fake_62())
        fake_prs.prs = [pr_62()]
        args = {"refs": ["jpshackelford/tickster#62"], "output_format": "json", "explain": True}
        assert steps_cmd.cmd_steps(**args) == 0
        captured = capsys.readouterr()
        [pr] = json.loads(captured.out)
        steps = {s["step"]: s for s in pr["steps"]}
        assert [s["step"] for s in pr["steps"]][4:] == list(STEP_NAMES[4:])
        assert steps[RETEST]["status"] == "needed"
        assert {e["kind"] for e in steps[RETEST]["evidence"]} == {"change", "report"}
        assert any("commits that count" in line for line in steps[RETEST]["explain"])
        assert captured.err == ""


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


@pytest.fixture
def fake_prs(monkeypatch, tmp_path):
    monkeypatch.setattr(board_config, "TKT_HOME", tmp_path)
    monkeypatch.setattr(board_config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(board_config, "CACHE_FILE", tmp_path / "board-cache.db")
    monkeypatch.setattr(FakePRClient, "prs", [])
    monkeypatch.setattr(steps_cmd, "PRClient", FakePRClient)
    monkeypatch.setattr(pr_list, "console", Console(width=200, color_system=None))
    return FakePRClient


class TestCollectSteps:
    def test_changes_are_fetched_once_per_tested_commit_and_only_when_needed(self, github):
        fake = github(fake_62())
        on_head = pr_as_of(62, ON_REPORT_HEAD)
        no_report = pr_as_of(62, BEFORE_REPORT)
        steps_cmd.collect_steps([on_head, no_report])
        assert fake.requests == []

    def test_one_client_serves_several_prs_and_is_closed(self, github, monkeypatch):
        fake = github(fake_62())
        closed: list[bool] = []
        real_close = ChangesClient.close
        monkeypatch.setattr(
            ChangesClient, "close", lambda self: (closed.append(True), real_close(self))
        )
        steps_cmd.collect_steps([pr_62(), pr_62()])
        assert closed == [True]
        assert fake.compare_paths.count(f"{BFF03B3}...{HEAD_62}") == 2

    def test_a_merged_pr_has_every_step_not_applicable(self):
        pr = replace(pr_as_of(62, AFTER_CODE_PUSH), state=PRState.MERGED)
        results = evaluate_steps(pr, load_norms(NORMS_TEXT + DOCS_REVIEW_TOML))
        assert [r.status for r in results] == [NA] * 10
        assert [r.step for r in results][4:] == list(
            step_names_for(load_norms(NORMS_TEXT + DOCS_REVIEW_TOML))
        )[4:]

    def test_a_merged_pr_makes_no_requests(self, github):
        fake = github(fake_62())
        merged = replace(pr_as_of(62, AFTER_CODE_PUSH), state=PRState.MERGED)
        assert tested_commits(merged, NORMS) == []
        steps_cmd.collect_steps([merged])
        assert fake.requests == []

    def test_list_steps_shows_the_manual_test_column(self, fake_prs, github, capsys, monkeypatch):
        github(fake_62())
        monkeypatch.setattr(pr_list, "PRClient", FakePRClient)
        monkeypatch.setattr(pr_list, "_get_repos", lambda *_: None)
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        fake_prs.prs = [pr_62()]
        assert pr_list.cmd_list(show_steps=True) == 0
        out = capsys.readouterr().out
        assert "m manual test, t test findings, x retest." in out
        assert "......X" in out


class TestPRFiles:
    def test_the_files_of_the_whole_pr(self):
        files = fake_62().client().pr_files("o/r", 62)
        assert files is not None
        assert "src/pr/changes.py" in {f.path for f in files}

    def test_a_listing_too_large_to_read_is_none(self):
        pages = [
            {
                "status": "ahead",
                "commits": [],
                "files": [
                    {"filename": f"f{p}-{i}", "status": "added", "additions": 1, "deletions": 0}
                    for i in range(100)
                ],
            }
            for p in range(12)
        ]

        def handle(request: httpx.Request) -> httpx.Response:
            if "/pulls/" in request.url.path:
                return httpx.Response(
                    200, json={"head": {"sha": "b" * 40}, "base": {"sha": "a" * 40}}
                )
            return httpx.Response(200, json=pages[int(request.url.params["page"]) - 1])

        gh = GitHubClient.__new__(GitHubClient)
        gh._client = httpx.Client(transport=httpx.MockTransport(handle))
        client = ChangesClient.__new__(ChangesClient)
        client._client = gh
        assert client.pr_files("o/r", 1) is None


class TestRecordedComments:
    def test_the_report_carries_the_head_it_was_posted_on(self):
        pr = pr_as_of(62, "2026-11-05T11:40:00Z")
        heads = {c.at: c.head for c in pr.comments or ()}
        assert heads == {
            "2026-11-05T11:09:51Z": BFF03B3,
            "2026-11-05T11:17:28Z": AF8CDB1,
            "2026-11-05T11:31:49Z": HEAD_62,
            "2026-11-05T11:39:10Z": HEAD_62,
        }

    def test_the_text_is_what_a_pattern_may_read(self):
        pr = pr_as_of(62, ON_REPORT_HEAD)
        [report] = pr.comments or ()
        assert len(report.text) == 200
        assert report.text.startswith("## Manual Test Results for PR #62")
        assert report.actor_class is ActorClass.ME_AGENT

    def test_a_force_push_moves_the_head(self):
        node = copy.deepcopy(recorded(62))
        node["timelineItems"]["nodes"].insert(
            5,
            {
                "__typename": "HeadRefForcePushedEvent",
                "createdAt": "2026-11-05T11:17:00Z",
                "afterCommit": {"oid": "f" * 40},
            },
        )
        norms_store.set_loader(lambda _repo: NORMS)
        pr = process_pr_data(node, REF_USER)
        heads = [c.head for c in pr.comments or ()]
        assert heads[:2] == [BFF03B3, "f" * 40]
        assert heads[2:] == [HEAD_62] * (len(heads) - 2)

    def test_a_repo_without_reports_collects_no_comments(self):
        assert pr_as_of(62, AFTER_CODE_PUSH, norms=None).comments == ()
        assert pr_as_of(62, AFTER_CODE_PUSH, norms=Norms()).comments == ()

    def test_a_deleted_author_and_a_null_node_are_tolerated(self):
        node = copy.deepcopy(recorded(62))
        node["timelineItems"]["nodes"].append(None)
        for item in node["timelineItems"]["nodes"]:
            if item and item["__typename"] == "IssueComment":
                item["author"] = None
        norms_store.set_loader(lambda _repo: NORMS)
        pr = process_pr_data(node, REF_USER)
        assert {c.actor for c in pr.comments or ()} == {"ghost"}

    def test_the_timeline_cap_is_recorded(self):
        node = copy.deepcopy(recorded(62))
        node["timelineItems"]["truncated"] = True
        norms_store.set_loader(lambda _repo: NORMS)
        assert process_pr_data(node, REF_USER).timeline_truncated is True


class TestUnits:
    def test_tested_commits_skips_a_report_already_on_the_head(self):
        assert tested_commits(pr_as_of(62, ON_REPORT_HEAD), NORMS) == []
        assert tested_commits(pr_as_of(62, AFTER_CODE_PUSH), NORMS) == [BFF03B3]
        assert tested_commits(pr_as_of(62, AFTER_CODE_PUSH), None) == []


class TestChangesParity:
    """``pr changes`` without flags and ``pr steps`` read the same ``[commits]`` norms."""

    @pytest.mark.parametrize(
        ("at", "head", "significant_expected"),
        [(AFTER_DOCS_PUSH, AF8CDB1, False), (AFTER_CODE_PUSH, HEAD_62, True)],
    )
    def test_same_verdict_for_the_same_pr_and_commit(
        self, capsys, monkeypatch, at, head, significant_expected
    ):
        fake = fake_62(head=head)
        pr = pr_as_of(62, at)
        via_steps = steps_cmd._report_facts(fake.client(), pr, NORMS).changes[BFF03B3]

        monkeypatch.setattr(changes_cmd, "ChangesClient", fake.client)
        code = main(
            [
                "pr",
                "changes",
                "jpshackelford/tickster#62",
                "--since-sha",
                BFF03B3,
                "--format",
                "json",
            ]
        )
        via_changes = json.loads(capsys.readouterr().out)

        assert code == 0
        assert via_changes["significant"] is via_steps.significant is significant_expected
        assert via_changes["reasons"] == via_steps.reasons
