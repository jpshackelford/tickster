"""Rich / JSON renderers for a `DiffResult`.

Rendering choices (per the design in issue #6):

- A leading `Δ` column with `+ * -` glyphs (space for unchanged).
- The history string carries `[bracketed]` tails for the characters that
  are new since the previous snapshot — nothing else is reformatted so
  the output stays readable to anyone familiar with the normal
  `tkt pr list` / `tkt issue list` / `tkt review` tables.
- A one-line summary header with scope-match status and counts.
- `--only-changed` by default: UNCHANGED rows are hidden unless the caller
  passes `show_unchanged=True`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from rich import box
from rich.console import Console
from rich.table import Table

from src.list_table import add_shrinkable_column, print_fitted_table, print_note
from src.pr.detail import merge_label, review_label, short_sha
from src.snapshot.models import ChangeKind, DiffResult, ItemDelta, Snapshot

# Diff tables have up to five shrinkable columns, so each gets a lower floor than in lists.
SHRINK_FLOOR = 4

_KIND_GLYPH = {
    ChangeKind.ADDED: "[green]+[/]",
    ChangeKind.CHANGED: "[yellow]*[/]",
    ChangeKind.REMOVED: "[red]-[/]",
    ChangeKind.UNCHANGED: " ",
}

_MERGE_FIELDS = frozenset({"merge_state", "mergeable"})

# The `-` glyph already says "gone"; the note only hints at why.
_REMOVAL_LABEL = {
    "closed-or-gone": "closed?",
    "left-queue": "done?",
    "scope": "scope",
    "limit": "limit?",
    "closed": "closed",
    "merged": "merged",
    "still-open": "still open",
    "not-found": "not found",
}


def render_diff(
    diff: DiffResult,
    *,
    console: Console | None = None,
    show_unchanged: bool = False,
    output_format: str = "table",
    detail: bool = False,
) -> None:
    """Render a diff to the console. `output_format` ∈ {"table", "json"}.

    `detail` adds the PR head / review / merge columns to the table.
    """
    console = console or Console()
    if output_format == "json":
        console.print_json(json.dumps(diff.to_dict()))
        return
    if output_format != "table":
        raise ValueError(f"unknown diff output format: {output_format!r}")

    _print_summary(diff, console=console)
    deltas = [d for d in diff.deltas if show_unchanged or d.kind is not ChangeKind.UNCHANGED]
    if not deltas:
        print_note(console, "[dim]No changes.[/]")
        return

    kind = diff.curr.kind
    if kind == "pr" or kind == "review":
        _print_pr_like_table(deltas, console=console, kind=kind, detail=detail)
    elif kind == "issue":
        _print_issue_table(deltas, console=console)
    else:  # pragma: no cover — guarded upstream
        raise ValueError(f"unknown snapshot kind: {kind!r}")

    console.print()
    print_note(
        console,
        "[dim]Δ: + new row, * changed, - gone (Note: why, `?` = a guess), (blank) unchanged.  "
        "History: \\[bracketed] = new since last snapshot.  "
        "Field!: value changed; prior value via `tkt snapshot diff`.  "
        "head!/review!/merge!: PR head commit, review decision or merge state changed.  "
        "Per-reviewer notes: requested / ↻ re-requested / approved on head / "
        "review now on old head / request removed / review dismissed.  "
        "Step notes: `step: old → new` (`pr list --steps`).[/]",
    )


def _print_summary(diff: DiffResult, *, console: Console) -> None:
    counts = diff.counts
    # Escape the literal `[` so Rich treats it as text, not a markup opener —
    # otherwise `[scope-changed]` renders as an empty unknown tag.
    scope_tag = "" if diff.scope_matches else r" [yellow]\[scope-changed][/]"
    prev, curr = diff.prev, diff.curr
    prev_when = relative_time(prev.captured_at)
    curr_when = relative_time(curr.captured_at)
    if prev.name == curr.name:
        span = f"{prev.kind}/{prev.name}: {prev_when} → {curr_when}"
    else:
        span = f"{prev.kind}/{prev.name} ({prev_when}) → {curr.name} ({curr_when})"
    header = (
        f"diff {span}  "
        f"([green]+{counts[ChangeKind.ADDED]}[/] new, "
        f"[yellow]*{counts[ChangeKind.CHANGED]}[/] changed, "
        f"[red]-{counts[ChangeKind.REMOVED]}[/] gone, "
        f"{counts[ChangeKind.UNCHANGED]} unchanged){scope_tag}"
    )
    print_note(console, header)
    if note := window_note(prev, curr):
        print_note(console, f"[dim]{note}[/]")


def window_note(prev: Snapshot, curr: Snapshot) -> str | None:
    """Name the date window, or what it changed from, so a scope change is explained."""
    prev_window, curr_window = prev.scope.window, curr.scope.window
    if prev_window == curr_window:
        return f"window: {curr_window.describe()}" if curr_window else None
    before = prev_window.describe() if prev_window else "none"
    after = curr_window.describe() if curr_window else "none"
    return f"window: {before} → {after}"


def _print_table(
    table: Table, rows: list[list[str]], *, console: Console, history_col: int
) -> None:
    """Print `table`; see `print_fitted_table` for the terminal and piped rules."""
    print_fitted_table(console, table, rows, history_col=history_col, floor=SHRINK_FLOOR)


def _print_pr_like_table(
    deltas: list[ItemDelta], *, console: Console, kind: str, detail: bool = False
) -> None:
    show_detail = detail and kind == "pr"
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Δ", no_wrap=True)
    add_shrinkable_column(table, "Repo", style="cyan")
    table.add_column("PR", justify="right", no_wrap=True)
    table.add_column("History", no_wrap=True)
    add_shrinkable_column(table, "CI")
    if show_detail:
        add_shrinkable_column(table, "Head")
        add_shrinkable_column(table, "Review")
        add_shrinkable_column(table, "Merge")
    if kind == "review":
        add_shrinkable_column(table, "Status")
    add_shrinkable_column(table, "State")
    table.add_column("💬", justify="right", no_wrap=True)
    table.add_column("Last", no_wrap=True)
    table.add_column("Note", no_wrap=True)

    rows = []
    for d in deltas:
        item = d.display_item
        row = [
            _KIND_GLYPH[d.kind],
            item.repo,
            f"#{item.number}",
            _render_history(item.history, d),
            _render_field(item.ci_status or "--", "ci_status" in d.changed_fields),
        ]
        if show_detail:
            changed = d.changed_fields
            row.extend(
                [
                    _render_field(short_sha(item.head_sha), "head_sha" in changed),
                    _render_field(review_label(item.review_decision), "review_decision" in changed),
                    _render_field(
                        merge_label(item.merge_state, item.mergeable),
                        bool(_MERGE_FIELDS.intersection(changed)),
                    ),
                ]
            )
        if kind == "review":
            row.append(
                _render_field(item.review_status or "--", "review_status" in d.changed_fields)
            )
        row.extend(
            [
                _render_field(item.state, "state" in d.changed_fields),
                _render_thread_count(item.unresolved_thread_count, d),
                _render_last_activity(item.last_activity, d),
                _render_note(d, show_pr_detail=not show_detail),
            ]
        )
        rows.append(row)

    _print_table(table, rows, console=console, history_col=3)


def _print_issue_table(deltas: list[ItemDelta], *, console: Console) -> None:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Δ", no_wrap=True)
    add_shrinkable_column(table, "Repo", style="cyan")
    table.add_column("Issue", justify="right", no_wrap=True)
    table.add_column("History", no_wrap=True)
    table.add_column("PR", no_wrap=True)
    add_shrinkable_column(table, "Labels", max_width=25)
    add_shrinkable_column(table, "State")
    table.add_column("Last", no_wrap=True)
    table.add_column("Note", no_wrap=True)

    rows = []
    for d in deltas:
        item = d.display_item
        rows.append(
            [
                _KIND_GLYPH[d.kind],
                item.repo,
                f"#{item.number}",
                _render_history(item.history, d),
                _render_linked_pr(item.linked_pr),
                _render_labels(item.labels, "labels" in d.changed_fields),
                _render_field(item.state, "state" in d.changed_fields),
                _render_last_activity(item.last_activity, d),
                _render_note(d),
            ]
        )

    _print_table(table, rows, console=console, history_col=3)


def _render_history(history: str, d: ItemDelta) -> str:
    """Format history with [bold magenta] bracketing the new tail.

    The literal `[` and `]` must be escaped (`\\[`, `\\]`) so Rich treats
    them as text and not as markup openers.
    """
    tail = d.new_history_tail
    if not tail or d.kind is ChangeKind.REMOVED:
        return history
    if d.kind is ChangeKind.ADDED:
        return f"[bold magenta]\\[{history}][/]"
    if tail == history:
        # history-rewritten: whole string is "new"
        return f"[bold magenta]\\[{history}][/]"
    if history.endswith(tail):
        head = history[: -len(tail)]
        return f"{head}[bold magenta]\\[{tail}][/]"
    # Unreachable: diff.diff_snapshots either returns tail == "" (no growth)
    # or tail that is a suffix of curr.history. Raise rather than silently
    # drop the user-requested bracketing.
    raise AssertionError(f"new_history_tail {tail!r} is not a suffix of history {history!r}")


def _render_field(value: str, changed: bool) -> str:
    if changed:
        return f"[yellow]{value}![/]"
    return value


def _render_thread_count(count: int, d: ItemDelta) -> str:
    changed = "unresolved_thread_count" in d.changed_fields
    text = "--" if count == 0 else str(count)
    return _render_field(text, changed)


def _render_last_activity(iso_timestamp: str, d: ItemDelta) -> str:
    return _render_field(relative_time(iso_timestamp), "activity" in d.changed_fields)


def _render_linked_pr(linked_pr: str | None) -> str:
    if not linked_pr:
        return "[dim]--[/]"
    if "#" in linked_pr:
        return f"[green]#{linked_pr.split('#')[1]}[/]"
    return f"[green]{linked_pr}[/]"


def _render_labels(labels: tuple[str, ...], changed: bool) -> str:
    text = ",".join(labels) if labels else "--"
    return _render_field(text, changed)


def relative_time(iso_timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return iso_timestamp
    now = datetime.now(UTC)
    secs = (now - dt).total_seconds()
    if secs < 60:
        return f"{int(secs)}s ago"
    if secs < 3600:
        return f"{int(secs / 60)}m ago"
    if secs < 86400:
        return f"{int(secs / 3600)}h ago"
    return f"{int(secs / 86400)}d ago"


def _render_note(d: ItemDelta, *, show_pr_detail: bool = False) -> str:
    if d.kind is ChangeKind.REMOVED:
        label = _REMOVAL_LABEL.get(d.disappearance_reason or "", "?")
        return f"[dim]{label}[/]"
    notes: list[str] = []
    if "history-rewritten" in d.changed_fields:
        notes.append("(history rewritten)")
    if show_pr_detail:
        notes.extend(_pr_detail_tags(d.changed_fields))
    notes.extend(d.reviewer_changes)
    notes.extend(d.step_changes)
    return f"[dim]{'; '.join(notes)}[/]" if notes else ""


def _pr_detail_tags(changed_fields: tuple[str, ...]) -> list[str]:
    """`head!` / `review!` / `merge!` for the PR fields that changed.

    Without `--detail` there is no column to carry the `!`, so the Note does.
    """
    tags = []
    if "head_sha" in changed_fields:
        tags.append("head!")
    if "review_decision" in changed_fields:
        tags.append("review!")
    if _MERGE_FIELDS.intersection(changed_fields):
        tags.append("merge!")
    return tags
