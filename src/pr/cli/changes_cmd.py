"""PR changes command - what changed since a commit, and does it matter."""

import json
import logging
import traceback
from collections.abc import Sequence
from typing import Literal

from rich.console import Console

from src.norms.store import get_repo_norms
from src.pr.changes import (
    ChangedCommit,
    ChangesClient,
    CommitSettings,
    InvalidSince,
    PRChanges,
    parse_since,
    pr_changes,
    resolve_commit_settings,
)
from src.pr.checks import parse_pr_ref

console = Console(stderr=True)
logger = logging.getLogger(__name__)

Format = Literal["text", "json"]
SHORT_SHA = 7
INDENT = "  "


def cmd_changes(
    *,
    ref: str,
    since: str,
    output_format: Format = "text",
    ignore_paths: Sequence[str] | None = None,
    min_changed_lines: int | None = None,
    explain: bool = False,
) -> int:
    """Show the commits and files between ``since`` and the PR head.

    ``ignore_paths`` and ``min_changed_lines`` that are not given come from the repo's
    ``[commits]`` norms; the repo's norms file is read only when one is missing.

    Exit code is 0 whether or not the change is significant; the verdict is in
    the output. A ``since`` that is not a 7 to 40 character hex SHA exits 2 before
    any GitHub call; other errors exit 1.
    """
    try:
        repo, number = parse_pr_ref(ref)
        parse_since(since)
        norms = (
            get_repo_norms(repo) if not (ignore_paths and min_changed_lines is not None) else None
        )
        settings = resolve_commit_settings(norms, ignore_paths, min_changed_lines)
        with ChangesClient() as client:
            changes = pr_changes(
                client,
                repo,
                number,
                since,
                ignore_paths=settings.ignore_paths,
                min_changed_lines=settings.min_changed_lines,
            )
    except InvalidSince as e:
        console.print(f"[red]Error:[/] {e}")
        return 2
    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        console.print(f"[red]Error:[/] {e}")
        return 1

    if output_format == "json":
        print(json.dumps(to_dict(changes, settings), indent=2))
    else:
        _print_text(changes, settings if explain else None)
    return 0


def to_dict(changes: PRChanges, settings: CommitSettings) -> dict:
    return {
        "repo": changes.repo,
        "number": changes.number,
        "since": changes.since,
        "head": changes.head,
        "significant": changes.significant,
        "reasons": changes.reasons,
        "settings": {
            "ignore_paths": list(settings.ignore_paths),
            "min_changed_lines": settings.min_changed_lines,
            "sources": {
                "ignore_paths": settings.ignore_paths_source,
                "min_changed_lines": settings.min_changed_lines_source,
            },
        },
        "commits": [
            {
                "sha": c.sha,
                "headline": c.headline,
                "author": c.author,
                "date": c.date,
                "merge": c.merge,
                "from_base": c.from_base,
            }
            for c in changes.commits
        ],
        "files": [
            {
                "path": f.path,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "ignored": f.path in changes.ignored,
            }
            for f in changes.files
        ],
    }


def _commit_marker(commit: ChangedCommit) -> str:
    if commit.merge:
        return "merge"
    return "base" if commit.from_base else "--"


def _print_text(changes: PRChanges, explain: CommitSettings | None) -> None:
    additions = sum(f.additions for f in changes.files)
    deletions = sum(f.deletions for f in changes.files)
    print(
        f"{changes.repo}#{changes.number} {changes.since[:SHORT_SHA]}..{changes.head[:SHORT_SHA]} "
        f"{len(changes.commits)} commits {len(changes.files)} files +{additions} -{deletions}"
    )
    print(f"significant: {'yes' if changes.significant else 'no'} ({'; '.join(changes.reasons)})")
    if explain:
        paths = ", ".join(explain.ignore_paths)
        print(f"{INDENT}why: ignore_paths = [{paths}] ({explain.ignore_paths_source})")
        print(
            f"{INDENT}why: min_changed_lines = {explain.min_changed_lines} "
            f"({explain.min_changed_lines_source})"
        )
    for c in changes.commits:
        fields = [c.sha[:SHORT_SHA], _commit_marker(c), c.author or "--", c.headline]
        print("commit\t" + "\t".join(fields))
    for f in changes.files:
        marker = "ignored" if f.path in changes.ignored else "--"
        print(f"file\t{f.status}\t+{f.additions}\t-{f.deletions}\t{marker}\t{f.path}")
