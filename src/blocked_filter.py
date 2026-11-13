"""Validation for `--blocked` / `--unblocked` on `tkt issue list`."""

BLOCKED_FILTER_LABEL = {"blocked": "--blocked", "unblocked": "--unblocked"}


def blocked_filter_error(blocked_filter: str | None, *, has_refs: bool) -> str | None:
    """Return why the blocked filter can't run with these inputs, or None if it can."""
    if blocked_filter and has_refs:
        flag = BLOCKED_FILTER_LABEL[blocked_filter]
        return (
            f"{flag} cannot be combined with explicit refs: refs list exactly the issues "
            f"named. Drop the refs, or drop {flag}."
        )
    return None
