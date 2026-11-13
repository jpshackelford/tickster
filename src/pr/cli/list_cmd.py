"""PR list command - show PRs with history visualization."""

import logging
import traceback
from collections.abc import Mapping, Sequence
from functools import partial

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from src.all_authors import all_authors_error
from src.cli_errors import VERBOSE_HINT, print_error
from src.connection_paging import TRUNCATION_MARKER
from src.date_window import (
    PR_DATE_FIELDS,
    DateWindow,
    DateWindowError,
    build_date_window,
    resolve_field_flags,
    window_line,
    window_suffix,
)
from src.list_table import (
    add_shrinkable_column,
    print_filters,
    print_fitted_table,
    print_history_legend,
    print_note,
)
from src.pr.cli.graph import render_merged_graph
from src.pr.cli.steps_cmd import collect_steps
from src.pr.detail import merge_label, review_label, short_sha
from src.pr.github_api import PRClient
from src.pr.models import CIStatus, PRInfo, PRState
from src.pr.reviewers import REVIEWER_LEGEND, compact_reviewers, named_reviewers
from src.pr.steps import STEP_LETTERS, STEPS_LEGEND, StepResult, steps_mark
from src.show.delta import EVENTS_BRIEF, add_pr_evidence
from src.snapshot.convert import snapshot_from_prs
from src.snapshot.integration import SnapshotPlan
from src.snapshot.models import KIND_PR, SnapshotScope

console = Console()
logger = logging.getLogger(__name__)


def cmd_list(
    *,
    author: str | None = None,
    all_authors: bool = False,
    reviewer: str | None = None,
    repos: list[str] | None = None,
    pr_refs: list[str] | None = None,
    states: list[str] | None = None,
    board_name: str | None = None,
    limit: int = 100,
    show_title: bool = False,
    show_graph: bool = False,
    show_detail: bool = False,
    show_reviewers: bool = False,
    reviewer_names: bool = False,
    show_steps: bool = False,
    snapshot_name: str | None = None,
    diff_name: str | None = None,
    watch_name: str | None = None,
    output_format: str = "table",
    diff_show_unchanged: bool = False,
    diff_force: bool = False,
    diff_resolve: bool = False,
    exit_code: bool = False,
    events: str = EVENTS_BRIEF,
    max_body: int | None = None,
    field_dates: Mapping[str, int | str | None] | None = None,
) -> int:
    """List PRs with history visualization.

    Args:
        author: Filter by PR author (use "me" for current user)
        all_authors: List every author's PRs (needs repos; excludes author/reviewer/refs)
        reviewer: Filter by requested reviewer (use "me" for current user)
        repos: List of repos to filter by (owner/repo format)
        pr_refs: Specific PR references (owner/repo#number format)
        states: Filter by state (open, merged, closed)
        board_name: Board to get repos from (default: default board)
        limit: Maximum number of PRs to show
        show_title: Include PR titles in output
        show_graph: Show weekly merge/age graph (only for merged PRs)
        show_detail: Add head commit, review decision and merge state columns
        show_reviewers: Add a Reviewers column with a count per reviewer state
        reviewer_names: Like show_reviewers, but naming each reviewer
        show_steps: Add a Steps column: one character per pending-step (see STEPS_LEGEND).
            Only the table column: snapshots and JSON always record the statuses
        events: With a JSON diff, how much of each added or changed PR's new timeline
            events to carry: brief (bodies cut), full, or none (no timeline fetch)
        max_body: With ``events="brief"``, cut event bodies at this many characters
        field_dates: Per-field flag values keyed by dest, e.g. ``merged_since``

    Returns:
        Exit code (0 for success)
    """
    # Validate graph flag - only works with merged state
    if show_graph and (not states or "merged" not in states):
        print_error("--graph only works with --merged flag")
        return 1

    reviewers_mode = "names" if reviewer_names else "counts" if show_reviewers else None

    try:
        resolved = resolve_field_flags(
            PR_DATE_FIELDS,
            field_dates or {},
        )
        window = build_date_window(
            states,
            since_days=resolved.since_days,
            after=resolved.after,
            before=resolved.before,
            date_field=resolved.date_field,
            refs=pr_refs,
            flag_names=resolved.flag_names,
        )
    except DateWindowError as e:
        print_error(str(e))
        return 1
    date_qualifier = window.to_qualifier() if window else None

    if all_authors and reviewer:
        print_error(
            "--all-authors cannot be combined with --reviewer: review-requested "
            "PRs already include every author. Drop one of them."
        )
        return 1

    try:
        target_repos = None if pr_refs else _get_repos(repos, board_name)
        if all_authors:
            error = all_authors_error(has_refs=bool(pr_refs), repos=target_repos, noun="PRs")
            if error:
                print_error(error)
                return 1

        with PRClient() as client:
            filters: list[tuple[str, str]]
            if pr_refs:
                # Use case 3: Arbitrary PR list
                result = client.get_prs_by_ref(pr_refs)
                filters = [("refs", str(len(pr_refs)))]
            elif reviewer:
                # Use case 2: PRs requesting review
                # Resolve "me" here so the Filters line can show the login
                is_me = reviewer == "me"
                target_reviewer = client.get_current_user() if is_me else reviewer
                filters = _pr_filters(
                    reviewer=target_reviewer,
                    is_me=is_me,
                    states=states,
                    repos=target_repos,
                    limit=limit,
                )
                result = client.list_prs_for_reviewer(
                    target_reviewer,
                    repos=target_repos,
                    limit=limit,
                    date_qualifier=date_qualifier,
                )
            else:
                # Use case 1 & 4: PRs by author; default is the current user
                # (None = every author's, with --all-authors)
                is_me = author in (None, "me") and not all_authors
                target_author = client.get_current_user() if is_me else author
                filters = _pr_filters(
                    author=target_author,
                    is_me=is_me,
                    states=states,
                    repos=target_repos,
                    limit=limit,
                )
                result = client.list_prs_by_author(
                    target_author,
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
                output_format=output_format,
                show_unchanged=diff_show_unchanged,
                force=diff_force,
                resolve=diff_resolve,
                exit_code=exit_code,
                detail=show_detail,
                show_steps=show_steps,
            )

            steps = collect_steps(result.prs) if show_steps or plan is not None else None
            steps_column = steps if show_steps else None

            if plan is not None:
                scope = SnapshotScope.from_pr_args(
                    board=board_name,
                    author=author,
                    all_authors=all_authors,
                    reviewer=reviewer,
                    repos=target_repos,
                    refs=pr_refs,
                    states=states,
                    limit=limit,
                    window=window,
                )
                save_name = plan.save_name or plan.diff_name or ""
                curr_snapshot = snapshot_from_prs(
                    result.prs,
                    scope=scope,
                    name=save_name,
                    has_more=result.has_more,
                    steps=steps,
                )
                return plan.execute(
                    curr_snapshot,
                    console,
                    print_table=lambda: _print_pr_table(
                        result.prs,
                        show_title=show_title,
                        show_detail=show_detail,
                        reviewers=reviewers_mode,
                        steps=steps_column,
                        window=window,
                    ),
                    fetch_by_ref=lambda refs: client.get_prs_by_ref(refs).prs,
                    enrich=partial(
                        add_pr_evidence, events=events, max_body=max_body, steps=steps or {}
                    ),
                )

            # Show graph above table if requested
            if show_graph:
                # Filter to only merged PRs for the graph
                merged_prs = [pr for pr in result.prs if pr.state == PRState.MERGED]
                if merged_prs:
                    render_merged_graph(merged_prs, console=console)

            _print_pr_table(
                result.prs,
                show_title=show_title,
                show_detail=show_detail,
                reviewers=reviewers_mode,
                steps=steps_column,
                window=window,
            )
            print_filters(console, filters)

            if result.has_more:
                print_note(
                    console, f"\n[dim]Showing {len(result.prs)} of {result.total_count} PRs[/]"
                )

            if window and result.prs:
                print_note(console, f"[dim]{window_line(window)}[/]")

            return 0

    except BrokenPipeError:
        raise
    except Exception as e:
        logger.debug("Full traceback:\n%s", traceback.format_exc())
        print_error(str(e), hint=VERBOSE_HINT)
        return 1


def _pr_filters(
    *,
    states: Sequence[str] | None,
    repos: Sequence[str] | None,
    limit: int,
    is_me: bool,
    author: str | None = None,
    reviewer: str | None = None,
) -> list[tuple[str, str]]:
    """The effective filters of a query listing, in display order.

    With `reviewer` the search is `is:open review-requested:USER`, so the line shows
    `reviewer=` and `state=open` whatever `states` says. Otherwise `author` is the
    resolved login (`None` = every author). `is_me` marks a login that came from the
    default or `me`.
    """
    if reviewer is not None:
        who = ("reviewer", reviewer + (" (you)" if is_me else ""))
        state_text = "open"
    else:
        who = ("author", "all authors" if author is None else author + (" (you)" if is_me else ""))
        state_text = "+".join(states) if states else "open+merged+closed"
    return [
        who,
        ("state", state_text),
        ("repos", ",".join(repos) if repos else "all GitHub"),
        ("limit", str(limit)),
    ]


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


def _print_pr_table(
    prs: list[PRInfo],
    *,
    show_title: bool = False,
    show_detail: bool = False,
    reviewers: str | None = None,
    steps: dict[str, tuple[StepResult, ...]] | None = None,
    window: DateWindow | None = None,
) -> None:
    """Print PRs in a formatted table."""
    if not prs:
        print_note(console, f"[dim]No PRs found{window_suffix(window)}.[/]")
        return
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")

    add_shrinkable_column(table, "Repo", style="cyan")
    table.add_column("PR", justify="right", no_wrap=True)
    if show_title:
        add_shrinkable_column(table, "Title", max_width=35)
    history_col = len(table.columns)
    table.add_column("History", no_wrap=True)
    table.add_column("CI", no_wrap=True)
    if show_detail:
        table.add_column("Head", no_wrap=True)
        table.add_column("Review", no_wrap=True)
        table.add_column("Merge", no_wrap=True)
    if reviewers:
        table.add_column("Reviewers", no_wrap=True)
    if steps is not None:
        table.add_column("Steps", no_wrap=True, min_width=len(STEP_LETTERS))
    table.add_column("State", no_wrap=True)
    table.add_column("💬", justify="right", no_wrap=True)
    table.add_column("Age", no_wrap=True)
    table.add_column("Last", no_wrap=True)

    rows = []
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
                *(
                    [
                        short_sha(pr.head_sha),
                        review_label(pr.review_decision),
                        merge_label(pr.merge_state, pr.mergeable),
                    ]
                    if show_detail
                    else []
                ),
                *([_format_reviewers(pr, reviewers)] if reviewers else []),
                *([steps_mark(steps[f"{pr.repo}#{pr.number}"])] if steps is not None else []),
                _format_state(pr.state, pr.is_draft),
                _format_unresolved_threads(pr.unresolved_thread_count),
                _format_duration(pr.age_seconds),
                _format_relative_time(pr.last_activity_seconds),
            ]
        )
        rows.append(row)

    print_fitted_table(console, table, rows, history_col=history_col)
    print_history_legend(console, "pr", (pr.history for pr in prs))
    if reviewers:
        print_note(console, f"[dim]{escape(REVIEWER_LEGEND)}[/]")
    if steps is not None:
        print_note(console, f"[dim]{escape(STEPS_LEGEND)}[/]")


def _format_reviewers(pr: PRInfo, mode: str) -> str:
    cell = named_reviewers(pr.reviewers) if mode == "names" else compact_reviewers(pr.reviewers)
    return escape(cell + TRUNCATION_MARKER if pr.reviewers_truncated else cell)


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
