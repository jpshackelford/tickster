"""Review list command - show reviewer's PR queue."""

import logging
import traceback
from collections.abc import Mapping, Sequence

from rich import box
from rich.console import Console
from rich.table import Table

from src.cli_errors import VERBOSE_HINT, print_error
from src.date_window import (
    REVIEW_DATE_FIELDS,
    DateWindowError,
    build_date_window,
    resolve_field_flags,
    window_line,
    window_suffix,
)
from src.list_table import add_shrinkable_column, print_filters, print_fitted_table, print_note
from src.pr.github_api import PRClient
from src.pr.models import CIStatus, PRInfo
from src.review.github_api import ReviewClient
from src.review.models import ReviewInfo, ReviewStatus
from src.snapshot.convert import snapshot_from_reviews
from src.snapshot.integration import SnapshotPlan
from src.snapshot.models import KIND_REVIEW, SnapshotScope

console = Console()
logger = logging.getLogger(__name__)

# Wait time thresholds (in seconds)
WAIT_CRITICAL_SECONDS = 48 * 3600  # 48 hours
WAIT_WARNING_SECONDS = 24 * 3600  # 24 hours


def _fetch_prs_by_ref(refs: list[str]) -> list[PRInfo]:
    """Look up PRs for `--diff-resolve`; review rows are PRs, which ReviewClient can't fetch."""
    with PRClient() as pr_client:
        return pr_client.get_prs_by_ref(refs).prs


def cmd_list(
    *,
    all_reviews: bool = False,
    reviewer: str | None = None,
    author: str | None = None,
    exclude_authors: list[str] | None = None,
    repos: list[str] | None = None,
    board_name: str | None = None,
    limit: int = 100,
    show_title: bool = False,
    states: list[str] | None = None,
    snapshot_name: str | None = None,
    diff_name: str | None = None,
    watch_name: str | None = None,
    output_format: str = "table",
    diff_show_unchanged: bool = False,
    diff_force: bool = False,
    diff_resolve: bool = False,
    field_dates: Mapping[str, int | str | None] | None = None,
) -> int:
    """List PRs needing review with status visualization.

    Args:
        all_reviews: Include approved and hold PRs (default: only actionable)
        reviewer: GitHub username to show queue for (default: current user)
        author: Filter by PR author
        exclude_authors: List of authors to exclude (e.g., dependabot[bot])
        repos: List of repos to filter by (owner/repo format)
        board_name: Board to get repos from (default: default board)
        limit: Maximum number of PRs to show
        show_title: Include PR titles in output
        states: List of states to include ("open", "merged", "closed")
        field_dates: Per-field flag values keyed by dest, e.g. ``merged_since``

    Returns:
        Exit code (0 for success)
    """
    try:
        resolved = resolve_field_flags(
            REVIEW_DATE_FIELDS,
            field_dates or {},
        )
        window = build_date_window(
            states,
            since_days=resolved.since_days,
            after=resolved.after,
            before=resolved.before,
            date_field=resolved.date_field,
            flag_names=resolved.flag_names,
            has_all_flag=False,
        )
    except DateWindowError as e:
        print_error(str(e))
        return 1
    date_qualifier = window.to_qualifier() if window else None

    try:
        with ReviewClient() as client:
            # Resolve reviewer to actual username (needed for legend)
            resolved_reviewer = reviewer if reviewer else client.get_current_user()

            # Get repos from board if not specified explicitly
            target_repos = _get_repos(repos, board_name)

            result = client.list_reviews(
                reviewer=resolved_reviewer,
                repos=target_repos,
                author=author,
                exclude_authors=exclude_authors,
                limit=limit,
                include_all=all_reviews,
                states=states,
                date_qualifier=date_qualifier,
            )

            # Determine whose queue we're showing for user-facing messages
            target_possessive = f"{reviewer}'s" if reviewer else "your"

            # Determine if we're showing historical PRs
            states_set = set(states or ["open"])
            showing_historical = "merged" in states_set or "closed" in states_set
            showing_open = "open" in states_set

            def print_table() -> None:
                if result.reviews:
                    _print_review_table(
                        result.reviews, reviewer=resolved_reviewer, show_title=show_title
                    )
                elif showing_historical and not showing_open:
                    print_note(
                        console,
                        f"[dim]No historical PRs found that {resolved_reviewer} reviewed"
                        f"{window_suffix(window)}.[/]",
                    )
                elif all_reviews:
                    print_note(
                        console,
                        f"[dim]No PRs found in {target_possessive} review queue"
                        f"{window_suffix(window)}.[/]",
                    )
                else:
                    print_note(
                        console,
                        f"[dim]No PRs needing {target_possessive} review{window_suffix(window)}.[/]",
                    )

            plan = SnapshotPlan.from_args(
                kind=KIND_REVIEW,
                snapshot_name=snapshot_name,
                diff_name=diff_name,
                watch_name=watch_name,
                output_format=output_format,
                show_unchanged=diff_show_unchanged,
                force=diff_force,
                resolve=diff_resolve,
            )
            if plan is not None:
                scope = SnapshotScope.from_review_args(
                    board=board_name,
                    author=author,
                    reviewer=reviewer,
                    repos=target_repos,
                    states=states,
                    exclude_authors=exclude_authors,
                    include_all=all_reviews,
                    limit=limit,
                    window=window,
                )
                save_name = plan.save_name or plan.diff_name or ""
                curr_snapshot = snapshot_from_reviews(
                    result.reviews, scope=scope, name=save_name, has_more=result.has_more
                )
                return plan.execute(
                    curr_snapshot,
                    console,
                    print_table=print_table,
                    fetch_by_ref=_fetch_prs_by_ref,
                )

            print_table()
            print_filters(
                console,
                _review_filters(
                    reviewer=resolved_reviewer,
                    is_me=reviewer is None,
                    author=author,
                    exclude_authors=exclude_authors,
                    include_all=all_reviews,
                    states=states,
                    repos=target_repos,
                    limit=limit,
                ),
            )
            if not result.reviews:
                return 0

            # Print summary
            if showing_historical and not showing_open:
                print_note(console, f"\n[dim]Showing {len(result.reviews)} historical PRs[/]")
            elif all_reviews:
                print_note(
                    console,
                    f"\n[dim]Showing {len(result.reviews)} PRs "
                    f"({result.action_count} need action)[/]",
                )
            else:
                print_note(
                    console,
                    f"\n[dim]Showing {len(result.reviews)} PRs needing {target_possessive} review[/]",
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


def _review_filters(
    *,
    reviewer: str,
    is_me: bool,
    author: str | None,
    exclude_authors: Sequence[str] | None,
    include_all: bool,
    states: Sequence[str] | None,
    repos: Sequence[str] | None,
    limit: int,
) -> list[tuple[str, str]]:
    """The effective filters of a review listing, in display order.

    `reviewer` is the resolved login; `is_me` marks the default (the current user).
    `author` and `exclude` appear only when set. `show` is `all` with `--all`
    (approved and hold PRs included), else `actionable`.
    """
    parts = [("reviewer", reviewer + (" (you)" if is_me else ""))]
    if author:
        parts.append(("author", author))
    if exclude_authors:
        parts.append(("exclude", ",".join(exclude_authors)))
    parts += [
        ("show", "all" if include_all else "actionable"),
        ("state", "+".join(states or ["open"])),
        ("repos", ",".join(repos) if repos else "all GitHub"),
        ("limit", str(limit)),
    ]
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

    # Always try to use board repos by default
    from src.pr.config import get_repos

    board_repos = get_repos(board_name)
    return board_repos if board_repos else None


def _print_review_table(
    reviews: list[ReviewInfo], *, reviewer: str, show_title: bool = False
) -> None:
    """Print reviews in a formatted table."""
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")

    add_shrinkable_column(table, "Repo", style="cyan")
    table.add_column("PR", justify="right", no_wrap=True)
    if show_title:
        add_shrinkable_column(table, "Title", max_width=35)
    history_col = len(table.columns)
    table.add_column("History", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Wait", no_wrap=True)
    table.add_column("CI", no_wrap=True)
    table.add_column("💬", justify="right", no_wrap=True)
    table.add_column("Author", no_wrap=True)
    table.add_column("Last", no_wrap=True)

    rows = []
    for review in reviews:
        row = [
            review.repo,
            f"#{review.number}",
        ]
        if show_title:
            row.append(review.title or "")
        row.extend(
            [
                _format_history(review.history),
                _format_status(review.status),
                _format_wait_time(review.wait_seconds, review.status),
                _format_ci_status(review.ci_status),
                _format_unresolved_threads(review.unresolved_thread_count),
                review.author,
                _format_relative_time(review.last_activity),
            ]
        )
        rows.append(row)

    print_fitted_table(console, table, rows, history_col=history_col)
    print_note(console, f"\n[dim]History: lowercase={reviewer}, UPPERCASE=others[/]")


def _format_history(history: str) -> str:
    """Format history string."""
    return history


def _format_status(status: ReviewStatus) -> str:
    """Format review status with color.

    - review, re-review: yellow (needs attention)
    - hold, approved: dim (info only)
    - merged: magenta (historical)
    - closed: dim (historical)
    """
    if status == ReviewStatus.REVIEW:
        return "[yellow]review[/]"
    elif status == ReviewStatus.RE_REVIEW:
        return "[yellow]re-review[/]"
    elif status == ReviewStatus.HOLD:
        return "[dim]hold[/]"
    elif status == ReviewStatus.APPROVED:
        return "[dim]approved[/]"
    elif status == ReviewStatus.MERGED:
        return "[magenta]merged[/]"
    else:  # CLOSED
        return "[dim]closed[/]"


def _format_wait_time(seconds: float, status: ReviewStatus) -> str:
    """Format wait time with urgency colors.

    - > 48h: red (critical)
    - > 24h: yellow (warning)
    - < 24h: default
    """
    duration = _format_duration(seconds)

    # Only colorize for actionable statuses
    if status not in (ReviewStatus.REVIEW, ReviewStatus.RE_REVIEW):
        return f"[dim]{duration}[/]"

    if seconds > WAIT_CRITICAL_SECONDS:
        return f"[red]{duration}[/]"
    elif seconds > WAIT_WARNING_SECONDS:
        return f"[yellow]{duration}[/]"
    else:
        return duration


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


def _format_relative_time(dt) -> str:
    """Format relative time (e.g., '3d ago', '2h ago')."""
    from datetime import datetime

    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    seconds = (now - dt).total_seconds()
    duration = _format_duration(abs(seconds))
    return f"{duration} ago"
