"""PR steps command - which follow-up steps a PR still needs, and why."""

import json
import logging
import traceback
from collections.abc import Sequence
from typing import Literal

from rich.console import Console

from src.norms.store import get_repo_norms
from src.pr.checks import ChecksClient, parse_pr_ref
from src.pr.github_api import PRClient
from src.pr.models import PRInfo
from src.pr.steps import StepResult, evaluate_steps, needs_check_details

console = Console(stderr=True)
logger = logging.getLogger(__name__)

Format = Literal["text", "json"]
INDENT = "  "


def collect_steps(prs: Sequence[PRInfo]) -> dict[str, tuple[StepResult, ...]]:
    """Steps per PR, keyed ``owner/repo#N``.

    The individual checks are fetched only for a PR whose repo ignores some
    checks and whose rollup is not green; every other verdict needs no extra call.
    """
    out: dict[str, tuple[StepResult, ...]] = {}
    checks_client: ChecksClient | None = None
    try:
        for pr in prs:
            norms = get_repo_norms(pr.repo)
            contexts = None
            if needs_check_details(pr, norms):
                checks_client = checks_client or ChecksClient()
                contexts = checks_client.get_pr_checks(pr.repo, pr.number).contexts
            out[f"{pr.repo}#{pr.number}"] = evaluate_steps(pr, norms, contexts)
    finally:
        if checks_client:
            checks_client.close()
    return out


def cmd_steps(
    *,
    refs: Sequence[str],
    output_format: Format = "text",
    explain: bool = False,
) -> int:
    """Print the pending steps of each PR. Exit code is 0 whatever the statuses are."""
    try:
        wanted = [parse_pr_ref(ref) for ref in refs]
        keys = [f"{repo}#{number}" for repo, number in wanted]
        with PRClient() as client:
            prs = client.get_prs_by_ref(keys).prs
        by_key = {f"{pr.repo}#{pr.number}".lower(): pr for pr in prs}
        missing = [k for k in keys if k.lower() not in by_key]
        if missing:
            raise ValueError(f"PR not found: {', '.join(missing)}")
        steps = collect_steps([by_key[k.lower()] for k in keys])
    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        console.print(f"[red]Error:[/] {e}")
        return 1

    if output_format == "json":
        print(json.dumps(to_dict(steps, explain=explain), indent=2))
    else:
        print_text(steps, explain=explain)
    return 0


def to_dict(steps: dict[str, tuple[StepResult, ...]], *, explain: bool = False) -> list[dict]:
    return [
        {"pr": key, "steps": [r.to_dict(explain=explain) for r in results]}
        for key, results in steps.items()
    ]


def print_text(steps: dict[str, tuple[StepResult, ...]], *, explain: bool = False) -> None:
    for key, results in steps.items():
        print(key)
        for r in results:
            print(INDENT + r.line())
            if explain:
                for why in r.explain:
                    print(f"{INDENT * 2}why: {why}")
