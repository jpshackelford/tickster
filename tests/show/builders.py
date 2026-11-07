"""GraphQL node builders for the show tests."""

from __future__ import annotations

HEAD = "c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3"
C1 = "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1"
C2 = "c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2"


def ts(hour: int, minute: int = 0, day: int = 5) -> str:
    return f"2026-11-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def login(name: str | None) -> dict | None:
    return {"login": name} if name else None


def conn(nodes: list) -> dict:
    return {"nodes": nodes}


def comment(who: str | None, at: str, body: str) -> dict:
    return {"__typename": "IssueComment", "author": login(who), "body": body, "createdAt": at}


def review(
    review_id: str, who: str, state: str, at: str, commit: str | None, body: str = ""
) -> dict:
    return {
        "__typename": "PullRequestReview",
        "id": review_id,
        "author": login(who),
        "body": body,
        "state": state,
        "createdAt": at,
        "commit": {"oid": commit} if commit else None,
        "comments": {"totalCount": 1},
    }


def commit(oid: str, who: str | None, at: str, headline: str = "a change") -> dict:
    return {
        "__typename": "PullRequestCommit",
        "commit": {
            "oid": oid,
            "messageHeadline": headline,
            "author": {"user": login(who)},
            "committedDate": at,
        },
    }


def request(who: str, at: str, by: str, *, removed: bool = False) -> dict:
    return {
        "__typename": "ReviewRequestRemovedEvent" if removed else "ReviewRequestedEvent",
        "createdAt": at,
        "actor": login(by),
        "requestedReviewer": {"__typename": "User", "login": who},
    }


def thread(thread_id: str, path: str, line: int, resolved: bool, comments: list) -> dict:
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": False,
        "path": path,
        "line": line,
        "originalLine": line,
        "comments": conn(comments),
    }


def thread_comment(who: str | None, at: str, body: str, review_id: str | None) -> dict:
    return {
        "body": body,
        "createdAt": at,
        "author": login(who),
        "pullRequestReview": {"id": review_id} if review_id else None,
    }


def pr_node(timeline: list, threads: list | None = None, **overrides) -> dict:
    node = {
        "id": "PR_1",
        "number": 7,
        "title": "Add the thing",
        "body": "Adds the thing.",
        "url": "https://github.com/o/r/pull/7",
        "state": "OPEN",
        "isDraft": False,
        "createdAt": ts(10),
        "closedAt": None,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "APPROVED",
        "headRefOid": HEAD,
        "author": login("alice"),
        "repository": {"nameWithOwner": "o/r"},
        "closingIssuesReferences": conn([{"number": 40, "repository": {"nameWithOwner": "o/r"}}]),
        "reviewThreads": conn(threads or []),
        "reviewRequests": conn([]),
        "latestReviews": conn([]),
        "commits": conn([{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]),
        "timelineItems": conn(timeline),
    }
    node.update(overrides)
    return node


def issue_node(timeline: list, **overrides) -> dict:
    node = {
        "id": "ISSUE_1",
        "number": 40,
        "title": "Show a timeline",
        "body": "We need a timeline.",
        "url": "https://github.com/o/r/issues/40",
        "state": "OPEN",
        "createdAt": ts(9),
        "closedAt": None,
        "author": login("alice"),
        "repository": {"nameWithOwner": "o/r"},
        "assignees": conn([login("bob")]),
        "labels": conn([{"name": "enhancement"}, {"name": "ready"}]),
        "timelineItems": conn(timeline),
    }
    node.update(overrides)
    return node
