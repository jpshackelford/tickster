"""Settings model for a repo's ``.agents/tickster.toml`` and the matching helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

NORMS_PATH = ".agents/tickster.toml"
CURRENT_SCHEMA = 1
COMMENT_MATCH_CHARS = 200

DEFAULT_STALE_LABELS: tuple[str, ...] = ("stale",)


@lru_cache(maxsize=512)
def glob_regex(glob: str) -> re.Pattern[str]:
    """Compile a glob where ``*`` stays inside a path segment and ``**`` crosses them."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out), re.DOTALL)


def glob_match(glob: str, text: str, *, ignore_case: bool = False) -> bool:
    if ignore_case:
        glob, text = glob.lower(), text.lower()
    return glob_regex(glob).fullmatch(text) is not None


def any_glob_match(globs: tuple[str, ...], text: str, *, ignore_case: bool = False) -> bool:
    return any(glob_match(g, text, ignore_case=ignore_case) for g in globs)


def pattern_matches(pattern: re.Pattern[str], comment: str) -> bool:
    """Match against the first 200 characters of a comment."""
    return pattern.search(comment[:COMMENT_MATCH_CHARS]) is not None


@dataclass(frozen=True)
class Actors:
    agent_logins: tuple[str, ...] = ()
    agent_disclosure: re.Pattern[str] | None = None
    bots: tuple[str, ...] = ()


@dataclass(frozen=True)
class Labels:
    stale: tuple[str, ...] = DEFAULT_STALE_LABELS
    rank: tuple[str, ...] = ()


@dataclass(frozen=True)
class Review:
    count_reviews_from: tuple[str, ...] = ("humans", "agents")
    rerequest_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class CI:
    ignore_checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Commits:
    ignore_paths: tuple[str, ...] = ()
    min_changed_lines: int = 0


@dataclass(frozen=True)
class ImpactLine:
    pattern: re.Pattern[str]
    from_: tuple[str, ...] = ("agents", "author")
    unassessed: str = "rerun"


@dataclass(frozen=True)
class Report:
    marker: re.Pattern[str]
    required: bool = False
    only_paths: tuple[str, ...] = ()
    fail: re.Pattern[str] | None = None
    impact_line: ImpactLine | None = None


@dataclass(frozen=True)
class Norms:
    schema: int = CURRENT_SCHEMA
    actors: Actors = field(default_factory=Actors)
    labels: Labels = field(default_factory=Labels)
    review: Review = field(default_factory=Review)
    ci: CI = field(default_factory=CI)
    commits: Commits = field(default_factory=Commits)
    reports: dict[str, Report] = field(default_factory=dict)

    def is_agent(self, login: str) -> bool:
        return any_glob_match(self.actors.agent_logins, login, ignore_case=True)

    def is_listed_bot(self, login: str) -> bool:
        return any_glob_match(self.actors.bots, login, ignore_case=True)

    def has_stale_label(self, labels: list[str]) -> bool:
        wanted = {s.lower() for s in self.labels.stale}
        return any(label.lower() in wanted for label in labels)
