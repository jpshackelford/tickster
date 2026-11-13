"""Shared snapshot/diff/watch/JSON integration for list commands.

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
        output_format=output_format,
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
from src.snapshot.models import VALID_KINDS, ChangeKind, DiffResult, Snapshot
from src.snapshot.resolve import FetchByRef, resolve_removed

EnrichDiff = Callable[[DiffResult], DiffResult]

EXIT_CHANGED = 10


def _without_steps(snapshot: Snapshot) -> Snapshot:
    return replace(snapshot, items=tuple(replace(it, step_status=None) for it in snapshot.items))


@dataclass(frozen=True)
class SnapshotPlan:
    """Decoded intent from `--snapshot`, `--diff`, `--watch` and `--format` flags."""

    kind: str
    diff_name: str | None
    save_name: str | None  # when set, we persist with this name
    output_format: str = "table"
    show_unchanged: bool = False
    force: bool = False
    detail: bool = False
    resolve: bool = False
    show_steps: bool = False  # `pr list --steps`: the table reports step moves
    exit_code: bool = False  # `--exit-code`: a diff with a changed row exits EXIT_CHANGED

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
        detail: bool = False,
        resolve: bool = False,
        show_steps: bool = False,
        exit_code: bool = False,
    ) -> SnapshotPlan | None:
        """Build a plan from parsed CLI arguments, or None if there is nothing to do.

        `--format json` always yields a plan, so a plain list prints the
        current result as the snapshot document.

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
        if exit_code and diff is None:
            raise ValueError("--exit-code needs --diff or --watch")
        if diff is None and save is None and output_format != "json":
            return None
        return cls(
            kind=kind,
            diff_name=diff,
            save_name=save,
            output_format=output_format,
            show_unchanged=show_unchanged,
            force=force,
            detail=detail,
            resolve=resolve,
            show_steps=show_steps,
            exit_code=exit_code,
        )

    def execute(
        self,
        curr: Snapshot,
        console: Console,
        print_table: Callable[[], None],
        fetch_by_ref: FetchByRef | None = None,
        enrich: EnrichDiff | None = None,
    ) -> int:
        """Diff and/or save `curr` per the plan. Returns exit code.

        `fetch_by_ref` looks up gone rows when the plan has `resolve` set.
        `enrich` adds per-row evidence to a JSON diff.

        With a diff, the diff output replaces the normal table, and the
        baseline is only overwritten when the diff succeeded (exit 0, or exit
        `EXIT_CHANGED` under `--exit-code`) so that a
        scope-mismatch error is safe to retry with `--diff-force`. A bare
        `--diff NAME` leaves the baseline alone and stages `curr` as the
        pending baseline for `tkt snapshot ack`.

        Without a diff, `--format json` prints `curr` as a snapshot document
        (the same one `tkt snapshot show --format json` prints) instead of
        the table.
        """
        if self.wants_diff:
            rc = self.render_diff(curr, console, fetch_by_ref, enrich)
            if rc in (0, EXIT_CHANGED):
                if self.wants_save:
                    self.save(curr)
                elif self.diff_name is not None:
                    store.save_pending(replace(curr, name=self.diff_name))
            return rc
        if self.output_format == "json":
            saved = self.save(curr) if self.wants_save else curr
            print(saved.to_json())
        else:
            print_table()
            if self.wants_save:
                self.save(curr)
        return 0

    def render_diff(
        self,
        curr: Snapshot,
        console: Console,
        fetch_by_ref: FetchByRef | None = None,
        enrich: EnrichDiff | None = None,
    ) -> int:
        """Load the baseline, diff, render. Returns exit code.

        With `exit_code` set, returns `EXIT_CHANGED` instead of 0 when any row
        is added, changed or removed.
        """
        if self.diff_name is None:
            raise RuntimeError("render_diff called without --diff / --watch")
        # In JSON mode stdout must hold only the document, so notices go to stderr.
        msg = Console(stderr=True) if self.output_format == "json" else console
        baseline_found = True
        try:
            prev = store.load(self.kind, self.diff_name)
        except FileNotFoundError:
            # First run: no baseline yet. The diff is "everything is new".
            # Rather than fail, we tell the user and print the normal table.
            msg.print(
                f"[yellow]No snapshot {self.kind}/{self.diff_name} found; "
                "treating all current rows as new.[/]"
            )
            prev = Snapshot.make(kind=self.kind, name=self.diff_name, scope=curr.scope, items=[])
            baseline_found = False
        if self.output_format == "table" and not self.show_steps:
            # Snapshots always record step statuses; the table reports a move only with --steps.
            prev, curr = _without_steps(prev), _without_steps(curr)
        result = replace(diff_module.diff_snapshots(prev, curr), baseline_found=baseline_found)
        if self.resolve:
            if fetch_by_ref is None:
                raise RuntimeError("--diff-resolve needs a fetch_by_ref")
            result = resolve_removed(result, fetch_by_ref)
        if not result.scope_matches and not self.force:
            msg.print(
                "[red]Error:[/] scope mismatch between snapshots "
                "(use --diff-force to proceed anyway)"
            )
            if prev.scope.window != curr.scope.window:
                msg.print(f"[dim]{render_module.window_note(prev, curr)}[/]")
            if prev.scope.pr_filter != curr.scope.pr_filter:
                msg.print(f"[dim]{render_module.pr_filter_note(prev, curr)}[/]")
            if prev.scope.blocked_filter != curr.scope.blocked_filter:
                msg.print(f"[dim]{render_module.blocked_filter_note(prev, curr)}[/]")
            if prev.scope.sort != curr.scope.sort:
                msg.print(f"[dim]{render_module.sort_note(prev, curr)}[/]")
            return 2
        if enrich is not None and self.output_format == "json":
            result = enrich(result)
        render_module.render_diff(
            result,
            console=console,
            show_unchanged=self.show_unchanged,
            output_format=self.output_format,
            detail=self.detail,
        )
        if self.exit_code and any(d.kind is not ChangeKind.UNCHANGED for d in result.deltas):
            return EXIT_CHANGED
        return 0

    def save(self, snapshot: Snapshot) -> Snapshot:
        """Persist `snapshot` under the configured save name; returns what was stored.

        A newer saved baseline supersedes any baseline staged for that name.
        """
        if self.save_name is None:
            raise RuntimeError("save called without --snapshot / --watch")
        saved = replace(snapshot, name=self.save_name)
        store.save(saved)
        store.delete_pending(snapshot.kind, self.save_name)
        return saved
