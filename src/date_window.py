"""Shared date-window filtering for pr/issue/review listings.

Translates the CLI date-window options (``--since`` / ``--after`` /
``--before`` / ``--date-field``) into a GitHub search date qualifier such as
``merged:>=2026-08-25`` or ``created:2026-08-01..2026-08-25`` so that
listings can be restricted to a recent time window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

VALID_DATE_FIELDS = ("created", "updated", "merged", "closed")
ISSUE_DATE_FIELDS = ("created", "updated", "closed")
PR_DATE_FIELDS = VALID_DATE_FIELDS
REVIEW_DATE_FIELDS = VALID_DATE_FIELDS
FIELD_FLAG_KINDS = ("since", "after", "before")
DEFAULT_FLAG_NAMES: Mapping[str, str] = {
    "since": "--since",
    "after": "--after",
    "before": "--before",
}


class DateWindowError(ValueError):
    """Raised when date-window options are invalid or inconsistent."""


def _parse_date(value: str, flag: str | None = None) -> date:
    """Parse a YYYY-MM-DD string into a date, raising DateWindowError."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        where = f" for {flag}" if flag else ""
        raise DateWindowError(
            f"Invalid date '{value}'{where}: expected YYYY-MM-DD format"
        ) from None


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


def _check_field_can_match(
    field: str,
    states: list[str] | None,
    *,
    merged_ok: bool,
    typed_flag: str | None = None,
    has_all_flag: bool = True,
) -> None:
    """Reject an explicit date field that the queried states can never have.

    ``typed_flag`` is the per-field flag the user typed (``--closed-since``);
    without it the message names ``--date-field``. ``has_all_flag`` is False
    where ``--all`` does not widen the states, so errors must not suggest it.
    """
    states_set = {s.lower() for s in (states or [])} or {"open"}
    state_text = "/".join(sorted(states_set))
    if field == "merged" and not merged_ok:
        raise DateWindowError(
            "Issues have no merged date: use --date-field created, updated or closed"
        )
    if field == "merged" and "merged" not in states_set:
        name = typed_flag or "--date-field merged"
        remedy = "add --merged (or --all)" if typed_flag and has_all_flag else "add --merged"
        raise DateWindowError(
            f"{name} only matches merged items, but the state filter is {state_text}: {remedy}"
        )
    if field == "closed" and not states_set & {"closed", "merged"}:
        name = typed_flag or "--date-field closed"
        if not typed_flag or not has_all_flag:
            remedy = "add --closed (or --merged)"
        elif merged_ok:
            remedy = "add --closed, --merged or --all"
        else:
            remedy = "add --closed (or --all)"
        raise DateWindowError(
            f"{name} only matches closed items, but the state filter is {state_text}: {remedy}"
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
    flag_names: Mapping[str, str] | None = None,
    has_all_flag: bool = True,
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
        flag_names: The flags the user typed, keyed ``since``/``after``/``before``,
            so errors name them. Set when the window came from per-field flags
            such as ``--created-since``; ``date_field`` is then explicit.
        has_all_flag: False when ``--all`` does not widen the states (``review``),
            so state errors don't suggest it.

    Returns:
        A DateWindow, or None when no window options were supplied.

    Raises:
        DateWindowError: The options are invalid, contradict each other, or
            cannot take effect (``--date-field`` alone, a window with refs).
    """
    names = flag_names or DEFAULT_FLAG_NAMES
    window_flags = [
        names[kind]
        for kind, value in (("since", since_days), ("after", after), ("before", before))
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
        if flag_names:
            bounds = "/".join(
                flag_names[kind]
                for kind, value in (("after", after), ("before", before))
                if value is not None
            )
        else:
            bounds = "--after/--before"
        raise DateWindowError(f"{names['since']} cannot be combined with {bounds}")

    field = resolve_date_field(states, date_field)
    if date_field:
        _check_field_can_match(
            field,
            states,
            merged_ok=merged_ok,
            typed_flag=window_flags[0] if flag_names else None,
            has_all_flag=has_all_flag,
        )

    after_date: date | None = None
    before_date: date | None = None

    if since_days is not None:
        if since_days < 0:
            raise DateWindowError(f"{names['since']} must be a non-negative number of days")
        base = now or datetime.now(tz=UTC)
        after_date = (base - timedelta(days=since_days)).date()

    if after is not None:
        after_date = _parse_date(after, flag_names["after"] if flag_names else None)
    if before is not None:
        before_date = _parse_date(before, flag_names["before"] if flag_names else None)

    if after_date and before_date and after_date > before_date:
        raise DateWindowError(
            f"{names['after']} date must not be later than {names['before']} date"
        )

    return DateWindow(field=field, after=after_date, before=before_date, since_days=since_days)


@dataclass(frozen=True)
class ResolvedDateFlags:
    """The ``build_date_window`` inputs behind a set of date flags."""

    since_days: int | None = None
    after: str | None = None
    before: str | None = None
    date_field: str | None = None
    flag_names: Mapping[str, str] | None = None


def field_flag(field: str, kind: str) -> str:
    """The per-field flag spelling, e.g. ``--created-since``."""
    return f"--{field}-{kind}"


def field_flag_dest(field: str, kind: str) -> str:
    """The argparse dest of a per-field flag, e.g. ``created_since``."""
    return f"{field}_{kind}"


def resolve_field_flags(
    fields: Sequence[str],
    field_values: Mapping[str, int | str | None],
    *,
    since_days: int | None = None,
    after: str | None = None,
    before: str | None = None,
    date_field: str | None = None,
) -> ResolvedDateFlags:
    """Map per-field flags (``--created-since`` ...) onto ``build_date_window`` inputs.

    Args:
        fields: The date fields that offer per-field flags.
        field_values: Parsed per-field values keyed by dest (``created_since``).
        since_days, after, before, date_field: The old, unscoped flags.

    Raises:
        DateWindowError: Per-field flags are mixed with the old flags, or name
            more than one date field.
    """
    typed: dict[str, list[str]] = {}
    values: dict[str, int | str | None] = {}
    for field in fields:
        for kind in FIELD_FLAG_KINDS:
            value = field_values.get(field_flag_dest(field, kind))
            if value is not None:
                typed.setdefault(field, []).append(field_flag(field, kind))
                values[kind] = value

    old_typed = [
        flag
        for flag, value in (
            ("--since", since_days),
            ("--after", after),
            ("--before", before),
            ("--date-field", date_field),
        )
        if value is not None
    ]
    if not typed:
        return ResolvedDateFlags(since_days, after, before, date_field)

    if old_typed:
        first_new = next(iter(typed.values()))[0]
        raise DateWindowError(
            f"{first_new} cannot be combined with {old_typed[0]}: "
            "use the per-field flags or the old flags, not both"
        )
    if len(typed) > 1:
        named = " and ".join(flags[0] for flags in typed.values())
        raise DateWindowError(
            f"{named} name different date fields: filter on one date field per query"
        )

    (field,) = typed
    since_value, after_value, before_value = (values.get(k) for k in FIELD_FLAG_KINDS)
    return ResolvedDateFlags(
        since_days=since_value if isinstance(since_value, int) else None,
        after=after_value if isinstance(after_value, str) else None,
        before=before_value if isinstance(before_value, str) else None,
        date_field=field,
        flag_names={kind: field_flag(field, kind) for kind in FIELD_FLAG_KINDS},
    )


def window_suffix(window: DateWindow | None) -> str:
    """Parenthetical naming the window, for appending to a message ("" if none)."""
    return f" ({window.describe()}, UTC)" if window else ""


def window_line(window: DateWindow) -> str:
    """One-line reminder of the window a listing was filtered by."""
    return f"Window: {window.describe()} (UTC)"
