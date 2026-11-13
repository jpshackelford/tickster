"""Per-reviewer state on a PR: who is asked, who reviewed which commit, who needs a re-request.

Built from ``reviewRequests`` (pending requests), ``latestReviews`` (each
reviewer's newest review and the commit it covered) and the timeline's
``ReviewRequestedEvent`` (who asked, and when). ``waiting``, ``rereview_requested``
and ``rereview_needed`` are derived, never fetched: GitHub has no field for the
sidebar's re-request button.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from src.actors import classify_actor
from src.norms.model import Norms

logger = logging.getLogger(__name__)

TEAM_UNKNOWN = "team:unknown"
GHOST = "ghost"

APPROVED = "APPROVED"
CHANGES_REQUESTED = "CHANGES_REQUESTED"
COMMENTED = "COMMENTED"
DISMISSED = "DISMISSED"

_SHORT_SHA = 7
_VERBS = {
    APPROVED: "approved",
    CHANGES_REQUESTED: "requested changes",
    COMMENTED: "commented",
}


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ReviewerState:
    """One reviewer of one PR: login (``team:SLUG`` for a team), request and latest review."""

    login: str
    actor_class: str | None  # None for a team
    requested: bool = False
    requested_by: str | None = None
    requested_at: str | None = None
    as_code_owner: bool = False
    latest_state: str | None = None
    reviewed_commit: str | None = None
    on_head: bool = False
    submitted_at: str | None = None

    @property
    def reviewed(self) -> bool:
        return self.latest_state is not None

    @property
    def rereview_requested(self) -> bool:
        """A request is pending that came after this reviewer's review."""
        if not (self.requested and self.submitted_at):
            return False
        return self.requested_at is None or _parse(self.requested_at) > _parse(self.submitted_at)

    @property
    def waiting(self) -> bool:
        """A request is pending and no review has answered it yet."""
        if not self.requested:
            return False
        return not self.submitted_at or self.rereview_requested

    @property
    def rereview_needed(self) -> bool:
        """The latest review covers an older head and nothing asks for another."""
        return self.reviewed and not self.on_head and not self.requested

    def to_dict(self) -> dict:
        return {
            "login": self.login,
            "actor_class": self.actor_class,
            "requested": self.requested,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "as_code_owner": self.as_code_owner,
            "latest_state": self.latest_state,
            "reviewed_commit": self.reviewed_commit,
            "on_head": self.on_head,
            "submitted_at": self.submitted_at,
            "waiting": self.waiting,
            "rereview_requested": self.rereview_requested,
            "rereview_needed": self.rereview_needed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReviewerState:
        return cls(
            login=data["login"],
            actor_class=data["actor_class"],
            requested=data["requested"],
            requested_by=data["requested_by"],
            requested_at=data["requested_at"],
            as_code_owner=data["as_code_owner"],
            latest_state=data["latest_state"],
            reviewed_commit=data["reviewed_commit"],
            on_head=data["on_head"],
            submitted_at=data["submitted_at"],
        )


def requested_reviewer_login(reviewer: dict | None) -> str:
    """Login of a ``requestedReviewer`` node; a team is ``team:SLUG``.

    An unreadable node (null) is a team the token may not read: reading a Team
    needs org access, which GitHub App installation tokens lack.
    """
    if reviewer is None:
        return TEAM_UNKNOWN
    if reviewer.get("__typename") == "Team":
        return f"team:{reviewer['slug']}"
    return reviewer.get("login") or GHOST


def build_reviewers(
    pr_data: dict, reference_user: str, norms: Norms | None = None
) -> tuple[ReviewerState, ...] | None:
    """Reviewer records sorted by login, or None when the PR data carries none of the fields."""
    if "reviewRequests" not in pr_data and "latestReviews" not in pr_data:
        return None

    head = pr_data.get("headRefOid")
    asked = _latest_requests(pr_data)
    records: dict[str, dict] = {}

    for node in (pr_data.get("reviewRequests") or {}).get("nodes", []):
        if not node:
            continue
        login = requested_reviewer_login(node.get("requestedReviewer"))
        if login == TEAM_UNKNOWN:
            logger.warning(
                "%s #%s: a requested reviewer could not be read (a team the token "
                "can't see?); reporting it as %s",
                pr_data.get("repository", {}).get("nameWithOwner"),
                pr_data.get("number"),
                TEAM_UNKNOWN,
            )
        requested_by, requested_at = asked.get(login.lower(), (None, None))
        records[login.lower()] = {
            "login": login,
            "requested": True,
            "requested_by": requested_by,
            "requested_at": requested_at,
            "as_code_owner": bool(node.get("asCodeOwner")),
        }

    for node in (pr_data.get("latestReviews") or {}).get("nodes", []):
        if not node:
            continue
        login = ((node.get("author") or {}).get("login")) or GHOST
        commit = (node.get("commit") or {}).get("oid")
        records.setdefault(login.lower(), {"login": login}).update(
            latest_state=node.get("state"),
            reviewed_commit=commit,
            on_head=commit is not None and commit == head,
            submitted_at=node.get("submittedAt"),
        )

    return tuple(
        ReviewerState(
            actor_class=None
            if rec["login"].startswith("team:")
            else str(classify_actor(rec["login"], reference_user, norms)),
            **rec,
        )
        for rec in sorted(records.values(), key=lambda r: r["login"].lower())
    )


def _latest_requests(pr_data: dict) -> dict[str, tuple[str | None, str]]:
    """Reviewer login (lowercased) to (who asked, when) for their newest request event."""
    asked: dict[str, tuple[str | None, str]] = {}
    for item in (pr_data.get("timelineItems") or {}).get("nodes", []):
        if not item or item.get("__typename") != "ReviewRequestedEvent":
            continue
        if "requestedReviewer" not in item:
            continue
        login = requested_reviewer_login(item["requestedReviewer"])
        actor = (item.get("actor") or {}).get("login")
        when = item["createdAt"]
        previous = asked.get(login.lower())
        if previous is None or _parse(when) >= _parse(previous[1]):
            asked[login.lower()] = (actor, when)
    return asked


def reviewer_changes(
    prev: tuple[ReviewerState, ...], curr: tuple[ReviewerState, ...]
) -> tuple[str, ...]:
    """Describe what changed per reviewer between two snapshots of one PR."""
    before = {r.login.lower(): r for r in prev}
    after = {r.login.lower(): r for r in curr}
    changes: list[str] = []
    for key in sorted(before.keys() | after.keys()):
        changes.extend(_changes_for(before.get(key), after.get(key)))
    return tuple(changes)


def _changes_for(old: ReviewerState | None, new: ReviewerState | None) -> list[str]:
    if new is None:
        assert old is not None
        return [f"{old.login} request removed" if old.requested else f"{old.login} review gone"]

    changes: list[str] = []
    if new.requested and not (old and old.requested):
        changes.append(
            f"{new.login} ↻ re-requested" if new.rereview_requested else f"{new.login} requested"
        )
    elif old and old.requested and not new.requested and not _review_changed(old, new):
        changes.append(f"{new.login} request removed")

    if _review_changed(old, new) and new.latest_state is not None:
        changes.append(_review_change(new))
    elif old and old.on_head and not new.on_head and new.reviewed:
        changes.append(f"{new.login} review now on old head")
    return changes


def _review_key(r: ReviewerState | None) -> tuple[str | None, str | None, str | None]:
    return (r.latest_state, r.reviewed_commit, r.submitted_at) if r else (None, None, None)


def _review_changed(old: ReviewerState | None, new: ReviewerState) -> bool:
    return _review_key(old) != _review_key(new)


def _review_change(new: ReviewerState) -> str:
    if new.latest_state == DISMISSED:
        return f"{new.login} review dismissed"
    verb = _VERBS.get(new.latest_state or "", (new.latest_state or "").lower())
    where = "on head" if new.on_head else f"on {(new.reviewed_commit or '?')[:_SHORT_SHA]}"
    return f"{new.login} {verb} {where}"


_COMPACT_ORDER = ("✓", "✗", "~", "⊘", "•", "↻", "!")


def reviewer_mark(reviewer: ReviewerState) -> str:
    """One glyph for a reviewer's state; see the legend in ``REVIEWER_LEGEND``."""
    if reviewer.rereview_requested:
        return "↻"
    if reviewer.waiting:
        return "•"
    if reviewer.rereview_needed:
        return "!"
    if reviewer.latest_state == APPROVED:
        return "✓"
    if reviewer.latest_state == CHANGES_REQUESTED:
        return "✗"
    if reviewer.latest_state == DISMISSED:
        return "⊘"
    return "~"


REVIEWER_LEGEND = (
    "Reviewers: ✓ approved on head, ✗ changes requested on head, ~ commented on head, "
    "⊘ dismissed, • waiting, ↻ re-review requested, ! review on an old head (re-request)."
)


def compact_reviewers(reviewers: tuple[ReviewerState, ...] | None) -> str:
    """Counts per mark, e.g. ``✓2 ✗1 •1``; ``--`` when no one reviews."""
    if not reviewers:
        return "--"
    marks = [reviewer_mark(r) for r in reviewers]
    return " ".join(f"{m}{marks.count(m)}" for m in _COMPACT_ORDER if m in marks)


def named_reviewers(reviewers: tuple[ReviewerState, ...] | None) -> str:
    """Each reviewer with their mark, e.g. ``alice✓ bob↻``."""
    if not reviewers:
        return "--"
    return " ".join(f"{r.login}{reviewer_mark(r)}" for r in reviewers)
