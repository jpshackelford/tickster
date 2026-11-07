"""Timeline nodes whose author/actor is null, as GitHub reports deleted accounts.

Shared by the `pr list` and `review` test suites so both paths see the same input.
"""

import pytest

from src.pr.models import ActionType

PR_AUTHOR = "alice"
REVIEWER = "bob"
CREATED_AT = "2024-01-01T00:00:00Z"
NULL_EVENT_AT = "2024-01-03T00:00:00Z"

# bob approves before the null-actor event so every event, including commits
# (which only count as fixes after a review), shows up as its own history character.
APPROVAL_BY_REVIEWER = {
    "__typename": "PullRequestReview",
    "author": {"login": REVIEWER},
    "state": "APPROVED",
    "createdAt": "2024-01-02T00:00:00Z",
    "comments": {"totalCount": 0},
}

# (node, expected action, expected actor)
NULL_ACTOR_CASES = [
    pytest.param(
        {
            "__typename": "PullRequestReview",
            "author": None,
            "state": "CHANGES_REQUESTED",
            "createdAt": NULL_EVENT_AT,
            "comments": {"totalCount": 0},
        },
        ActionType.REVIEW,
        "ghost",
        id="PullRequestReview.author",
    ),
    pytest.param(
        {"__typename": "IssueComment", "author": None, "createdAt": NULL_EVENT_AT},
        ActionType.COMMENT,
        "ghost",
        id="IssueComment.author",
    ),
    pytest.param(
        {"__typename": "ReviewRequestedEvent", "actor": None, "createdAt": NULL_EVENT_AT},
        ActionType.HELP,
        "ghost",
        id="ReviewRequestedEvent.actor",
    ),
    pytest.param(
        {"__typename": "MergedEvent", "actor": None, "createdAt": NULL_EVENT_AT},
        ActionType.MERGED,
        "ghost",
        id="MergedEvent.actor",
    ),
    pytest.param(
        {"__typename": "ClosedEvent", "actor": None, "createdAt": NULL_EVENT_AT},
        ActionType.KILLED,
        "ghost",
        id="ClosedEvent.actor",
    ),
    pytest.param(
        {
            "__typename": "PullRequestCommit",
            "commit": {"author": None, "committedDate": NULL_EVENT_AT},
        },
        ActionType.FIX,
        PR_AUTHOR,
        id="PullRequestCommit.commit.author",
    ),
    pytest.param(
        {
            "__typename": "PullRequestCommit",
            "commit": {"author": {"user": None}, "committedDate": NULL_EVENT_AT},
        },
        ActionType.FIX,
        PR_AUTHOR,
        id="PullRequestCommit.commit.author.user",
    ),
]


def make_pr_data(null_item: dict) -> dict:
    """Minimal open PR by PR_AUTHOR: approved by REVIEWER, then the null-actor event."""
    return {
        "repository": {"nameWithOwner": "owner/repo"},
        "number": 1,
        "title": "Test PR",
        "author": {"login": PR_AUTHOR},
        "createdAt": CREATED_AT,
        "closedAt": None,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "reviewThreads": {"nodes": []},
        "reviewRequests": {"nodes": []},
        "latestReviews": {"nodes": []},
        "commits": {"nodes": []},
        "timelineItems": {"nodes": [APPROVAL_BY_REVIEWER, null_item]},
    }
