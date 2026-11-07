"""Shape of the GraphQL PR_FIELDS_FRAGMENT around reviewer selection.

``requestedReviewer`` is selected so a Team request can be attributed. A Team the
token can't read yields a partial-data FORBIDDEN, which ``GitHubClient.graphql()``
logs rather than raises (#11), so selecting the Team branch is safe.
"""

import re

from src.pr.github_api import PR_FIELDS_FRAGMENT
from src.pr.history import process_pr_data
from src.pr.models import ActionType


def _strip_graphql_comments(fragment: str) -> str:
    """Drop ``#`` comments so assertions see only the selected fields."""
    return re.sub(r"#[^\n]*", "", fragment)


def _block(fragment: str, opener: str) -> str:
    """Body of the first ``opener { ... }`` block, matching nested braces."""
    start = fragment.index(opener)
    open_at = fragment.index("{", start)
    depth = 0
    for i in range(open_at, len(fragment)):
        depth += {"{": 1, "}": -1}.get(fragment[i], 0)
        if depth == 0:
            return fragment[open_at + 1 : i]
    raise AssertionError(f"unbalanced braces after {opener!r}")


def test_review_requested_event_selects_the_reviewer_union_including_team():
    block = _block(_strip_graphql_comments(PR_FIELDS_FRAGMENT), "... on ReviewRequestedEvent")
    assert "createdAt" in block
    assert "actor" in block
    for branch in ("... on User", "... on Bot", "... on Mannequin", "... on Team { slug }"):
        assert branch in block


def test_fragment_selects_per_reviewer_state():
    fragment = _strip_graphql_comments(PR_FIELDS_FRAGMENT)
    requests = _block(fragment, "reviewRequests(")
    assert "asCodeOwner" in requests
    assert "... on Team { slug }" in requests
    reviews = _block(fragment, "latestReviews(")
    for field in ("author { login }", "state", "submittedAt", "commit { oid }"):
        assert field in reviews
    assert "headRefOid" in fragment


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
        "reviewRequests": {"nodes": []},
        "latestReviews": {"nodes": []},
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
