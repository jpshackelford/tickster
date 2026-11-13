"""What each history character means: the one source for list legends and `show`."""

from collections.abc import Iterable
from typing import Literal

Kind = Literal["pr", "issue"]

# (lowercase character, meaning). Lists match a character in either case; `B` is
# matched as written because a bot comment is always uppercase.
PR_CHARS = (
    ("o", "opened"),
    ("s", "AI opened"),
    ("h", "review requested"),
    ("r", "changes or inline review"),
    ("e", "AI review"),
    ("a", "approved"),
    ("v", "AI approval"),
    ("c", "comment"),
    ("n", "AI comment"),
    ("f", "push after a review"),
    ("m", "merged"),
    ("k", "closed"),
)
ISSUE_CHARS = (
    ("o", "opened"),
    ("s", "AI opened"),
    ("c", "comment"),
    ("n", "AI comment"),
    ("B", "bot comment"),
    ("l", "labeled"),
    ("a", "assigned"),
    ("x", "closed"),
    ("r", "reopened"),
    ("p", "PR linked"),
)
_CHARS = {"pr": PR_CHARS, "issue": ISSUE_CHARS}

AI_CASE_RULE = "AI letters: lowercase = your login, UPPERCASE = its own login"


def case_rule(you: str = "you") -> str:
    return f"lowercase = {you}, UPPERCASE = others"


def chars_text(kind: Kind) -> str:
    """Every character of `kind` with its meaning: `o opened, s AI opened, ...`."""
    return _entries_text(_CHARS[kind])


def history_legend(kind: Kind, histories: Iterable[str], *, you: str = "you") -> str | None:
    """The `History:` note for the characters in `histories`, or None when none is known.

    Entries come in table order. `you` is who lowercase stands for. The AI sentence
    is added only when an AI character is listed.
    """
    present = {c for history in histories for c in history}
    shown = [
        (char, meaning)
        for char, meaning in _CHARS[kind]
        if char in present or (char.islower() and char.upper() in present)
    ]
    if not shown:
        return None
    rule = case_rule(you)
    if any(meaning.startswith("AI ") for _, meaning in shown):
        rule += f" ({AI_CASE_RULE})"
    return f"History: {rule}. {_entries_text(shown)}"


def _entries_text(entries: Iterable[tuple[str, str]]) -> str:
    return ", ".join(f"{char} {meaning}" for char, meaning in entries)
