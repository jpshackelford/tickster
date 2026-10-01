"""Build `ItemSnapshot` objects from live `PRInfo` / `IssueInfo` / `ReviewInfo`.

Keeps the display dataclasses untouched; snapshot persistence stays an
opt-in sidecar.
"""

from __future__ import annotations

from datetime import datetime

from src.issue.models import IssueInfo, IssueState
from src.pr.models import CIStatus, PRInfo, PRState
from src.review.models import ReviewInfo, ReviewStatus
from src.snapshot.models import (
    KIND_ISSUE,
    KIND_PR,
    KIND_REVIEW,
    ItemSnapshot,
    Snapshot,
    SnapshotScope,
)


def _iso(dt: datetime) -> str:
    """Serialize a datetime as ISO-8601, Z-suffixed UTC."""
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.astimezone(tz=None).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _iso_utc(dt: datetime) -> str:
    """ISO-8601 UTC with trailing Z (stable comparisons)."""
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    from datetime import UTC

    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def item_from_pr(pr: PRInfo) -> ItemSnapshot:
    return ItemSnapshot(
        key=f"{pr.repo}#{pr.number}",
        repo=pr.repo,
        number=pr.number,
        title=pr.title or "",
        history=pr.history,
        state=_pr_state_value(pr.state),
        author=pr.author,
        last_activity=_iso_utc(pr.last_activity),
        labels=(),  # pr list does not currently carry labels
        ci_status=_ci_value(pr.ci_status),
        is_draft=pr.is_draft,
        unresolved_thread_count=pr.unresolved_thread_count,
    )


def item_from_issue(issue: IssueInfo) -> ItemSnapshot:
    return ItemSnapshot(
        key=f"{issue.repo}#{issue.number}",
        repo=issue.repo,
        number=issue.number,
        title=issue.title or "",
        history=issue.history,
        state=_issue_state_value(issue.state),
        author=issue.author,
        last_activity=_iso_utc(issue.last_activity),
        labels=tuple(issue.labels),
        linked_pr=issue.linked_pr,
    )


def item_from_review(review: ReviewInfo) -> ItemSnapshot:
    return ItemSnapshot(
        key=f"{review.repo}#{review.number}",
        repo=review.repo,
        number=review.number,
        title=review.title or "",
        history=review.history,
        state="open",  # review queue always-open rows; historical rows carry status
        author=review.author,
        last_activity=_iso_utc(review.last_activity),
        labels=(),
        ci_status=_ci_value(review.ci_status),
        unresolved_thread_count=review.unresolved_thread_count,
        review_status=_review_status_value(review.status),
        wait_seconds=review.wait_seconds,
    )


def snapshot_from_prs(prs: list[PRInfo], *, scope: SnapshotScope, name: str) -> Snapshot:
    return Snapshot.make(
        kind=KIND_PR,
        name=name,
        scope=scope,
        items=[item_from_pr(p) for p in prs],
    )


def snapshot_from_issues(issues: list[IssueInfo], *, scope: SnapshotScope, name: str) -> Snapshot:
    return Snapshot.make(
        kind=KIND_ISSUE,
        name=name,
        scope=scope,
        items=[item_from_issue(i) for i in issues],
    )


def snapshot_from_reviews(
    reviews: list[ReviewInfo], *, scope: SnapshotScope, name: str
) -> Snapshot:
    return Snapshot.make(
        kind=KIND_REVIEW,
        name=name,
        scope=scope,
        items=[item_from_review(r) for r in reviews],
    )


def _pr_state_value(state: PRState) -> str:
    return state.value


def _issue_state_value(state: IssueState) -> str:
    return state.value


def _ci_value(status: CIStatus) -> str:
    return status.value


def _review_status_value(status: ReviewStatus) -> str:
    return status.value


# Suppress unused-import warning
_ = _iso
