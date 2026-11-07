"""What ``show`` reports about one PR or issue, and the helpers every builder shares."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.actors import ActorClass, iso_utc
from src.connection_paging import TRUNCATION_MARKER

DEFAULT_MAX_BODY = 600
NO_CHAR = "-"  # an event the history string does not show


def parse_time(value: str) -> datetime:
    """Parse an ISO-8601 time or date; a time with no zone is UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(
            f"invalid time {value!r}: expected ISO-8601, e.g. 2026-11-05T10:00:00Z"
        ) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def trim_body(body: str | None, max_chars: int) -> tuple[str | None, int]:
    """Trim ``body`` to ``max_chars`` (0 = no limit); return it and the characters cut."""
    text = (body or "").strip()
    if not text:
        return None, 0
    if max_chars <= 0 or len(text) <= max_chars:
        return text, 0
    more = len(text) - max_chars
    return f"{text[:max_chars]}{TRUNCATION_MARKER}({more} more chars)", more


@dataclass(frozen=True)
class ThreadComment:
    at: str
    actor: str
    actor_class: ActorClass
    body: str | None
    more_chars: int = 0

    def to_dict(self) -> dict:
        return {
            "at": self.at,
            "actor": self.actor,
            "actor_class": self.actor_class.value,
            "body": self.body,
            "more_chars": self.more_chars,
        }


@dataclass(frozen=True)
class Thread:
    """A review thread: its place in the diff, whether it is resolved, and its comments."""

    path: str | None
    line: int | None
    resolved: bool
    outdated: bool
    comments: tuple[ThreadComment, ...]

    @property
    def place(self) -> str:
        if self.path is None:
            return "--"
        return f"{self.path}:{self.line}" if self.line else self.path

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "resolved": self.resolved,
            "outdated": self.outdated,
            "comments": [c.to_dict() for c in self.comments],
        }


@dataclass(frozen=True)
class Entry:
    """One line of the timeline.

    ``char`` is the item's history letter for this event (``NO_CHAR`` when the
    history string omits it); ``text`` says what happened; ``fields`` carries the
    structured details (review state, SHA, label) that JSON reports.
    """

    at: str
    kind: str
    char: str
    actor: str
    actor_class: ActorClass
    text: str
    body: str | None = None
    more_chars: int = 0
    threads: tuple[Thread, ...] = ()
    fields: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {
            "at": self.at,
            "kind": self.kind,
            "char": self.char,
            "actor": self.actor,
            "actor_class": self.actor_class.value,
            "text": self.text,
            "body": self.body,
            "more_chars": self.more_chars,
            **self.fields,
        }
        if self.threads:
            data["threads"] = [t.to_dict() for t in self.threads]
        return data

    def since(self, cutoff: datetime) -> Entry | None:
        """This entry cut down to what happened after ``cutoff``; None when nothing did."""
        threads = tuple(
            replace_comments(t, [c for c in t.comments if parse_time(c.at) > cutoff])
            for t in self.threads
        )
        threads = tuple(t for t in threads if t.comments)
        if parse_time(self.at) <= cutoff and not threads:
            return None
        return Entry(
            self.at,
            self.kind,
            self.char,
            self.actor,
            self.actor_class,
            self.text,
            self.body,
            self.more_chars,
            threads,
            self.fields,
        )


def replace_comments(thread: Thread, comments: list[ThreadComment]) -> Thread:
    return Thread(thread.path, thread.line, thread.resolved, thread.outdated, tuple(comments))


@dataclass(frozen=True)
class ReportStatus:
    """The latest comment matching one ``[reports]`` marker, and what it says."""

    name: str
    found: bool
    at: str | None = None
    actor: str | None = None
    head: str | None = None  # the PR head when the comment was posted
    on_head: bool | None = None
    failed: bool | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "found": self.found,
            "at": self.at,
            "actor": self.actor,
            "head": self.head,
            "on_head": self.on_head,
            "failed": self.failed,
        }


@dataclass
class Show:
    """The header facts plus the (possibly filtered) timeline of one item."""

    kind: str  # "pr" | "issue"
    repo: str
    number: int
    title: str
    header: dict
    entries: list[Entry]
    reviewers: list[dict] = field(default_factory=list)
    reports: list[ReportStatus] = field(default_factory=list)
    truncated: bool = False
    since: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.repo}#{self.number}"

    def apply_since(self, cutoff: datetime) -> None:
        kept = (e.since(cutoff) for e in self.entries)
        self.entries = [e for e in kept if e is not None]
        self.since = iso_utc(cutoff)

    def to_dict(self) -> dict:
        data = {
            "kind": self.kind,
            "ref": self.ref,
            "title": self.title,
            **self.header,
        }
        if self.kind == "pr":
            data["reviewers"] = self.reviewers
            data["reports"] = [r.to_dict() for r in self.reports]
        data["since"] = self.since
        data["timeline_truncated"] = self.truncated
        data["events"] = [e.to_dict() for e in self.entries]
        return data
