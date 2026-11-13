"""Build `ItemSnapshot` objects from live `PRInfo` / `IssueInfo` / `ReviewInfo`.

Keeps the display dataclasses untouched; snapshot persistence stays an
opt-in sidecar.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.issue.models import IssueInfo, IssueState
from src.pr.models import CIStatus, PRInfo, PRState
from src.pr.steps import StepResult, step_statuses
from src.review.models import ReviewInfo, ReviewStatus
from src.snapshot.models import (
    KIND_ISSUE,
    KIND_PR,
    KIND_REVIEW,
    ItemSnapshot,
    Snapshot,
    SnapshotScope,
)
from src.snapshot.rows import item_url


def _iso_utc(dt: datetime) -> str:
    """ISO-8601 UTC with trailing Z (stable comparisons).

    Rejects naive datetimes. Upstream `last_activity` fields on PRInfo /
    IssueInfo / ReviewInfo are populated from GitHub ISO-8601 strings and
    always carry a tzinfo; a naive datetime here is a programming error
    that would silently stamp `Z` onto wall-clock time.
    """
    if dt.tzinfo is None:
        raise ValueError(f"_iso_utc requires an aware datetime; got naive {dt!r}")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def item_from_pr(pr: PRInfo, steps: tuple[StepResult, ...] | None = None) -> ItemSnapshot:
    return ItemSnapshot(
        ref=f"{pr.repo}#{pr.number}",
        kind=KIND_PR,
        repo=pr.repo,
        number=pr.number,
        url=item_url(pr.repo, KIND_PR, pr.number),
        title=pr.title or "",
        history=pr.history,
        state=_pr_state_value(pr.state),
        author=pr.author,
        labels=pr.labels,
        created_at=_iso_utc(pr.created_at),
        last_activity=_iso_utc(pr.last_activity),
        draft=pr.is_draft,
        ci=_ci_value(pr.ci_status),
        unresolved_threads=pr.unresolved_thread_count,
        head=pr.head_sha,
        review_decision=pr.review_decision,
        merge_state=pr.merge_state,
        mergeable=pr.mergeable,
        reviewers=pr.reviewers or (),
        step_status=step_statuses(steps) if steps is not None else None,
    )


def item_from_issue(issue: IssueInfo) -> ItemSnapshot:
    return ItemSnapshot(
        ref=f"{issue.repo}#{issue.number}",
        kind=KIND_ISSUE,
        repo=issue.repo,
        number=issue.number,
        url=item_url(issue.repo, KIND_ISSUE, issue.number),
        title=issue.title or "",
        history=issue.history,
        state=_issue_state_value(issue.state),
        author=issue.author,
        labels=tuple(issue.labels),
        created_at=_iso_utc(issue.created_at),
        last_activity=_iso_utc(issue.last_activity),
        linked_pr=issue.linked_pr,
        closed_at=_iso_utc(issue.closed_at) if issue.closed_at else None,
        open_blockers=tuple(issue.open_blockers),
        blocking=issue.blocking,
        parent=issue.parent,
        milestone=issue.milestone,
    )


def item_from_review(review: ReviewInfo) -> ItemSnapshot:
    return ItemSnapshot(
        ref=f"{review.repo}#{review.number}",
        kind=KIND_REVIEW,
        repo=review.repo,
        number=review.number,
        url=item_url(review.repo, KIND_REVIEW, review.number),
        title=review.title or "",
        history=review.history,
        state="open",  # review queue always-open rows; historical rows carry status
        author=review.author,
        labels=review.labels,
        created_at=_iso_utc(review.created_at),
        last_activity=_iso_utc(review.last_activity),
        draft=review.draft,
        ci=_ci_value(review.ci_status),
        unresolved_threads=review.unresolved_thread_count,
        head=review.head_sha,
        review_decision=review.review_decision,
        merge_state=review.merge_state,
        mergeable=review.mergeable,
        reviewers=review.reviewers,
        review_status=_review_status_value(review.status),
        wait_seconds=review.wait_seconds,
    )


def snapshot_from_prs(
    prs: list[PRInfo],
    *,
    scope: SnapshotScope,
    name: str,
    has_more: bool = False,
    total_count: int | None = None,
    steps: dict[str, tuple[StepResult, ...]] | None = None,
) -> Snapshot:
    return Snapshot.make(
        kind=KIND_PR,
        name=name,
        scope=scope,
        items=[
            item_from_pr(p, steps[f"{p.repo}#{p.number}"] if steps is not None else None)
            for p in prs
        ],
        has_more=has_more,
        total_count=total_count,
    )


def snapshot_from_issues(
    issues: list[IssueInfo],
    *,
    scope: SnapshotScope,
    name: str,
    has_more: bool = False,
    total_count: int | None = None,
) -> Snapshot:
    return Snapshot.make(
        kind=KIND_ISSUE,
        name=name,
        scope=scope,
        items=[item_from_issue(i) for i in issues],
        has_more=has_more,
        total_count=total_count,
    )


def snapshot_from_reviews(
    reviews: list[ReviewInfo],
    *,
    scope: SnapshotScope,
    name: str,
    has_more: bool = False,
    total_count: int | None = None,
) -> Snapshot:
    return Snapshot.make(
        kind=KIND_REVIEW,
        name=name,
        scope=scope,
        items=[item_from_review(r) for r in reviews],
        has_more=has_more,
        total_count=total_count,
    )


def _pr_state_value(state: PRState) -> str:
    return state.value


def _issue_state_value(state: IssueState) -> str:
    return state.value


def _ci_value(status: CIStatus) -> str:
    return status.value


def _review_status_value(status: ReviewStatus) -> str:
    return status.value
