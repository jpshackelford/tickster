"""PR list command - show PRs with history visualization."""

import logging
import traceback

from rich import box
from rich.console import Console
from rich.table import Table

from src.date_window import DateWindowError, build_date_qualifier
from src.pr.cli.graph import render_merged_graph
from src.pr.github_api import PRClient
from src.pr.models import CIStatus, PRInfo, PRState
from src.snapshot.convert import snapshot_from_prs
from src.snapshot.integration import SnapshotPlan
from src.snapshot.models import KIND_PR, SnapshotScope

console = Console()
logger = logging.getLogger(__name__)


def cmd_list(
    *,
    author: str | None = None,
    reviewer: str | None = None,
    repos: list[str] | None = None,
    pr_refs: list[str] | None = None,
    states: list[str] | None = None,
    board_name: str | None = None,
    limit: int = 100,
    show_title: bool = False,
    show_graph: bool = False,
    snapshot_name: str | None = None,
    diff_name: str | None = None,
    watch_name: str | None = None,
    diff_format: str = "table",
    diff_show_unchanged: bool = False,
    diff_force: bool = False,
    since_days: int | None = None,
    after: str | None = None,
    before: str | None = None,
    date_field: str | None = None,
) -> int:
    """List PRs with history visualization.

    Args:
        author: Filter by PR author (use "me" for current user)
        reviewer: Filter by requested reviewer (use "me" for current user)
        repos: List of repos to filter by (owner/repo format)
        pr_refs: Specific PR references (owner/repo#number format)
        states: Filter by state (open, merged, closed)
        board_name: Board to get repos from (default: default board)
        limit: Maximum number of PRs to show
        show_title: Include PR titles in output
        show_graph: Show weekly merge/age graph (only for merged PRs)
        since_days: Only include PRs within the last N days
        after: Only include PRs on/after this date (YYYY-MM-DD)
        before: Only include PRs on/before this date (YYYY-MM-DD)
        date_field: Search date field to filter on
            (created/updated/merged/closed)

    Returns:
        Exit code (0 for success)
    """
    # Validate graph flag - only works with merged state
    if show_graph and (not states or "merged" not in states):
        console.print("[red]Error:[/] --graph only works with --merged flag")
        return 1

    try:
        date_qualifier = build_date_qualifier(
            states,
            since_days=since_days,
            after=after,
            before=before,
            date_field=date_field,
        )
    except DateWindowError as e:
        console.print(f"[red]Error:[/] {e}")
        return 1

    try:
        with PRClient() as client:
            target_repos = None if pr_refs else _get_repos(repos, board_name)
            # Determine which use case we're handling
            if pr_refs:
                # Use case 3: Arbitrary PR list
                result = client.get_prs_by_ref(pr_refs)
            elif reviewer:
                # Use case 2: PRs requesting review
                result = client.list_prs_for_reviewer(
                    reviewer,
                    repos=target_repos,
                    limit=limit,
                    date_qualifier=date_qualifier,
                )
            elif author:
                # Use case 1 & 4: PRs by author
                result = client.list_prs_by_author(
                    author,
                    repos=target_repos,
                    states=states,
                    limit=limit,
                    date_qualifier=date_qualifier,
                )
            else:
                # Default: current user's PRs from default board's repos
                result = client.list_prs_by_author(
                    "me",
                    repos=target_repos,
                    states=states,
                    limit=limit,
                    date_qualifier=date_qualifier,
                )

            plan = SnapshotPlan.from_args(
                kind=KIND_PR,
                snapshot_name=snapshot_name,
                diff_name=diff_name,
                watch_name=watch_name,
                output_format=diff_format,
                show_unchanged=diff_show_unchanged,
                force=diff_force,
            )

            if plan is not None:
                scope = SnapshotScope.from_pr_args(
                    board=board_name,
                    author=author,
                    reviewer=reviewer,
                    repos=target_repos,
                    refs=pr_refs,
                    states=states,
                    limit=limit,
                )
                save_name = plan.save_name or plan.diff_name or "snapshot"
                curr_snapshot = snapshot_from_prs(result.prs, scope=scope, name=save_name)
                return plan.execute(
                    curr_snapshot,
                    console,
                    print_table=lambda: _print_pr_table(result.prs, show_title=show_title),
                )

            # Show graph above table if requested
            if show_graph:
                # Filter to only merged PRs for the graph
                merged_prs = [pr for pr in result.prs if pr.state == PRState.MERGED]
                if merged_prs:
                    render_merged_graph(merged_prs, console=console)

            _print_pr_table(result.prs, show_title=show_title)

            if result.has_more:
                console.print(f"\n[dim]Showing {len(result.prs)} of {result.total_count} PRs[/]")

            return 0

    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        console.print(f"[red]Error:[/] {e}")
        console.print("[dim]Run with --verbose for full traceback[/]")
        return 1


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

    # Always try to use board repos by default
    from src.pr.config import get_repos

    board_repos = get_repos(board_name)
    return board_repos if board_repos else None


def _print_pr_table(prs: list[PRInfo], *, show_title: bool = False) -> None:
    """Print PRs in a formatted table."""
    if not prs:
        console.print("[dim]No PRs found.[/]")
        return
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")

    table.add_column("Repo", style="cyan", no_wrap=True)
    table.add_column("PR", justify="right", no_wrap=True)
    if show_title:
        table.add_column("Title", no_wrap=True, overflow="ellipsis", max_width=35)
    table.add_column("History", no_wrap=True)
    table.add_column("CI", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("💬", justify="right", no_wrap=True)
    table.add_column("Age", no_wrap=True)
    table.add_column("Last", no_wrap=True)

    for pr in prs:
        row = [
            pr.repo,
            f"#{pr.number}",
        ]
        if show_title:
            row.append(pr.title or "")
        row.extend(
            [
                _format_history(pr.history),
                _format_ci_status(pr.ci_status),
                _format_state(pr.state, pr.is_draft),
                _format_unresolved_threads(pr.unresolved_thread_count),
                _format_duration(pr.age_seconds),
                _format_relative_time(pr.last_activity_seconds),
            ]
        )
        table.add_row(*row)

    console.print(table)


def _format_history(history: str) -> str:
    """Format history string with colors for readability."""
    # Could add coloring here if desired
    # For now, return as-is
    return history


def _format_ci_status(status: CIStatus) -> str:
    """Format CI status with color."""
    if status == CIStatus.GREEN:
        return "[green]green[/]"
    elif status == CIStatus.RED:
        return "[red]red[/]"
    elif status == CIStatus.CONFLICT:
        return "[red]conflict[/]"
    elif status == CIStatus.PENDING:
        return "[yellow]pending[/]"
    else:
        return "[dim]--[/]"


def _format_state(state: PRState, is_draft: bool = False) -> str:
    """Format PR state with color."""
    if state == PRState.MERGED:
        return "[magenta]merged[/]"
    elif state == PRState.CLOSED:
        return "[dim]closed[/]"
    elif is_draft:
        return "[dim]draft[/]"
    else:
        return "[green]ready[/]"


def _format_unresolved_threads(count: int) -> str:
    """Format unresolved thread count."""
    if count == 0:
        return "[dim]--[/]"
    return f"[yellow]{count}[/]"


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
