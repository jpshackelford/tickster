"""Failing-check details for a single PR: which check, which step, which log."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.board.github_api import GitHubClient, get_github_token
from src.pr.history import _determine_ci_status
from src.pr.models import CIStatus

FAILING_CONCLUSIONS = frozenset({"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "CANCELLED"})
FAILING_STATUS_STATES = frozenset({"FAILURE", "ERROR"})

_PR_REF_RE = re.compile(r"^(?P<repo>[^/\s#]+/[^/\s#]+)#(?P<number>\d+)$")
_PR_URL_RE = re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/pull/(?P<number>\d+)")
_JOB_URL_RE = re.compile(r"/actions/runs/\d+/job/(?P<job_id>\d+)")
_LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z ?")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

CHECKS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
    repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
            mergeable
            commits(last: 1) {
                nodes {
                    commit {
                        ci: statusCheckRollup { state }
                        statusCheckRollup {
                            contexts(first: 100, after: $cursor) {
                                pageInfo { hasNextPage endCursor }
                                nodes {
                                    __typename
                                    ... on CheckRun {
                                        name
                                        conclusion
                                        detailsUrl
                                        startedAt
                                        checkSuite {
                                            workflowRun { workflow { name } }
                                        }
                                        steps(first: 100) {
                                            nodes {
                                                name
                                                conclusion
                                                startedAt
                                                completedAt
                                            }
                                        }
                                    }
                                    ... on StatusContext {
                                        context
                                        state
                                        targetUrl
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
"""


@dataclass
class FailedCheck:
    """One failing check, with the failing step when GitHub Actions reports one."""

    name: str
    url: str | None
    step: str | None = None
    job_id: int | None = None
    step_started_at: datetime | None = None
    step_completed_at: datetime | None = None


@dataclass
class PRChecks:
    """Failing checks for the head commit of a PR."""

    repo: str
    number: int
    ci_status: CIStatus
    failures: list[FailedCheck] = field(default_factory=list)


def parse_pr_ref(ref: str) -> tuple[str, int]:
    """Parse ``owner/repo#N`` or a GitHub PR URL into ``(owner/repo, N)``."""
    match = _PR_REF_RE.match(ref) or _PR_URL_RE.match(ref)
    if not match:
        raise ValueError(f"Invalid PR reference: {ref!r} (expected owner/repo#number or PR URL)")
    return match["repo"], int(match["number"])


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _latest_contexts(nodes: list[dict]) -> list[dict]:
    """Keep only the newest run of each (workflow, check name).

    The rollup lists every check run on the commit, including runs superseded by
    a re-run, so an old failure can sit next to a newer success of the same job.
    """
    latest: dict[tuple, tuple[str, dict]] = {}
    for node in nodes:
        if node.get("__typename") == "CheckRun":
            run = (node.get("checkSuite") or {}).get("workflowRun") or {}
            workflow = (run.get("workflow") or {}).get("name")
            key = ("check", workflow, node["name"])
        else:
            key = ("status", node.get("context"))
        started = node.get("startedAt") or ""
        if key not in latest or started >= latest[key][0]:
            latest[key] = (started, node)
    return [node for _, node in latest.values()]


def _failed_check_from_context(node: dict) -> FailedCheck | None:
    kind = node.get("__typename")
    if kind == "CheckRun":
        if node.get("conclusion") not in FAILING_CONCLUSIONS:
            return None
        url = node.get("detailsUrl")
        check = FailedCheck(name=node["name"], url=url)
        job = _JOB_URL_RE.search(url or "")
        if job:
            check.job_id = int(job["job_id"])
        failed_step = next(
            (
                s
                for s in (node.get("steps") or {}).get("nodes", [])
                if s.get("conclusion") in FAILING_CONCLUSIONS
            ),
            None,
        )
        if failed_step:
            check.step = failed_step["name"]
            check.step_started_at = _parse_time(failed_step.get("startedAt"))
            check.step_completed_at = _parse_time(failed_step.get("completedAt"))
        return check
    if kind == "StatusContext" and node.get("state") in FAILING_STATUS_STATES:
        return FailedCheck(name=node["context"], url=node.get("targetUrl"))
    return None


def _strip_log_line(line: str) -> str:
    return _ANSI_RE.sub("", _LOG_TS_RE.sub("", line, count=1))


def extract_step_log(
    log: str,
    started_at: datetime | None,
    completed_at: datetime | None,
    tail: int,
) -> tuple[list[str], int]:
    """Cut a job log down to one step and its last ``tail`` lines.

    Job logs have no per-step markers that can be matched across workflows, but
    every line carries a timestamp, so the step is selected by its start/end
    time. Step times only have second resolution, so lines of neighbouring steps
    in the same second leak in: the end is trimmed back to the step's last
    ``##[error]`` line (a failed step always ends with one), while the start may
    still include the tail of the previous step. With no step window the whole
    job log is used. Returns ``(lines, omitted_count)``; ``tail <= 0`` keeps all.
    """
    lo = started_at.astimezone(UTC).replace(microsecond=0, tzinfo=None) if started_at else None
    hi = completed_at.astimezone(UTC).replace(microsecond=0, tzinfo=None) if completed_at else None

    lines: list[str] = []
    in_window = not (lo or hi)
    for raw in log.lstrip("\ufeff").splitlines():
        match = _LOG_TS_RE.match(raw)
        if match and (lo or hi):
            ts = datetime.fromisoformat(match.group(1))
            in_window = (lo is None or ts >= lo) and (hi is None or ts <= hi)
        if in_window:
            lines.append(_strip_log_line(raw))

    if lo or hi:
        last_error = max(
            (i for i, line in enumerate(lines) if line.startswith("##[error]")), default=None
        )
        if last_error is not None:
            del lines[last_error + 1 :]

    omitted = 0
    if tail > 0 and len(lines) > tail:
        omitted = len(lines) - tail
        lines = lines[-tail:]
    return lines, omitted


class ChecksClient:
    """Fetches failing-check details for a PR."""

    def __init__(self, token: str | None = None):
        self._client = GitHubClient(token or get_github_token())

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ChecksClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def get_pr_checks(self, repo: str, number: int) -> PRChecks:
        """Return CI status and failing checks for the PR's head commit."""
        owner, name = repo.split("/", 1)
        nodes: list[dict] = []
        ci_input: dict = {}
        cursor: str | None = None

        while True:
            data = self._client.graphql(
                CHECKS_QUERY,
                {"owner": owner, "name": name, "number": number, "cursor": cursor},
                tolerate_null_roots=True,
            )
            pr = (data.get("repository") or {}).get("pullRequest")
            if not pr:
                raise ValueError(f"PR not found: {repo}#{number}")

            commit = (pr["commits"]["nodes"] or [{}])[-1].get("commit") or {}
            # Rollup `state` is wrong (reports stale failures) when requested in the same
            # field as `contexts`, so it comes from a separate alias to agree with `pr list`.
            ci_input = {
                "mergeable": pr["mergeable"],
                "commits": {"nodes": [{"commit": {"statusCheckRollup": commit.get("ci")}}]},
            }
            rollup = commit.get("statusCheckRollup")
            if not rollup:
                break
            contexts = rollup["contexts"]
            nodes.extend(n for n in contexts["nodes"] if n)
            if not contexts["pageInfo"]["hasNextPage"]:
                break
            cursor = contexts["pageInfo"]["endCursor"]

        failures = [f for n in _latest_contexts(nodes) if (f := _failed_check_from_context(n))]
        return PRChecks(
            repo=repo,
            number=number,
            ci_status=_determine_ci_status(ci_input),
            failures=failures,
        )

    def get_step_log(
        self,
        repo: str,
        check: FailedCheck,
        tail: int,
    ) -> tuple[list[str], int]:
        """Return the failing step's log (or the whole job's when no step failed).

        Raises ``ValueError`` for checks without a GitHub Actions job and
        ``httpx.HTTPStatusError`` when GitHub refuses or has expired the log.
        """
        if check.job_id is None:
            raise ValueError("not a GitHub Actions check")
        text = self._client.get_text(
            f"{GitHubClient.REST_BASE}/repos/{repo}/actions/jobs/{check.job_id}/logs"
        )
        return extract_step_log(text, check.step_started_at, check.step_completed_at, tail)
