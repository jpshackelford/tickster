"""``tkt pr show`` and ``tkt issue show``."""

from __future__ import annotations

import logging
import re
import traceback
from datetime import datetime
from typing import Literal

from rich.console import Console

from src.board.github_api import GitHubClient, get_github_token, get_github_username
from src.pr.checks import parse_pr_ref
from src.show.issue import build_issue_show, fetch_issue_node
from src.show.models import DEFAULT_MAX_BODY, parse_time
from src.show.pr import build_pr_show, fetch_pr_node
from src.show.render import render_json, render_text
from src.snapshot import store
from src.snapshot.cli.commands import _parse_ref as parse_snapshot_ref
from src.snapshot.models import KIND_ISSUE, KIND_PR, KIND_REVIEW

console = Console(stderr=True)
logger = logging.getLogger(__name__)

Format = Literal["text", "json"]

_ISSUE_REF_RE = re.compile(r"^(?P<repo>[^/\s#]+/[^/\s#]+)#(?P<number>\d+)$")
_ISSUE_URL_RE = re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/issues/(?P<number>\d+)")

# A review snapshot lists PRs too, so its last_activity says when a PR last moved.
_SNAPSHOT_KINDS = {"pr": (KIND_PR, KIND_REVIEW), "issue": (KIND_ISSUE,)}
_SNAPSHOT_ARTICLES = {"pr": "a", "issue": "an"}


def parse_issue_ref(ref: str) -> tuple[str, int]:
    """Parse ``owner/repo#N`` or a GitHub issue URL into ``(owner/repo, N)``."""
    match = _ISSUE_REF_RE.match(ref) or _ISSUE_URL_RE.match(ref)
    if not match:
        raise ValueError(
            f"Invalid issue reference: {ref!r} (expected owner/repo#number or issue URL)"
        )
    return match["repo"], int(match["number"])


def snapshot_last_activity(kind: str, snapshot_ref: str, repo: str, number: int) -> datetime:
    """The ``last_activity`` the named snapshot stored for this item."""
    snapshot_kind, name = parse_snapshot_ref(snapshot_ref)
    if snapshot_kind not in _SNAPSHOT_KINDS[kind]:
        allowed = " or ".join(_SNAPSHOT_KINDS[kind])
        article = _SNAPSHOT_ARTICLES[kind]
        raise ValueError(f"`{kind} show` reads {article} {allowed} snapshot, not {snapshot_kind}")
    snapshot = store.load(snapshot_kind, name)
    key = f"{repo}#{number}".lower()
    for item in snapshot.items:
        if item.key.lower() == key:
            return parse_time(item.last_activity)
    raise ValueError(f"snapshot {snapshot_ref} has no row for {repo}#{number}")


def cmd_show(
    *,
    kind: Literal["pr", "issue"],
    ref: str,
    since: str | None = None,
    since_snapshot: str | None = None,
    max_body: int = DEFAULT_MAX_BODY,
    output_format: Format = "text",
) -> int:
    """Print one item's header and timeline, optionally only the events after a time."""
    try:
        repo, number = parse_pr_ref(ref) if kind == "pr" else parse_issue_ref(ref)
        cutoff = None
        if since is not None:
            cutoff = parse_time(since)
        elif since_snapshot is not None:
            cutoff = snapshot_last_activity(kind, since_snapshot, repo, number)

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
