"""Regression tests for the GraphQL PR_FIELDS_FRAGMENT.

Full context is in the PR / commit that dropped ``requestedReviewer`` from the
fragment. Short version: the field was unused in Python but caused GitHub to
return a FORBIDDEN partial-data response when a Team was the requested
reviewer, which ``GitHubClient.graphql()`` currently treats as fatal.
"""

import re

from src.pr.github_api import PR_FIELDS_FRAGMENT
from src.pr.history import process_pr_data
from src.pr.models import ActionType


def _strip_graphql_comments(fragment: str) -> str:
    """Drop ``#`` comments so assertions see only the selected fields."""
    return re.sub(r"#[^\n]*", "", fragment)


def _extract_review_requested_block(fragment: str) -> str:
    """Return the body of the ``... on ReviewRequestedEvent { ... }`` block.

    Handles one level of nested braces so sub-selections like ``actor { login }``
    don't trip up the match.
    """
    match = re.search(
        r"ReviewRequestedEvent\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
        fragment,
    )
    assert match is not None, (
        "ReviewRequestedEvent block not found in fragment (or nested >1 level deep)"
    )
    return match.group(1)


def test_fragment_does_not_request_requested_reviewer():
    assert "requestedReviewer" not in _strip_graphql_comments(PR_FIELDS_FRAGMENT)


def test_review_requested_block_keeps_fields_history_processing_needs():
    """Guard against over-pruning: _parse_timeline_item reads createdAt and
    actor.login from the ReviewRequestedEvent node."""
    block = _extract_review_requested_block(_strip_graphql_comments(PR_FIELDS_FRAGMENT))
    assert "createdAt" in block
    assert "actor" in block


def test_process_pr_data_handles_review_requested_without_requested_reviewer():
    """End-to-end: process_pr_data must consume a ReviewRequestedEvent node
    shaped like what the pruned fragment now returns."""
    pr_data = {
        "repository": {"nameWithOwner": "OpenHands/OpenHands"},
        "number": 17813,
        "title": "feat(sidebar): add drag-to-resize handle on the left sidebar",
        "state": "OPEN",
        "isDraft": False,
        "createdAt": "2026-09-30T18:00:00Z",
        "closedAt": None,
        "mergeable": "MERGEABLE",
        "author": {"login": "jpshackelford"},
        "reviewThreads": {"nodes": []},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
        "timelineItems": {
            "nodes": [
                {
                    "__typename": "ReviewRequestedEvent",
                    "createdAt": "2026-09-30T18:05:00Z",
                    "actor": {"login": "jpshackelford"},
                },
                {
                    "__typename": "PullRequestReview",
                    "author": {"login": "alice"},
                    "state": "APPROVED",
                    "createdAt": "2026-09-30T19:00:00Z",
                    "comments": {"totalCount": 0},
                },
            ],
        },
    }

    info = process_pr_data(pr_data, reference_user="jpshackelford")

    assert info.number == 17813
    # Assert on structured action types, not on display glyphs: the history
    # string's uppercase/lowercase convention is a presentation detail and
    # shouldn't own a regression test for a GraphQL change.
    action_chars = {a.value for a in ActionType}
    seen_actions = {ch.lower() for ch in info.history if ch.lower() in action_chars}
    assert ActionType.OPENED.value in seen_actions
    assert ActionType.HELP.value in seen_actions
    assert ActionType.APPROVED.value in seen_actions
