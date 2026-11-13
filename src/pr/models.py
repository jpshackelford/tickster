"""Data models for PR history visualization."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from src.actors import ActorClass, HistoryEvent
from src.pr.reviewers import ReviewerState


class ActionType(Enum):
    """PR timeline action types."""

    OPENED = "o"
    HELP = "h"  # Review requested
    REVIEW = "r"  # Changes requested
    APPROVED = "a"
    COMMENT = "c"
    FIX = "f"  # Commits pushed after review
    MERGED = "m"
    KILLED = "k"  # Closed without merge


class CIStatus(Enum):
    """CI/merge status values."""

    CONFLICT = "conflict"
    GREEN = "green"
    RED = "red"
    PENDING = "pending"
    NONE = "--"


class PRState(Enum):
    """PR state values."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


@dataclass
class TimelineEvent:
    """A single event in the PR timeline."""

    action: ActionType
    actor: str
    timestamp: datetime
    actor_class: ActorClass = ActorClass.HUMAN


@dataclass(frozen=True)
class PRComment:
    """A plain PR comment, as much of it as a ``[reports]`` pattern reads.

    ``head`` is the PR's head commit when the comment was posted, or None when
    the timeline shows no commit before it.
    """

    actor: str
    actor_class: ActorClass
    at: str  # ISO-8601 UTC
    text: str
    head: str | None = None


@dataclass
class PRInfo:
    """Processed PR information for display."""

    repo: str
    number: int
    title: str
    state: PRState
    ci_status: CIStatus
    history: str  # Compact history string like "oRfAM"
    created_at: datetime
    closed_at: datetime | None
    last_activity: datetime
    author: str
    is_draft: bool = False
    unresolved_thread_count: int = 0
    head_sha: str | None = None
    review_decision: str | None = None
    merge_state: str | None = None
    mergeable: str | None = None
    events: list[HistoryEvent] = field(default_factory=list)  # one per history character
    reviewers: tuple[ReviewerState, ...] | None = None  # None = not fetched
    reviewers_truncated: bool = False
    labels: tuple[str, ...] = ()
    checks_state: str | None = None  # raw check-rollup state of the head commit, if any
    comments: tuple[PRComment, ...] | None = None  # oldest first; None = not collected
    timeline_truncated: bool = False  # events past the fetch cap are missing

    @property
    def age_seconds(self) -> float:
        """Time from open to close (or now if open)."""
        end = self.closed_at or datetime.now(self.created_at.tzinfo)
        return (end - self.created_at).total_seconds()

    @property
    def last_activity_seconds(self) -> float:
        """Time since last activity."""
        now = datetime.now(self.last_activity.tzinfo)
        return (now - self.last_activity).total_seconds()


@dataclass
class PRListResult:
    """Result of a PR list query."""

    prs: list[PRInfo] = field(default_factory=list)
    total_count: int | None = 0  # rows that matched; None = unknown (client-side state filter)
    has_more: bool = False
    cursor: str | None = None
