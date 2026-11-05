"""PR changes command - what changed since a commit, and does it matter."""

import json
import logging
import traceback
from collections.abc import Sequence
from typing import Literal

from rich.console import Console

from src.pr.changes import ChangedCommit, ChangesClient, PRChanges, pr_changes
from src.pr.checks import parse_pr_ref

console = Console(stderr=True)
logger = logging.getLogger(__name__)

Format = Literal["text", "json"]
SHORT_SHA = 7


def cmd_changes(
    *,
    ref: str,
    since: str,
    output_format: Format = "text",
    ignore_paths: Sequence[str] = (),
    min_changed_lines: int = 0,
) -> int:
    """Show the commits and files between ``since`` and the PR head.

    Exit code is 0 whether or not the change is significant; the verdict is in
    the output.
    """
    try:
        repo, number = parse_pr_ref(ref)
        with ChangesClient() as client:
            changes = pr_changes(
                client,
                repo,
                number,
                since,
                ignore_paths=ignore_paths,
                min_changed_lines=min_changed_lines,
            )
    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        console.print(f"[red]Error:[/] {e}")
        return 1

    if output_format == "json":
        print(json.dumps(to_dict(changes), indent=2))
    else:
        _print_text(changes)
    return 0


def to_dict(changes: PRChanges) -> dict:
    return {
        "repo": changes.repo,
        "number": changes.number,
        "since": changes.since,
        "head": changes.head,
        "significant": changes.significant,
        "reasons": changes.reasons,
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


def _print_text(changes: PRChanges) -> None:
    additions = sum(f.additions for f in changes.files)
    deletions = sum(f.deletions for f in changes.files)
    print(
        f"{changes.repo}#{changes.number} {changes.since[:SHORT_SHA]}..{changes.head[:SHORT_SHA]} "
        f"{len(changes.commits)} commits {len(changes.files)} files +{additions} -{deletions}"
    )
    print(f"significant: {'yes' if changes.significant else 'no'} ({'; '.join(changes.reasons)})")
    for c in changes.commits:
        fields = [c.sha[:SHORT_SHA], _commit_marker(c), c.author or "--", c.headline]
        print("commit\t" + "\t".join(fields))
    for f in changes.files:
        marker = "ignored" if f.path in changes.ignored else "--"
        print(f"file\t{f.status}\t+{f.additions}\t-{f.deletions}\t{marker}\t{f.path}")
