"""PR checks command - show failing checks, their failing step, and log."""

import logging
import traceback
from typing import Literal

import httpx
from rich.console import Console

from src.pr.checks import ChecksClient, FailedCheck, PRChecks, parse_pr_ref

console = Console()
logger = logging.getLogger(__name__)

Mode = Literal["short", "full"]
DEFAULT_TAIL = 100


def cmd_checks(*, ref: str, mode: Mode, tail: int = DEFAULT_TAIL) -> int:
    """Show failing checks for a PR.

    Args:
        ref: PR reference (owner/repo#number or GitHub PR URL)
        mode: "short" prints check, failing step and log URL; "full" prints
            check, failing step and the step's log
        tail: In full mode, keep only the last N log lines (0 = all)

    Returns:
        Exit code (0 for success)
    """
    try:
        repo, number = parse_pr_ref(ref)
        with ChecksClient() as client:
            checks = client.get_pr_checks(repo, number)
            _print_header(checks)
            if mode == "short":
                for check in checks.failures:
                    _print_short(check)
            else:
                for check in checks.failures:
                    _print_full(client, repo, check, tail)
        return 0
    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        console.print(f"[red]Error:[/] {e}")
        return 1


def _out(text: str = "") -> None:
    # Plain print: rich would expand the tab separators and wrap long URLs.
    print(text)


def _print_header(checks: PRChecks) -> None:
    status = checks.ci_status.value
    if checks.failures:
        _out(f"{checks.repo}#{checks.number} {status} {len(checks.failures)} failing")
    else:
        _out(f"{checks.repo}#{checks.number} {status} no failing checks")


def _print_short(check: FailedCheck) -> None:
    _out(f"{check.name}\t{check.step or '--'}\t{check.url or '--'}")


def _print_full(client: ChecksClient, repo: str, check: FailedCheck, tail: int) -> None:
    _out()
    _out(f"== {check.name} :: {check.step or '--'}")
    if check.job_id is None:
        _out(f"(no log available: not a GitHub Actions check) {check.url or ''}".rstrip())
        return
    try:
        lines, omitted = client.get_step_log(repo, check, tail)
    except httpx.HTTPStatusError as e:
        _out(f"(log unavailable: HTTP {e.response.status_code}) {check.url or ''}".rstrip())
        return
    if omitted:
        _out(f"... {omitted} earlier lines omitted (--tail 0 for all)")
    for line in lines:
        _out(line)
