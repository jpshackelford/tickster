"""Validation for `--no-pr` / `--has-pr` on `tkt issue list`."""

PR_FILTER_LABEL = {"no-pr": "--no-pr", "has-pr": "--has-pr"}


def pr_filter_error(pr_filter: str | None, *, has_refs: bool) -> str | None:
    """Return why the PR filter can't run with these inputs, or None if it can."""
    if pr_filter and has_refs:
        flag = PR_FILTER_LABEL[pr_filter]
        return (
            f"{flag} cannot be combined with explicit refs: refs list exactly the issues "
            f"named. Drop the refs, or drop {flag}."
        )
    return None
