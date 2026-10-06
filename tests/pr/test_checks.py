"""Tests for `tkt pr checks`: check selection, log slicing, and CLI output."""

from datetime import UTC, datetime

import httpx
import pytest

from src.__main__ import main
from src.pr.checks import (
    ChecksClient,
    FailedCheck,
    PRChecks,
    extract_step_log,
    parse_pr_ref,
)
from src.pr.cli import checks_cmd
from src.pr.models import CIStatus

JOB_URL = "https://github.com/o/r/actions/runs/11/job/22"


def _check_run(
    name: str,
    conclusion: str,
    *,
    workflow: str | None = "CI",
    started: str = "2026-10-05T10:00:00Z",
    url: str | None = JOB_URL,
    steps: list[dict] | None = None,
) -> dict:
    return {
        "__typename": "CheckRun",
        "name": name,
        "conclusion": conclusion,
        "detailsUrl": url,
        "startedAt": started,
        "checkSuite": {"workflowRun": {"workflow": {"name": workflow}} if workflow else None},
        "steps": {"nodes": steps or []},
    }


def _step(name: str, conclusion: str, started: str, completed: str) -> dict:
    return {"name": name, "conclusion": conclusion, "startedAt": started, "completedAt": completed}


class FakeGraphQL:
    """Stands in for GitHubClient: serves canned GraphQL pages and log text."""

    def __init__(self, pages: list[list[dict]], ci_state: str | None = "FAILURE", log: str = ""):
        self.pages = pages
        self.ci_state = ci_state
        self.log = log
        self.cursors: list[str | None] = []

    def graphql(self, _query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.cursors.append(variables["cursor"])
        index = len(self.cursors) - 1
        last = index == len(self.pages) - 1
        return {
            "repository": {
                "pullRequest": {
                    "mergeable": "MERGEABLE",
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "ci": {"state": self.ci_state} if self.ci_state else None,
                                    "statusCheckRollup": {
                                        "contexts": {
                                            "pageInfo": {
                                                "hasNextPage": not last,
                                                "endCursor": f"c{index}",
                                            },
                                            "nodes": self.pages[index],
                                        }
                                    },
                                }
                            }
                        ]
                    },
                }
            }
        }

    def get_text(self, _url: str) -> str:
        return self.log

    def close(self) -> None:
        pass


def _client(fake: FakeGraphQL) -> ChecksClient:
    client = ChecksClient.__new__(ChecksClient)
    client._client = fake  # pyright: ignore[reportAttributeAccessIssue]
    return client


class TestParsePrRef:
    def test_owner_repo_number(self):
        assert parse_pr_ref("octo/hello#7") == ("octo/hello", 7)

    def test_pr_url(self):
        assert parse_pr_ref("https://github.com/octo/hello/pull/7") == ("octo/hello", 7)

    @pytest.mark.parametrize("ref", ["nonsense", "octo/hello", "octo/hello#x", "#7"])
    def test_invalid(self, ref):
        with pytest.raises(ValueError, match="Invalid PR reference"):
            parse_pr_ref(ref)


class TestGetPrChecks:
    def test_reports_failing_check_with_failing_step(self):
        steps = [
            _step("Set up job", "SUCCESS", "2026-10-05T10:00:00Z", "2026-10-05T10:00:01Z"),
            _step("Run tests", "FAILURE", "2026-10-05T10:00:01Z", "2026-10-05T10:00:05Z"),
            _step("Post cleanup", "SUCCESS", "2026-10-05T10:00:05Z", "2026-10-05T10:00:05Z"),
        ]
        fake = FakeGraphQL(
            [[_check_run("test", "FAILURE", steps=steps), _check_run("lint", "SUCCESS")]]
        )

        result = _client(fake).get_pr_checks("o/r", 1)

        assert result.ci_status == CIStatus.RED
        assert [(f.name, f.step, f.url, f.job_id) for f in result.failures] == [
            ("test", "Run tests", JOB_URL, 22)
        ]
        assert result.failures[0].step_started_at == datetime(2026, 10, 5, 10, 0, 1, tzinfo=UTC)

    def test_check_without_failed_step_still_listed(self):
        fake = FakeGraphQL([[_check_run("test", "CANCELLED", steps=[])]])

        (failure,) = _client(fake).get_pr_checks("o/r", 1).failures

        assert failure.step is None
        assert failure.step_started_at is None

    @pytest.mark.parametrize("conclusion", ["SUCCESS", "SKIPPED", "NEUTRAL"])
    def test_passing_conclusions_are_not_failures(self, conclusion):
        fake = FakeGraphQL([[_check_run("test", conclusion)]], ci_state="SUCCESS")

        result = _client(fake).get_pr_checks("o/r", 1)

        assert result.failures == []
        assert result.ci_status == CIStatus.GREEN

    def test_superseded_failure_is_dropped(self):
        old = _check_run("test", "FAILURE", started="2026-10-05T10:00:00Z")
        new = _check_run("test", "SUCCESS", started="2026-10-05T11:00:00Z")

        assert _client(FakeGraphQL([[old, new]])).get_pr_checks("o/r", 1).failures == []
        assert _client(FakeGraphQL([[new, old]])).get_pr_checks("o/r", 1).failures == []

    def test_same_job_name_in_different_workflows_are_distinct(self):
        nodes = [
            _check_run("test", "FAILURE", workflow="CI"),
            _check_run("test", "SUCCESS", workflow="Docker", started="2026-10-05T11:00:00Z"),
        ]

        failures = _client(FakeGraphQL([nodes])).get_pr_checks("o/r", 1).failures

        assert [f.name for f in failures] == ["test"]

    def test_external_status_context_has_no_job(self):
        node = {
            "__typename": "StatusContext",
            "context": "ci/circleci",
            "state": "FAILURE",
            "targetUrl": "https://circleci.example/1",
        }

        (failure,) = _client(FakeGraphQL([[node]])).get_pr_checks("o/r", 1).failures

        assert (failure.name, failure.url, failure.step, failure.job_id) == (
            "ci/circleci",
            "https://circleci.example/1",
            None,
            None,
        )

    def test_passing_status_context_ignored(self):
        node = {
            "__typename": "StatusContext",
            "context": "ci",
            "state": "SUCCESS",
            "targetUrl": None,
        }

        assert (
            _client(FakeGraphQL([[node]], ci_state="SUCCESS")).get_pr_checks("o/r", 1).failures
            == []
        )

    def test_paginates_contexts(self):
        fake = FakeGraphQL([[_check_run("a", "SUCCESS")], [_check_run("b", "FAILURE")]])

        result = _client(fake).get_pr_checks("o/r", 1)

        assert fake.cursors == [None, "c0"]
        assert [f.name for f in result.failures] == ["b"]

    def test_pr_not_found(self):
        class Missing(FakeGraphQL):
            def graphql(self, _query, _variables=None):
                return {"repository": {"pullRequest": None}}

        with pytest.raises(ValueError, match="PR not found: o/r#1"):
            _client(Missing([])).get_pr_checks("o/r", 1)


LOG = "\n".join(
    [
        "\ufeff2026-10-05T10:00:00.1000000Z Set up job line",
        "2026-10-05T10:00:01.1000000Z ##[group]Run pytest",
        "2026-10-05T10:00:02.1000000Z \x1b[31mFAILED\x1b[0m test_a",
        "2026-10-05T10:00:03.1000000Z ##[error]Process completed with exit code 1.",
        "2026-10-05T10:00:03.2000000Z Post job cleanup.",
        "2026-10-05T10:00:06.1000000Z Complete job",
    ]
)
STEP_START = datetime(2026, 10, 5, 10, 0, 1, tzinfo=UTC)
STEP_END = datetime(2026, 10, 5, 10, 0, 3, tzinfo=UTC)


class TestExtractStepLog:
    def test_selects_step_window_and_trims_after_last_error(self):
        lines, omitted = extract_step_log(LOG, STEP_START, STEP_END, tail=0)

        assert lines == [
            "##[group]Run pytest",
            "FAILED test_a",
            "##[error]Process completed with exit code 1.",
        ]
        assert omitted == 0

    def test_tail_keeps_last_lines_and_counts_omitted(self):
        lines, omitted = extract_step_log(LOG, STEP_START, STEP_END, tail=2)

        assert lines == ["FAILED test_a", "##[error]Process completed with exit code 1."]
        assert omitted == 1

    def test_without_window_uses_whole_log_untrimmed(self):
        lines, _ = extract_step_log(LOG, None, None, tail=0)

        assert lines[0] == "Set up job line"
        assert lines[-1] == "Complete job"
        assert len(lines) == 6

    def test_window_without_error_line_keeps_whole_window(self):
        log = "2026-10-05T10:00:01.0000000Z a\n2026-10-05T10:00:02.0000000Z b"

        lines, _ = extract_step_log(log, STEP_START, STEP_END, tail=0)

        assert lines == ["a", "b"]

    def test_untimestamped_continuation_follows_previous_line(self):
        log = "2026-10-05T10:00:01.0000000Z a\ncontinued\n2026-10-05T10:00:09.0000000Z late\nlate-cont"

        lines, _ = extract_step_log(log, STEP_START, STEP_END, tail=0)

        assert lines == ["a", "continued"]


class TestGetStepLog:
    def test_non_actions_check_raises(self):
        check = FailedCheck(name="ci/circleci", url="https://x")

        with pytest.raises(ValueError, match="not a GitHub Actions check"):
            _client(FakeGraphQL([[]])).get_step_log("o/r", check, tail=10)

    def test_returns_step_slice(self):
        check = FailedCheck(
            name="test",
            url=JOB_URL,
            step="Run pytest",
            job_id=22,
            step_started_at=STEP_START,
            step_completed_at=STEP_END,
        )

        lines, _ = _client(FakeGraphQL([[]], log=LOG)).get_step_log("o/r", check, tail=0)

        assert lines[-1] == "##[error]Process completed with exit code 1."


class FakeChecksClient:
    """Replaces ChecksClient in the CLI layer."""

    checks = PRChecks(
        repo="o/r",
        number=7,
        ci_status=CIStatus.RED,
        failures=[
            FailedCheck(name="test (ubuntu)", url=JOB_URL, step="Run tests", job_id=22),
            FailedCheck(name="ci/circleci", url="https://circleci.example/1"),
        ],
    )
    log_error: Exception | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_pr_checks(self, repo, number):
        assert (repo, number) == ("o/r", 7)
        return self.checks

    def get_step_log(self, _repo, _check, _tail):
        if self.log_error:
            raise self.log_error
        return ["boom"], 3


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(checks_cmd, "ChecksClient", FakeChecksClient)
    monkeypatch.setattr(FakeChecksClient, "log_error", None)
    return FakeChecksClient


@pytest.mark.usefixtures("fake_client")
class TestCmdChecks:
    def test_short_prints_name_step_url_per_check(self, capsys):
        assert checks_cmd.cmd_checks(ref="o/r#7", mode="short") == 0

        assert capsys.readouterr().out.splitlines() == [
            "o/r#7 red 2 failing",
            f"test (ubuntu)\tRun tests\t{JOB_URL}",
            "ci/circleci\t--\thttps://circleci.example/1",
        ]

    def test_short_with_no_failures(self, monkeypatch, capsys):
        class Green(FakeChecksClient):
            checks = PRChecks(repo="o/r", number=7, ci_status=CIStatus.GREEN)

        monkeypatch.setattr(checks_cmd, "ChecksClient", Green)

        assert checks_cmd.cmd_checks(ref="o/r#7", mode="short") == 0
        assert capsys.readouterr().out.splitlines() == ["o/r#7 green no failing checks"]

    def test_full_prints_log_and_omitted_notice(self, capsys):
        assert checks_cmd.cmd_checks(ref="o/r#7", mode="full", tail=1) == 0

        out = capsys.readouterr().out
        assert (
            "== test (ubuntu) :: Run tests\n... 3 earlier lines omitted (--tail 0 for all)\nboom\n"
            in out
        )

    def test_full_external_check_has_no_log(self, capsys):
        checks_cmd.cmd_checks(ref="o/r#7", mode="full")

        out = capsys.readouterr().out
        assert (
            "== ci/circleci :: --\n(no log available: not a GitHub Actions check) https://circleci.example/1"
            in out
        )

    def test_full_log_download_failure_is_reported_not_fatal(self, capsys):
        response = httpx.Response(410, request=httpx.Request("GET", "https://x"))
        FakeChecksClient.log_error = httpx.HTTPStatusError(
            "gone", request=response.request, response=response
        )

        assert checks_cmd.cmd_checks(ref="o/r#7", mode="full") == 0

        assert f"(log unavailable: HTTP 410) {JOB_URL}" in capsys.readouterr().out

    def test_invalid_ref_is_an_error(self, capsys):
        assert checks_cmd.cmd_checks(ref="bogus", mode="short") == 1
        assert "Invalid PR reference" in capsys.readouterr().out


class TestCliArgs:
    def test_mode_is_required(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["pr", "checks", "o/r#7"])

        assert exc.value.code == 2
        assert "--short" in capsys.readouterr().err

    def test_short_and_full_are_mutually_exclusive(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["pr", "checks", "o/r#7", "--short", "--full"])

        assert exc.value.code == 2
        assert "not allowed with" in capsys.readouterr().err

    def test_tail_requires_full(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["pr", "checks", "o/r#7", "--short", "--tail", "5"])

        assert exc.value.code == 2
        assert "--tail can only be used with --full" in capsys.readouterr().err

    @pytest.mark.parametrize("value", ["-1", "abc"])
    def test_tail_rejects_invalid_values(self, capsys, value):
        with pytest.raises(SystemExit) as exc:
            main(["pr", "checks", "o/r#7", "--full", "--tail", value])

        assert exc.value.code == 2
        assert "--tail" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("flags", "mode", "tail"),
        [
            (["--short"], "short", 100),
            (["--full"], "full", 100),
            (["--full", "--tail", "5"], "full", 5),
            (["--full", "--tail", "0"], "full", 0),
        ],
    )
    def test_dispatches_to_cmd_checks(self, monkeypatch, flags, mode, tail):
        seen = {}
        monkeypatch.setattr("src.pr.cli.cmd_checks", lambda **kw: seen.update(kw) or 0)

        assert main(["pr", "checks", "o/r#7", *flags]) == 0
        assert seen == {"ref": "o/r#7", "mode": mode, "tail": tail}
