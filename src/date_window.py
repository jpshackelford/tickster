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


@dataclass(frozen=True)
class DateWindow:
    """A resolved date window expressed as a GitHub search qualifier."""

    field: str
    after: date | None = None
    before: date | None = None

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
    now: datetime | None = None,
) -> DateWindow | None:
    """Build a DateWindow from the raw CLI options.

    Args:
        states: The states being queried (used to infer the date field).
        since_days: Relative window - include items within the last N days.
        after: Absolute lower bound (YYYY-MM-DD, inclusive).
        before: Absolute upper bound (YYYY-MM-DD, inclusive).
        date_field: Explicit field override (created/updated/merged/closed).
        now: Reference time for ``since_days`` (defaults to current UTC time).

    Returns:
        A DateWindow, or None when no window options were supplied.
    """
    if since_days is None and after is None and before is None:
        # No window requested; --date-field on its own is a harmless no-op.
        return None

    if since_days is not None and (after is not None or before is not None):
        raise DateWindowError("--since cannot be combined with --after/--before")

    field = resolve_date_field(states, date_field)

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

    return DateWindow(field=field, after=after_date, before=before_date)


def build_date_qualifier(
    states: list[str] | None,
    *,
    since_days: int | None = None,
    after: str | None = None,
    before: str | None = None,
    date_field: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Convenience wrapper returning the qualifier string (or None)."""
    window = build_date_window(
        states,
        since_days=since_days,
        after=after,
        before=before,
        date_field=date_field,
        now=now,
    )
    if window is None:
        return None
    qualifier = window.to_qualifier()
    return qualifier or None
