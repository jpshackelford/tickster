"""`tkt snapshot` subcommand implementations.

Users invoke these via `tkt snapshot {list, show, rm, diff}`. They
operate purely on the on-disk store under `~/.tkt/snapshots/` and never
touch the GitHub API.
"""

from __future__ import annotations

import json
import logging

from rich import box
from rich.console import Console
from rich.table import Table

from src.snapshot import diff as diff_module
from src.snapshot import render, store
from src.snapshot.models import VALID_KINDS

console = Console()
logger = logging.getLogger(__name__)


def _parse_ref(ref: str) -> tuple[str, str]:
    """Parse a `kind/name` ref into `(kind, name)`."""
    if "/" not in ref:
        raise ValueError(f"snapshot ref must be in KIND/NAME form (e.g. pr/hourly); got {ref!r}")
    kind, _, name = ref.partition("/")
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown snapshot kind {kind!r}; expected one of {VALID_KINDS}")
    if not name:
        raise ValueError(f"snapshot name is empty in ref {ref!r}")
    return kind, name


def cmd_list(*, kind: str | None = None) -> int:
    """List all stored snapshots, optionally filtered by `kind`."""
    records = store.list_(kind)
    if not records:
        console.print("[dim]No snapshots stored.[/]")
        return 0

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Ref", no_wrap=True)
    table.add_column("Captured at", no_wrap=True)
    table.add_column("Items", justify="right", no_wrap=True)
    table.add_column("Scope#", no_wrap=True)
    for r in records:
        table.add_row(
            f"{r.kind}/{r.name}",
            r.captured_at,
            str(r.item_count),
            r.scope_hash,
        )
    console.print(table)
    return 0


def cmd_show(ref: str, *, output_format: str = "table") -> int:
    """Dump a single snapshot. `output_format` ∈ {table, json}."""
    try:
        kind, name = _parse_ref(ref)
    except ValueError as e:
        console.print(f"[red]Error:[/] {e}")
        return 2
    try:
        snap = store.load(kind, name)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        return 1

    if output_format == "json":
        print(json.dumps(snap.to_dict(), indent=2))
        return 0

    console.print(
        f"[bold]{snap.kind}/{snap.name}[/]  "
        f"captured_at={snap.captured_at}  "
        f"scope#{snap.scope_hash}  "
        f"items={len(snap.items)}"
    )
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Repo", style="cyan", no_wrap=True)
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("History", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Last activity", no_wrap=True)
    for it in snap.items:
        table.add_row(it.repo, str(it.number), it.history, it.state, it.last_activity)
    console.print(table)
    return 0


def cmd_rm(refs: list[str]) -> int:
    """Delete one or more snapshots.

    Exit code reports the most severe failure across all refs so the
    result is independent of argv ordering: 2 if any ref failed to parse,
    1 if any (otherwise-valid) ref was not found, 0 on complete success.
    """
    exit_code = 0
    for ref in refs:
        try:
            kind, name = _parse_ref(ref)
        except ValueError as e:
            console.print(f"[red]Error:[/] {e}")
            exit_code = max(exit_code, 2)
            continue
        if store.delete(kind, name):
            console.print(f"removed {kind}/{name}")
        else:
            console.print(f"[yellow]not found:[/] {kind}/{name}")
            exit_code = max(exit_code, 1)
    return exit_code


def cmd_diff(
    prev_ref: str,
    curr_ref: str,
    *,
    show_unchanged: bool = False,
    output_format: str = "table",
) -> int:
    """Diff two stored snapshots (`kind/name`)."""
    try:
        p_kind, p_name = _parse_ref(prev_ref)
        c_kind, c_name = _parse_ref(curr_ref)
    except ValueError as e:
        console.print(f"[red]Error:[/] {e}")
        return 2
    if p_kind != c_kind:
        console.print(f"[red]Error:[/] cannot diff across kinds ({prev_ref} vs {curr_ref})")
        return 2
    try:
        prev = store.load(p_kind, p_name)
        curr = store.load(c_kind, c_name)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        return 1
    result = diff_module.diff_snapshots(prev, curr)
    render.render_diff(
        result,
        console=console,
        show_unchanged=show_unchanged,
        output_format=output_format,
    )
    return 0
