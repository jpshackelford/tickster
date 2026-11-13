"""``tkt pr show`` and ``tkt issue show``."""

from __future__ import annotations

import logging
import re
import traceback
from typing import Literal

from rich.console import Console

from src.board.github_api import GitHubClient, get_github_token, get_github_username
from src.pr.checks import parse_pr_ref
from src.show.issue import build_issue_show, fetch_issue_node
from src.show.models import DEFAULT_MAX_BODY, parse_time
from src.show.pr import build_pr_show, fetch_pr_node
from src.show.render import render_json, render_text

console = Console(stderr=True)
logger = logging.getLogger(__name__)

Format = Literal["text", "json"]

_ISSUE_REF_RE = re.compile(r"^(?P<repo>[^/\s#]+/[^/\s#]+)#(?P<number>\d+)$")
_ISSUE_URL_RE = re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)")


def parse_issue_ref(ref: str) -> tuple[str, int]:
    """Parse ``owner/repo#N`` or a GitHub issue URL into ``(owner/repo, N)``."""
    match = _ISSUE_REF_RE.match(ref) or _ISSUE_URL_RE.match(ref)
    if not match:
        raise ValueError(
            f"Invalid issue reference: {ref!r} (expected owner/repo#number or issue URL)"
        )
    return match["repo"], int(match["number"])


def cmd_show(
    *,
    kind: Literal["pr", "issue"],
    ref: str,
    since_time: str | None = None,
    max_body: int = DEFAULT_MAX_BODY,
    output_format: Format = "text",
) -> int:
    """Print one item's header and timeline, optionally only the events after a time."""
    try:
        repo, number = parse_pr_ref(ref) if kind == "pr" else parse_issue_ref(ref)
        cutoff = parse_time(since_time) if since_time is not None else None

        with GitHubClient(get_github_token()) as client:
            reference_user = get_github_username() or client.get_authenticated_user()
            if kind == "pr":
                show = build_pr_show(fetch_pr_node(client, repo, number), reference_user, max_body)
            else:
                show = build_issue_show(
                    fetch_issue_node(client, repo, number), reference_user, max_body
                )
        if cutoff is not None:
            show.apply_since(cutoff)
    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        console.print(f"[red]Error:[/] {e}")
        return 1

    if output_format == "json":
        print(render_json(show))
    else:
        print("\n".join(render_text(show)))
    return 0
