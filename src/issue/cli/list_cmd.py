"""Issue list command - show issues with history visualization."""

import logging
import traceback
from collections.abc import Mapping, Sequence

from rich import box
from rich.console import Console
from rich.table import Table

from src.all_authors import all_authors_error
from src.blocked_filter import blocked_filter_error
from src.cli_errors import VERBOSE_HINT, print_error
from src.date_window import (
    ISSUE_DATE_FIELDS,
    DateWindow,
    DateWindowError,
    build_date_window,
    resolve_field_flags,
    window_line,
    window_suffix,
)
from src.issue.dependencies import short_ref
from src.issue.github_api import IssueClient
from src.issue.models import IssueInfo, IssueState
from src.list_table import (
    add_shrinkable_column,
    print_filters,
    print_fitted_table,
    print_history_legend,
    print_note,
)
from src.pr_filter import pr_filter_error
from src.snapshot.convert import snapshot_from_issues
from src.snapshot.integration import SnapshotPlan
from src.snapshot.models import KIND_ISSUE, SnapshotScope

console = Console()
logger = logging.getLogger(__name__)


def cmd_list(
    *,
    author: str | None = None,
    all_authors: bool = False,
    repos: list[str] | None = None,
    issue_refs: list[str] | None = None,
    states: list[str] | None = None,
    labels: list[str] | None = None,
    not_labels: list[str] | None = None,
    pr_filter: str | None = None,
    blocked_filter: str | None = None,
    board_name: str | None = None,
    limit: int = 100,
    show_title: bool = False,
    show_deps: bool = False,
    sort_by_activity: bool = False,
    snapshot_name: str | None = None,
    diff_name: str | None = None,
    watch_name: str | None = None,
    output_format: str = "table",
    diff_show_unchanged: bool = False,
    diff_force: bool = False,
    diff_resolve: bool = False,
    field_dates: Mapping[str, int | str | None] | None = None,
) -> int:
    """List issues with history visualization.

    Args:
        author: Filter by issue author (use "me" for current user, default)
        all_authors: List every author's issues (needs repos; excludes author/refs)
        repos: List of repos to filter by (owner/repo format)
        issue_refs: Specific issue references (owner/repo#number format)
        states: Filter by state (open, closed); defaults to open
        labels: Filter by labels (comma-separated = OR, multiple = AND)
        not_labels: Leave out issues that have any of these labels (not with refs)
        pr_filter: "no-pr" or "has-pr": keep issues without or with a linked PR (not with refs)
        blocked_filter: "unblocked" or "blocked": keep issues without or with an open
            blocker (not with refs)
        board_name: Board to get repos from (default: default board)
        limit: Maximum number of issues to show
        show_title: Include issue titles in output
        show_deps: Add Blocked by and Blocks columns
        sort_by_activity: Sort by recent activity instead of creation date
        field_dates: Per-field flag values keyed by dest, e.g. ``created_since``

    Returns:
        Exit code (0 for success)
    """
    states = states or ["open"]
    try:
        resolved = resolve_field_flags(
            ISSUE_DATE_FIELDS,
            field_dates or {},
        )
        window = build_date_window(
            states,
            since_days=resolved.since_days,
            after=resolved.after,
            before=resolved.before,
            date_field=resolved.date_field,
            refs=issue_refs,
            merged_ok=False,
            flag_names=resolved.flag_names,
        )
    except DateWindowError as e:
        print_error(str(e))
        return 1
    date_qualifier = window.to_qualifier() if window else None

    if not_labels and issue_refs:
        print_error(
            "--not-label cannot be combined with explicit refs: refs list exactly the "
            "issues named. Drop the refs to filter by label, or drop --not-label."
        )
        return 1

    if error := pr_filter_error(pr_filter, has_refs=bool(issue_refs)):
        print_error(error)
        return 1

    if error := blocked_filter_error(blocked_filter, has_refs=bool(issue_refs)):
        print_error(error)
        return 1

    try:
        target_repos = None if issue_refs else _get_repos(repos, board_name)
        if all_authors:
            error = all_authors_error(has_refs=bool(issue_refs), repos=target_repos, noun="issues")
            if error:
                print_error(error)
                return 1

        with IssueClient() as client:
            filters: list[tuple[str, str]]
            if issue_refs:
                result = client.get_issues_by_ref(issue_refs)
                filters = [("refs", str(len(issue_refs)))]
            else:
                # Resolve "me" here so the Filters line can show the login
                is_me = not all_authors and author in (None, "me")
                if all_authors:
                    target_author = None
                elif is_me:
                    target_author = client.get_current_user()
                else:
                    target_author = author
                filters = _issue_filters(
                    author=target_author,
                    is_me=is_me,
                    states=states,
                    repos=target_repos,
                    labels=labels,
                    not_labels=not_labels,
                    blocked_filter=blocked_filter,
                    limit=limit,
                )
                result = client.list_issues_by_author(
                    target_author,
                    repos=target_repos,
                    states=states,
                    labels=labels,
                    limit=limit,
                    sort_by_activity=sort_by_activity,
                    date_qualifier=date_qualifier,
                    not_labels=not_labels,
                    pr_filter=pr_filter,
                    blocked_filter=blocked_filter,
                )

            plan = SnapshotPlan.from_args(
                kind=KIND_ISSUE,
                snapshot_name=snapshot_name,
                diff_name=diff_name,
                watch_name=watch_name,
                output_format=output_format,
                show_unchanged=diff_show_unchanged,
                force=diff_force,
                resolve=diff_resolve,
            )
            if plan is not None:
                scope = SnapshotScope.from_issue_args(
                    board=board_name,
                    author=author,
                    all_authors=all_authors,
                    repos=target_repos,
                    refs=issue_refs,
                    states=states,
                    labels=labels,
                    not_labels=not_labels,
                    pr_filter=pr_filter,
                    blocked_filter=blocked_filter,
                    limit=limit,
                    window=window,
                )
                save_name = plan.save_name or plan.diff_name or ""
                curr_snapshot = snapshot_from_issues(
                    result.issues, scope=scope, name=save_name, has_more=result.has_more
                )
                return plan.execute(
                    curr_snapshot,
                    console,
                    print_table=lambda: _print_issue_table(
                        result.issues, show_title=show_title, show_deps=show_deps, window=window
                    ),
                    fetch_by_ref=lambda refs: client.get_issues_by_ref(refs).issues,
                )

            _print_issue_table(
                result.issues, show_title=show_title, show_deps=show_deps, window=window
            )
            print_filters(console, filters)
            if not result.issues:
                return 0

            if show_deps:
                print_note(
                    console,
                    "[dim]Blocked by: open blockers (? = one you cannot read); "
                    "Blocks: open issues this one blocks[/]",
                )

            if result.has_more and (pr_filter or blocked_filter):
                print_note(
                    console,
                    f"\n[dim]Showing {len(result.issues)} matching issues "
                    "(more available; raise --limit)[/]",
                )
            elif result.has_more:
                print_note(
                    console,
                    f"\n[dim]Showing {len(result.issues)} of {result.total_count} issues[/]",
                )

            if window:
                print_note(console, f"[dim]{window_line(window)}[/]")

            return 0

    except BrokenPipeError:
        raise
    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        print_error(str(e), hint=VERBOSE_HINT)
        return 1


def _issue_filters(
    *,
    author: str | None,
    is_me: bool,
    states: Sequence[str],
    repos: Sequence[str] | None,
    labels: Sequence[str] | None,
    not_labels: Sequence[str] | None,
    blocked_filter: str | None,
    limit: int,
) -> list[tuple[str, str]]:
    """The effective filters of a query listing, in display order.

    `author` is the resolved login (`None` = every author); `is_me` marks a login that
    came from the default or `me`. Repeated labels are AND (` & `), commas inside one
    are OR (`|`). `not-label` and `blocked` appear only when given.
    """
    author_text = "all authors" if author is None else author + (" (you)" if is_me else "")
    label_text = " & ".join(label.replace(",", "|") for label in labels) if labels else "any"
    parts = [
        ("author", author_text),
        ("state", "+".join(states)),
        ("repos", ",".join(repos) if repos else "all GitHub"),
        ("label", label_text),
    ]
    if not_labels:
        parts.append(("not-label", ",".join(not_labels)))
    if blocked_filter:
        parts.append(("blocked", "yes" if blocked_filter == "blocked" else "no"))
    parts.append(("limit", str(limit)))
    return parts


def _get_repos(
    repos: list[str] | None,
    board_name: str | None,
) -> list[str] | None:
    """Get list of repos to query.

    Priority:
    1. Explicit --repo flags
    2. Board repos (from --board or default board)
    3. None (all GitHub)
    """
    if repos:
        return repos

    # Try to use board repos by default
    from src.repo.config import get_repos

    board_repos = get_repos(board_name)
    return board_repos if board_repos else None


def _print_issue_table(
    issues: list[IssueInfo],
    *,
    show_title: bool = False,
    show_deps: bool = False,
    window: DateWindow | None = None,
) -> None:
    """Print issues in a formatted table."""
    if not issues:
        print_note(console, f"[dim]No issues found{window_suffix(window)}.[/]")
        return
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")

    add_shrinkable_column(table, "Repo", style="cyan")
    table.add_column("Issue", justify="right", no_wrap=True)
    if show_title:
        add_shrinkable_column(table, "Title", max_width=35)
    history_col = len(table.columns)
    table.add_column("History", no_wrap=True)
    table.add_column("PR", no_wrap=True)
    if show_deps:
        add_shrinkable_column(table, "Blocked by", max_width=25)
        table.add_column("Blocks", justify="right", no_wrap=True)
    add_shrinkable_column(table, "Labels", max_width=25)
    table.add_column("State", no_wrap=True)
    table.add_column("Age", no_wrap=True)
    table.add_column("Last", no_wrap=True)

    rows = []
    for issue in issues:
        row = [
            issue.repo,
            f"#{issue.number}",
        ]
        if show_title:
            row.append(issue.title or "")
        row.extend(
            [
                issue.history,
                _format_linked_pr(issue.linked_pr),
            ]
        )
        if show_deps:
            row.extend([_format_blockers(issue), str(issue.blocking)])
        row.extend(
            [
                _format_labels(issue.labels),
                _format_state(issue.state),
                _format_duration(issue.age_seconds),
                _format_relative_time(issue.last_activity_seconds),
            ]
        )
        rows.append(row)

    print_fitted_table(console, table, rows, history_col=history_col)
    print_history_legend(console, "issue", (issue.history for issue in issues))


def _format_linked_pr(linked_pr: str | None) -> str:
    """Format linked PR reference."""
    if not linked_pr:
        return "[dim]--[/]"
    # Extract just the #number part for brevity
    if "#" in linked_pr:
        return f"[green]#{linked_pr.split('#')[1]}[/]"
    return f"[green]{linked_pr}[/]"


def _format_blockers(issue: IssueInfo) -> str:
    """Open blockers, `#N` for the issue's own repo; `--` for none."""
    if not issue.open_blockers:
        return "[dim]--[/]"
    return ",".join(short_ref(ref, issue.repo) for ref in issue.open_blockers)


def _format_labels(labels: list[str]) -> str:
    """Format labels for display."""
    if not labels:
        return "[dim]--[/]"
    return ",".join(labels)


def _format_state(state: IssueState) -> str:
    """Format issue state with color."""
    if state == IssueState.OPEN:
        return "[green]open[/]"
    else:
        return "[dim]closed[/]"


def _format_duration(seconds: float) -> str:
    """Format duration in compact form (e.g., '3d', '2h', '45m')."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h"
    else:
        days = int(seconds / 86400)
        return f"{days}d"


def _format_relative_time(seconds: float) -> str:
    """Format relative time (e.g., '3d ago', '2h ago')."""
    duration = _format_duration(seconds)
    return f"{duration} ago"
