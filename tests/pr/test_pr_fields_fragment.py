"""Regression tests for the GraphQL PR_FIELDS_FRAGMENT.

Context: tkt's PR_FIELDS_FRAGMENT previously requested
``requestedReviewer { ... on User { login } ... on Team { name } }``
on every ``ReviewRequestedEvent``. The field was never consumed by
Python downstream, but when a team was the requested reviewer GitHub
required team-read permission to resolve any part of it. GitHub App
installation tokens (which many users rely on in sandboxed
environments) lack that permission and the API returned a
partial-data response with a top-level ``errors`` entry of type
``FORBIDDEN`` — "Resource not accessible by integration". tkt's
graphql client treats any ``errors`` as fatal, so ``tkt pr list``
would blow up on any board containing a repo whose recent PRs had
been assigned to a team for review.

The fix is to drop the unused field from the fragment entirely.
These tests are the guard that keeps it dropped.
"""

from src.pr.github_api import PR_FIELDS_FRAGMENT
from src.pr.history import process_pr_data


def test_fragment_does_not_request_requested_reviewer():
    """requestedReviewer is unused in Python and triggers FORBIDDEN on team
    reviewer-requests when tkt runs with a GitHub App installation token."""
    assert "requestedReviewer" not in PR_FIELDS_FRAGMENT


def test_fragment_still_requests_fields_history_processing_consumes():
    """Guard against over-pruning: process_pr_data reads these from the
    ReviewRequestedEvent node, so the fragment must keep asking for them."""
    assert "ReviewRequestedEvent" in PR_FIELDS_FRAGMENT
    # The ReviewRequestedEvent sub-selection must still include createdAt + actor.
    rre_section = PR_FIELDS_FRAGMENT.split("ReviewRequestedEvent", 1)[1].split("}", 2)
    rre_body = rre_section[0] + "}" + rre_section[1] + "}"
    assert "createdAt" in rre_body
    assert "actor" in rre_body


def test_process_pr_data_handles_review_requested_without_requested_reviewer():
    """process_pr_data must correctly process a ReviewRequestedEvent node that
    contains only the fields the pruned fragment now asks for."""
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
    # 'o' = opened by reference user; the HELP glyph for ReviewRequestedEvent is
    # consumed in-sequence by _filter_timeline_events, so we assert the
    # resulting history string contains the subsequent APPROVED event rather
    # than crashing on the missing requestedReviewer field.
    assert "A" in info.history
