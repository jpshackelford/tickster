"""Cell formatting for the PR head / review decision / merge state columns."""

from __future__ import annotations

SHORT_SHA_LENGTH = 7

_REVIEW_LABELS = {
    "APPROVED": "approved",
    "CHANGES_REQUESTED": "changes",
    "REVIEW_REQUIRED": "required",
}


def short_sha(sha: str | None) -> str:
    return sha[:SHORT_SHA_LENGTH] if sha else "--"


def review_label(decision: str | None) -> str:
    if not decision:
        return "--"
    return _REVIEW_LABELS.get(decision, decision.lower())


def merge_label(merge_state: str | None, mergeable: str | None) -> str:
    value = merge_state or mergeable
    return value.lower() if value else "--"
