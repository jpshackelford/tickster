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
from datetime import datetime

from rich import box
from rich.console import Console
from rich.table import Table

from src.snapshot.models import ChangeKind, DiffResult, ItemDelta, ItemSnapshot

_KIND_GLYPH = {
    ChangeKind.ADDED: "[green]+[/]",
    ChangeKind.CHANGED: "[yellow]*[/]",
    ChangeKind.REMOVED: "[red]-[/]",
    ChangeKind.UNCHANGED: " ",
}


def render_diff(
    diff: DiffResult,
    *,
    console: Console | None = None,
    show_unchanged: bool = False,
    output_format: str = "table",
) -> None:
    """Render a diff to the console. `output_format` ∈ {"table", "json"}."""
    console = console or Console()
    if output_format == "json":
        console.print_json(json.dumps(diff.to_dict()))
        return
    if output_format != "table":
        raise ValueError(f"unknown diff output format: {output_format!r}")

    _print_summary(diff, console=console)
    deltas = [d for d in diff.deltas if show_unchanged or d.kind is not ChangeKind.UNCHANGED]
    if not deltas:
        console.print("[dim]No changes.[/]")
        return

    kind = diff.curr.kind
    if kind == "pr" or kind == "review":
        _print_pr_like_table(deltas, console=console, kind=kind)
    elif kind == "issue":
        _print_issue_table(deltas, console=console)
    else:  # pragma: no cover — guarded upstream
        raise ValueError(f"unknown snapshot kind: {kind!r}")

    console.print()
    console.print(
        "[dim]Δ: + new row, * changed, - gone, (blank) unchanged.  "
        "History: \\[bracketed] = new since last snapshot.  "
        "Field!: value changed; prior value via `tkt snapshot diff`.[/]"
    )


def _print_summary(diff: DiffResult, *, console: Console) -> None:
    counts = diff.counts
    scope_tag = "" if diff.scope_matches else " [yellow][scope-changed][/]"
    header = (
        f"diff: {diff.prev.kind}/{diff.prev.name} @ {diff.prev.captured_at} → "
        f"{diff.curr.name} @ {diff.curr.captured_at}  "
        f"([green]+{counts[ChangeKind.ADDED]}[/] new, "
        f"[yellow]*{counts[ChangeKind.CHANGED]}[/] changed, "
        f"[red]-{counts[ChangeKind.REMOVED]}[/] gone, "
        f"{counts[ChangeKind.UNCHANGED]} unchanged){scope_tag}"
    )
    console.print(header)


def _print_pr_like_table(deltas: list[ItemDelta], *, console: Console, kind: str) -> None:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Δ", no_wrap=True)
    table.add_column("Repo", style="cyan", no_wrap=True)
    table.add_column("PR" if kind == "pr" else "PR", justify="right", no_wrap=True)
    table.add_column("History", no_wrap=True)
    table.add_column("CI", no_wrap=True)
    if kind == "review":
        table.add_column("Status", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("💬", justify="right", no_wrap=True)
    table.add_column("Last", no_wrap=True)
    table.add_column("Note", no_wrap=True)

    for d in deltas:
        item = d.display_item
        row = [
            _KIND_GLYPH[d.kind],
            item.repo,
            f"#{item.number}",
            _render_history(item.history, d),
            _render_field(item.ci_status or "--", "ci_status" in d.changed_fields),
        ]
        if kind == "review":
            row.append(
                _render_field(item.review_status or "--", "review_status" in d.changed_fields)
            )
        row.extend(
            [
                _render_field(item.state, "state" in d.changed_fields),
                _render_thread_count(item.unresolved_thread_count, d),
                _render_last_activity(item.last_activity),
                _render_note(d),
            ]
        )
        table.add_row(*row)

    console.print(table)


def _print_issue_table(deltas: list[ItemDelta], *, console: Console) -> None:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Δ", no_wrap=True)
    table.add_column("Repo", style="cyan", no_wrap=True)
    table.add_column("Issue", justify="right", no_wrap=True)
    table.add_column("History", no_wrap=True)
    table.add_column("PR", no_wrap=True)
    table.add_column("Labels", no_wrap=True, overflow="ellipsis", max_width=25)
    table.add_column("State", no_wrap=True)
    table.add_column("Last", no_wrap=True)
    table.add_column("Note", no_wrap=True)

    for d in deltas:
        item = d.display_item
        table.add_row(
            _KIND_GLYPH[d.kind],
            item.repo,
            f"#{item.number}",
            _render_history(item.history, d),
            _render_linked_pr(item.linked_pr),
            _render_labels(item.labels, "labels" in d.changed_fields),
            _render_field(item.state, "state" in d.changed_fields),
            _render_last_activity(item.last_activity),
            _render_note(d),
        )

    console.print(table)


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
    return history  # defensive; shouldn't reach


def _render_field(value: str, changed: bool) -> str:
    if changed:
        return f"[yellow]{value}![/]"
    return value


def _render_thread_count(count: int, d: ItemDelta) -> str:
    changed = "unresolved_thread_count" in d.changed_fields
    text = "--" if count == 0 else str(count)
    return _render_field(text, changed)


def _render_linked_pr(linked_pr: str | None) -> str:
    if not linked_pr:
        return "[dim]--[/]"
    if "#" in linked_pr:
        return f"[green]#{linked_pr.split('#')[1]}[/]"
    return f"[green]{linked_pr}[/]"


def _render_labels(labels: tuple[str, ...], changed: bool) -> str:
    text = ",".join(labels) if labels else "--"
    return _render_field(text, changed)


def _render_last_activity(iso_timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return iso_timestamp
    from datetime import UTC

    now = datetime.now(UTC)
    secs = (now - dt).total_seconds()
    if secs < 60:
        return f"{int(secs)}s ago"
    if secs < 3600:
        return f"{int(secs / 60)}m ago"
    if secs < 86400:
        return f"{int(secs / 3600)}h ago"
    return f"{int(secs / 86400)}d ago"


def _render_note(d: ItemDelta) -> str:
    if d.kind is ChangeKind.REMOVED:
        reason = d.disappearance_reason or "gone"
        return f"[dim](gone: {reason})[/]"
    if "history-rewritten" in d.changed_fields:
        return "[dim](history rewritten)[/]"
    return ""


# Suppress unused-import warning on ItemSnapshot (kept for type context)
_ = ItemSnapshot
