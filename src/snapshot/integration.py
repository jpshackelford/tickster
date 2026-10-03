"""Shared snapshot/diff/watch integration for list commands.

The three list commands (`pr list`, `issue list`, `review`) all build a
collection of info objects, print a table, and then exit. This module gives
them one helper that decides — based on `--snapshot` / `--diff` / `--watch`
— whether to also diff against a stored snapshot and/or persist the result.

Call sites look like:

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
        curr = snapshot_from_prs(result.prs, scope=scope, name=...)
        return plan.execute(curr, console, print_table=lambda: _print_table(result))

The plan must run even when the query returned no rows: an empty current
snapshot is how `--watch` reports that the last item in scope went away.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from rich.console import Console

from src.snapshot import diff as diff_module
from src.snapshot import render as render_module
from src.snapshot import store
from src.snapshot.models import VALID_KINDS, Snapshot


@dataclass(frozen=True)
class SnapshotPlan:
    """Decoded intent from `--snapshot`, `--diff`, `--watch` flags."""

    kind: str
    diff_name: str | None
    save_name: str | None  # when set, we persist with this name
    output_format: str = "table"
    show_unchanged: bool = False
    force: bool = False

    @property
    def wants_diff(self) -> bool:
        return self.diff_name is not None

    @property
    def wants_save(self) -> bool:
        return self.save_name is not None

    @classmethod
    def from_args(
        cls,
        *,
        kind: str,
        snapshot_name: str | None,
        diff_name: str | None,
        watch_name: str | None,
        output_format: str = "table",
        show_unchanged: bool = False,
        force: bool = False,
    ) -> SnapshotPlan | None:
        """Build a plan from parsed CLI arguments, or None if no snapshot work.

        Mutual-exclusion rules:

        - `--watch` is `--diff + --snapshot` under the same name; cannot be
          combined with either.
        - `--snapshot` and `--diff` may be combined (save then diff).

        CLI call sites should validate these up-front via
        `_validate_snapshot_args(parser, args)` so argparse's `parser.error`
        formats the message; this method still raises `ValueError` so
        library/test callers get a usable exception.
        """
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid snapshot kind: {kind!r}")
        if watch_name is not None:
            if snapshot_name is not None or diff_name is not None:
                raise ValueError("--watch cannot be combined with --snapshot or --diff")
            diff = watch_name
            save = watch_name
        else:
            diff = diff_name
            save = snapshot_name
        if diff is None and save is None:
            return None
        return cls(
            kind=kind,
            diff_name=diff,
            save_name=save,
            output_format=output_format,
            show_unchanged=show_unchanged,
            force=force,
        )

    def execute(self, curr: Snapshot, console: Console, print_table: Callable[[], None]) -> int:
        """Diff and/or save `curr` per the plan. Returns exit code.

        With a diff, the diff output replaces the normal table, and the
        baseline is only overwritten when the diff succeeded so that a
        scope-mismatch error is safe to retry with `--diff-force`.
        """
        if self.wants_diff:
            rc = self.render_diff(curr, console)
            if rc == 0 and self.wants_save:
                self.save(curr)
            return rc
        print_table()
        self.save(curr)
        return 0

    def render_diff(self, curr: Snapshot, console: Console) -> int:
        """Load the baseline, diff, render. Returns exit code."""
        if self.diff_name is None:
            raise RuntimeError("render_diff called without --diff / --watch")
        try:
            prev = store.load(self.kind, self.diff_name)
        except FileNotFoundError:
            # First run: no baseline yet. The diff is "everything is new".
            # Rather than fail, we tell the user and print the normal table.
            console.print(
                f"[yellow]No snapshot {self.kind}/{self.diff_name} found; "
                "treating all current rows as new.[/]"
            )
            prev = Snapshot.make(kind=self.kind, name=self.diff_name, scope=curr.scope, items=[])
        result = diff_module.diff_snapshots(prev, curr)
        if not result.scope_matches and not self.force:
            console.print(
                "[red]Error:[/] scope mismatch between snapshots "
                "(use --diff-force to proceed anyway)"
            )
            return 2
        render_module.render_diff(
            result,
            console=console,
            show_unchanged=self.show_unchanged,
            output_format=self.output_format,
        )
        return 0

    def save(self, snapshot: Snapshot) -> None:
        """Persist `snapshot` under the configured save name."""
        if self.save_name is None:
            raise RuntimeError("save called without --snapshot / --watch")
        store.save(replace(snapshot, name=self.save_name))
