"""Shared date-window filtering for pr/issue/review listings.

Translates the CLI date-window options (``--since`` / ``--after`` /
``--before`` / ``--date-field``) into a GitHub search date qualifier such as
``merged:>=2026-08-25`` or ``created:2026-08-01..2026-08-25`` so that
listings can be restricted to a recent time window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

VALID_DATE_FIELDS = ("created", "updated", "merged", "closed")


class DateWindowError(ValueError):
    """Raised when date-window options are invalid or inconsistent."""


def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD string into a date, raising DateWindowError."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise DateWindowError(f"Invalid date '{value}': expected YYYY-MM-DD format") from None


def resolve_date_field(states: list[str] | None, explicit: str | None = None) -> str:
    """Pick the search date field to filter on.

    An explicit ``--date-field`` always wins. Otherwise the field is inferred
    from the states being queried: a lone ``merged`` or ``closed`` listing uses
    the matching field, everything else falls back to ``updated``.
    """
    if explicit:
        if explicit not in VALID_DATE_FIELDS:
            raise DateWindowError(
                f"Invalid date field '{explicit}': choose from {', '.join(VALID_DATE_FIELDS)}"
            )
        return explicit

    states_set = {s.lower() for s in (states or [])}
    if states_set == {"merged"}:
        return "merged"
    if states_set == {"closed"}:
        return "closed"
    return "updated"


def _check_field_can_match(field: str, states: list[str] | None, *, merged_ok: bool) -> None:
    """Reject an explicit --date-field that the queried states can never have."""
    states_set = {s.lower() for s in (states or [])} or {"open"}
    if field == "merged" and not merged_ok:
        raise DateWindowError(
            "Issues have no merged date: use --date-field created, updated or closed"
        )
    if field == "merged" and "merged" not in states_set:
        raise DateWindowError(
            "--date-field merged only matches merged items, but the state filter "
            f"is {'/'.join(sorted(states_set))}: add --merged"
        )
    if field == "closed" and not states_set & {"closed", "merged"}:
        raise DateWindowError(
            "--date-field closed only matches closed items, but the state filter "
            f"is {'/'.join(sorted(states_set))}: add --closed (or --merged)"
        )


@dataclass(frozen=True)
class DateWindow:
    """A resolved date window expressed as a GitHub search qualifier."""

    field: str
    after: date | None = None
    before: date | None = None
    # As typed for a relative window. `after` is resolved against today's UTC
    # date, so snapshots record this instead to stay comparable day to day.
    since_days: int | None = None

    def describe(self) -> str:
        """Short human-readable form, e.g. ``merged ≥ 2026-08-25``."""
        if self.after and self.before:
            return f"{self.field} {self.after.isoformat()}..{self.before.isoformat()}"
        if self.after:
            return f"{self.field} ≥ {self.after.isoformat()}"
        if self.before:
            return f"{self.field} ≤ {self.before.isoformat()}"
        return self.field

    def to_qualifier(self) -> str:
        """Render this window as a GitHub search qualifier string."""
        if self.after and self.before:
            return f"{self.field}:{self.after.isoformat()}..{self.before.isoformat()}"
        if self.after:
            return f"{self.field}:>={self.after.isoformat()}"
        if self.before:
            return f"{self.field}:<={self.before.isoformat()}"
        return ""


def build_date_window(
    states: list[str] | None,
    *,
    since_days: int | None = None,
    after: str | None = None,
    before: str | None = None,
    date_field: str | None = None,
    refs: list[str] | None = None,
    merged_ok: bool = True,
    now: datetime | None = None,
) -> DateWindow | None:
    """Build a DateWindow from the raw CLI options.

    Args:
        states: The states being queried (used to infer the date field).
        since_days: Relative window - include items from the start of the UTC
            calendar day N days ago (``0`` means today, UTC).
        after: Absolute lower bound (YYYY-MM-DD, inclusive).
        before: Absolute upper bound (YYYY-MM-DD, inclusive).
        date_field: Explicit field override (created/updated/merged/closed).
        refs: Explicit item references; a window cannot narrow these.
        merged_ok: False for item kinds that cannot be merged (issues).
        now: Reference time for ``since_days`` (defaults to current UTC time).

    Returns:
        A DateWindow, or None when no window options were supplied.

    Raises:
        DateWindowError: The options are invalid, contradict each other, or
            cannot take effect (``--date-field`` alone, a window with refs).
    """
    window_flags = [
        flag
        for flag, value in (("--since", since_days), ("--after", after), ("--before", before))
        if value is not None
    ]
    if not window_flags:
        if date_field:
            raise DateWindowError("--date-field needs --since, --after or --before")
        return None

    if refs:
        flags = "/".join(window_flags)
        raise DateWindowError(
            f"{flags} cannot narrow explicit refs (they list exactly the items named).\n"
            f"Drop the refs to search by date, or drop {flags}."
        )

    if since_days is not None and (after is not None or before is not None):
        raise DateWindowError("--since cannot be combined with --after/--before")

    field = resolve_date_field(states, date_field)
    if date_field:
        _check_field_can_match(field, states, merged_ok=merged_ok)

    after_date: date | None = None
    before_date: date | None = None

    if since_days is not None:
        if since_days < 0:
            raise DateWindowError("--since must be a non-negative number of days")
        base = now or datetime.now(tz=UTC)
        after_date = (base - timedelta(days=since_days)).date()

    if after is not None:
        after_date = _parse_date(after)
    if before is not None:
        before_date = _parse_date(before)

    if after_date and before_date and after_date > before_date:
        raise DateWindowError("--after date must not be later than --before date")

    return DateWindow(field=field, after=after_date, before=before_date, since_days=since_days)


def window_suffix(window: DateWindow | None) -> str:
    """Parenthetical naming the window, for appending to a message ("" if none)."""
    return f" ({window.describe()}, UTC)" if window else ""


def window_line(window: DateWindow) -> str:
    """One-line reminder of the window a listing was filtered by."""
    return f"Window: {window.describe()} (UTC)"
