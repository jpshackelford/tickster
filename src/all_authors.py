"""Validation for `--all-authors` on `tkt pr list` / `tkt issue list`."""


def all_authors_error(*, has_refs: bool, repos: list[str] | None, noun: str) -> str | None:
    """Return why `--all-authors` can't run with these inputs, or None if it can.

    Args:
        has_refs: Explicit owner/repo#N refs were given.
        repos: Repos the search would be scoped to (explicit or from the board).
        noun: "issues" or "PRs", for the message.
    """
    if has_refs:
        return (
            f"--all-authors cannot be combined with explicit refs: refs list exactly the "
            f"{noun} named. Drop the refs to list every author's {noun}, or drop --all-authors."
        )
    if not repos:
        return (
            "--all-authors needs repos to search: pass --repo OWNER/REPO, or --board NAME "
            "for a board with repos. tkt won't search every author across all of GitHub."
        )
    return None
