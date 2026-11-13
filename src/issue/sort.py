"""`--sort KEY[,KEY...]` on `tkt issue list`: parse the keys and order issues by them."""

from collections.abc import Callable, Sequence
from typing import Any

from src.issue.models import IssueInfo

SORT_CAP = 500

SORT_TOO_MANY_MESSAGE = f"more than {SORT_CAP} issues match; narrow the query"

# Each key maps to its natural-order value and the direction a bare key sorts in.
_KEYS: dict[str, tuple[Callable[[IssueInfo], Any], bool]] = {
    "number": (lambda i: i.number, False),
    "created": (lambda i: i.created_at, False),
    "updated": (lambda i: i.last_activity, False),
    "blocking": (lambda i: i.blocking, True),
}

VALID_KEYS = tuple(_KEYS)


class TooManyCandidatesError(Exception):
    """More than `SORT_CAP` issues match, so a complete sort is not possible."""

    def __init__(self) -> None:
        super().__init__(SORT_TOO_MANY_MESSAGE)


def parse_sort(text: str) -> tuple[str, ...]:
    """Split `text` into keys, each optionally prefixed with `-`; raise ValueError on a bad one."""
    keys = tuple(part.strip() for part in text.split(","))
    for key in keys:
        if key.removeprefix("-") not in _KEYS:
            raise ValueError(
                f"unknown sort key {key!r}: valid keys are {', '.join(VALID_KEYS)} "
                "(prefix a key with - to reverse it)"
            )
    return keys


def sort_issues(issues: Sequence[IssueInfo], keys: Sequence[str]) -> list[IssueInfo]:
    """Order `issues` by `keys`, then by number ascending (and repo, for a stable total order).

    Sorts from the last key to the first; Python's sort is stable, so each earlier key
    takes precedence and later ones only break its ties.
    """
    ordered = sorted(issues, key=lambda i: (i.repo, i.number))
    ordered.sort(key=lambda i: i.number)
    for key in reversed(keys):
        value, descending_by_default = _KEYS[key.removeprefix("-")]
        ordered.sort(key=value, reverse=descending_by_default != key.startswith("-"))
    return ordered
