"""Fetch one PR with the text of its comments and reviews, and turn it into a timeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from src.actors import ActorClass, classify_actor, iso_utc
from src.board.github_api import GitHubClient
from src.connection_paging import ConnectionSpec, complete_connection, is_truncated
from src.norms.model import Norms, pattern_matches
from src.norms.store import get_repo_norms
from src.pr.detail import short_sha
from src.pr.github_api import (
    PR_LATEST_REVIEWS,
    PR_REVIEWER_REQUESTS,
    PR_TIMELINE,
    REQUESTED_REVIEWER,
)
from src.pr.history import (
    _format_action,
    _login,
    _parse_datetime,
    _parse_timeline_item,
    process_pr_data,
)
from src.pr.models import ActionType, TimelineEvent
from src.pr.reviewers import requested_reviewer_login
from src.show.models import (
    NO_CHAR,
    Entry,
    ReportStatus,
    Show,
    Thread,
    ThreadComment,
    trim_body,
)
from src.snapshot.rows import KIND_PR, item_url

# A busy PR's whole timeline matters here, so the cap is far above the list commands'.
TIMELINE_CAP = 5000
THREAD_CAP = 1000

_REVIEW_TEXT = {
    "APPROVED": "approved",
    "CHANGES_REQUESTED": "requested changes",
    "COMMENTED": "commented",
    "DISMISSED": "review, since dismissed",
}

# Timeline items the history string ignores but a reader of the PR needs.
_EXTRA_EVENTS = {
    "HeadRefForcePushedEvent",
    "ReviewRequestRemovedEvent",
    "ReviewDismissedEvent",
    "ReopenedEvent",
}

PR_SHOW_TIMELINE = replace(
    PR_TIMELINE,
    args="""itemTypes: [
        PULL_REQUEST_REVIEW,
        ISSUE_COMMENT,
        PULL_REQUEST_COMMIT,
        HEAD_REF_FORCE_PUSHED_EVENT,
        REVIEW_REQUESTED_EVENT,
        REVIEW_REQUEST_REMOVED_EVENT,
        REVIEW_DISMISSED_EVENT,
        CLOSED_EVENT,
        MERGED_EVENT,
        REOPENED_EVENT
    ]""",
    cap=TIMELINE_CAP,
    selection="""            __typename
            ... on PullRequestReview {
                id
                author { login }
                body
                state
                createdAt
                commit { oid }
                comments { totalCount }
            }
            ... on IssueComment {
                author { login }
                body
                createdAt
            }
            ... on PullRequestCommit {
                commit {
                    oid
                    messageHeadline
                    author { user { login } }
                    committedDate
                }
            }
            ... on HeadRefForcePushedEvent {
                actor { login }
                createdAt
                afterCommit { oid }
            }
            ... on ReviewRequestedEvent {
                createdAt
                actor { login }
                REQUESTED_REVIEWER_FIELDS
            }
            ... on ReviewRequestRemovedEvent {
                createdAt
                actor { login }
                REQUESTED_REVIEWER_FIELDS
            }
            ... on ReviewDismissedEvent {
                createdAt
                actor { login }
                dismissalMessage
                review { author { login } }
            }
            ... on ClosedEvent {
                actor { login }
                createdAt
            }
            ... on MergedEvent {
                actor { login }
                createdAt
            }
            ... on ReopenedEvent {
                actor { login }
                createdAt
            }""".replace("REQUESTED_REVIEWER_FIELDS", REQUESTED_REVIEWER),
)
THREAD_COMMENTS = ConnectionSpec(
    type_name="PullRequestReviewThread",
    field="comments",
    selection="""        body
        createdAt
        author { login }
        pullRequestReview { id }""",
    cap=THREAD_CAP,
    first=50,
)
PR_SHOW_THREADS = ConnectionSpec(
    type_name="PullRequest",
    field="reviewThreads",
    selection=f"""            id
            isResolved
            isOutdated
            path
            line
            originalLine
            {THREAD_COMMENTS.fragment_field()}""",
    cap=THREAD_CAP,
    first=50,
)

PR_SHOW_QUERY = f"""
query($owner: String!, $name: String!, $number: Int!) {{
    repository(owner: $owner, name: $name) {{
        pullRequest(number: $number) {{
            id
            number
            title
            body
            url
            state
            isDraft
            createdAt
            closedAt
            mergeable
            mergeStateStatus
            reviewDecision
            headRefOid
            author {{ login }}
            repository {{ nameWithOwner }}
            closingIssuesReferences(first: 20) {{
                nodes {{ number repository {{ nameWithOwner }} }}
            }}
            {PR_SHOW_THREADS.fragment_field()}
            {PR_REVIEWER_REQUESTS.fragment_field()}
            {PR_LATEST_REVIEWS.fragment_field()}
            commits(last: 1) {{
                nodes {{ commit {{ statusCheckRollup {{ state }} }} }}
            }}
            {PR_SHOW_TIMELINE.fragment_field()}
        }}
    }}
}}
"""


def fetch_pr_node(client: GitHubClient, repo: str, number: int) -> dict:
    """The raw PR with every connection followed to its cap."""
    owner, name = repo.split("/", 1)
    data = client.graphql(PR_SHOW_QUERY, {"owner": owner, "name": name, "number": number})
    node = (data.get("repository") or {}).get("pullRequest")
    if node is None:
        raise ValueError(f"PR not found: {repo}#{number}")
    complete_connection(client, node, PR_SHOW_TIMELINE)
    complete_connection(client, node, PR_SHOW_THREADS)
    for thread in node["reviewThreads"]["nodes"]:
        if thread:
            complete_connection(client, thread, THREAD_COMMENTS)
    complete_connection(client, node, PR_REVIEWER_REQUESTS)
    complete_connection(client, node, PR_LATEST_REVIEWS)
    return node


@dataclass
class _Item:
    typename: str
    raw: dict
    at: datetime
    actor: str
    actor_class: ActorClass
    event: TimelineEvent | None  # how the history string sees it; None if it does not


def _prepare(item: dict, pr_author: str, reference_user: str, norms: Norms | None) -> _Item | None:
    typename = item["__typename"]
    event = _parse_timeline_item(typename, item, pr_author, reference_user, norms)
    if event is not None:
        return _Item(typename, item, event.timestamp, event.actor, event.actor_class, event)
    dismissed_review = typename == "PullRequestReview" and item.get("state") == "DISMISSED"
    if not (dismissed_review or typename in _EXTRA_EVENTS):
        return None
    actor = _login(item.get("author") if dismissed_review else item.get("actor"))
    at = _parse_datetime(item["createdAt"])
    actor_class = classify_actor(actor, reference_user, norms, item.get("body"))
    return _Item(typename, item, at, actor, actor_class, None)


def _thread_comment(
    raw: dict, reference_user: str, norms: Norms | None, max_body: int
) -> ThreadComment:
    actor = _login(raw.get("author"))
    body, more = trim_body(raw.get("body"), max_body)
    return ThreadComment(
        at=iso_utc(_parse_datetime(raw["createdAt"])),
        actor=actor,
        actor_class=classify_actor(actor, reference_user, norms, raw.get("body")),
        body=body,
        more_chars=more,
    )


def _threads_by_review(
    node: dict, reference_user: str, norms: Norms | None, max_body: int
) -> dict[str | None, list[Thread]]:
    """Review threads keyed by the review that started them (None: unknown review)."""
    grouped: dict[str | None, list[Thread]] = {}
    for raw in node["reviewThreads"]["nodes"]:
        comments = [c for c in (raw or {}).get("comments", {}).get("nodes", []) if c]
        if not comments:
            continue
        thread = Thread(
            path=raw.get("path"),
            line=raw.get("line") or raw.get("originalLine"),
            resolved=bool(raw.get("isResolved")),
            outdated=bool(raw.get("isOutdated")),
            comments=tuple(_thread_comment(c, reference_user, norms, max_body) for c in comments),
        )
        review_id = (comments[0].get("pullRequestReview") or {}).get("id")
        grouped.setdefault(review_id, []).append(thread)
    return grouped


class _Builder:
    """Walks the sorted timeline once, keeping the state that later events depend on."""

    def __init__(self, node: dict, reference_user: str, max_body: int):
        self.node = node
        self.reference_user = reference_user
        self.max_body = max_body
        self.info = process_pr_data(node, reference_user)
        self.norms = get_repo_norms(self.info.repo)
        self.entries: list[Entry] = []
        self.has_had_review = False  # a commit before any review is not a "fix"
        self.head_seen: str | None = None
        self.push: list[_Item] = []
        self.report_hits: dict[str, tuple[_Item, str | None, bool]] = {}
        self.merged_times = {
            i["createdAt"]
            for i in node["timelineItems"]["nodes"]
            if i and i["__typename"] == "MergedEvent"
        }
        self.threads = _threads_by_review(node, reference_user, self.norms, max_body)

    def char(self, event: TimelineEvent) -> str:
        if event.action == ActionType.FIX and not self.has_had_review:
            return NO_CHAR
        return _format_action(
            event.action, event.actor, self.reference_user, ai=event.actor_class.is_ai
        )

    def add(self, item: _Item, kind: str, text: str, *, body: str | None = None, **fields) -> None:
        trimmed, more = trim_body(body, self.max_body)
        self.entries.append(
            Entry(
                at=iso_utc(item.at),
                kind=kind,
                char=self.char(item.event) if item.event else NO_CHAR,
                actor=item.actor,
                actor_class=item.actor_class,
                text=text,
                body=trimmed,
                more_chars=more,
                fields=fields,
            )
        )

    def flush_push(self) -> None:
        if not self.push:
            return
        first, last = self.push[0], self.push[-1]
        commits = [p.raw["commit"] for p in self.push]
        count = len(commits)
        tip = commits[-1]
        text = f"pushed {count} commit{'s' if count != 1 else ''}, last {short_sha(tip.get('oid'))}"
        if tip.get("messageHeadline"):
            text += f' "{tip["messageHeadline"]}"'
        item = _Item(last.typename, last.raw, last.at, last.actor, last.actor_class, first.event)
        self.add(
            item,
            "push",
            text,
            commits=count,
            head=tip.get("oid"),
            messages=[c.get("messageHeadline") for c in commits],
        )
        self.push = []

    def note_report(self, item: _Item, body: str | None) -> None:
        if self.norms is None or not body:
            return
        for name, report in self.norms.reports.items():
            if pattern_matches(report.marker, body):
                failed = report.fail is not None and pattern_matches(report.fail, body)
                self.report_hits[name] = (item, self.head_seen, failed)

    def opened(self) -> None:
        node = self.node
        author = self.info.author
        actor_class = classify_actor(author, self.reference_user, self.norms, node.get("body"))
        body, more = trim_body(node.get("body"), self.max_body)
        self.entries.append(
            Entry(
                at=iso_utc(self.info.created_at),
                kind="opened",
                char=_format_action(
                    ActionType.OPENED, author, self.reference_user, ai=actor_class.is_ai
                ),
                actor=author,
                actor_class=actor_class,
                text="opened",
                body=body,
                more_chars=more,
            )
        )

    def handle(self, item: _Item) -> None:
        typename, raw = item.typename, item.raw
        if typename != "PullRequestCommit" or (self.push and self.push[-1].actor != item.actor):
            self.flush_push()

        if typename == "PullRequestCommit":
            self.push.append(item)
            self.head_seen = raw["commit"].get("oid")
        elif typename == "PullRequestReview":
            self.review(item)
        elif typename == "IssueComment":
            self.add(item, "comment", "commented", body=raw.get("body"))
            self.note_report(item, raw.get("body"))
        elif typename == "HeadRefForcePushedEvent":
            sha = (raw.get("afterCommit") or {}).get("oid")
            self.head_seen = sha
            self.add(item, "force_push", f"force-pushed to {short_sha(sha)}", head=sha)
        elif typename == "ReviewRequestedEvent":
            who = requested_reviewer_login(raw.get("requestedReviewer"))
            self.add(item, "review_request", f"requested review from {who}", reviewer=who)
        elif typename == "ReviewRequestRemovedEvent":
            who = requested_reviewer_login(raw.get("requestedReviewer"))
            text = f"removed review request for {who}"
            self.add(item, "review_request_removed", text, reviewer=who)
        elif typename == "ReviewDismissedEvent":
            author = _login((raw.get("review") or {}).get("author"))
            text = f"dismissed review by {author}"
            self.add(
                item,
                "review_dismissed",
                text,
                body=raw.get("dismissalMessage"),
                review_author=author,
            )
        elif typename == "MergedEvent":
            self.add(item, "merged", "merged")
        elif typename == "ClosedEvent":
            if raw["createdAt"] not in self.merged_times:
                self.add(item, "closed", "closed")
        elif typename == "ReopenedEvent":
            self.add(item, "reopened", "reopened")

        if item.event and item.event.action in (
            ActionType.REVIEW,
            ActionType.APPROVED,
            ActionType.COMMENT,
        ):
            self.has_had_review = True

    def review(self, item: _Item) -> None:
        raw = item.raw
        state = raw.get("state") or ""
        commit = (raw.get("commit") or {}).get("oid")
        on_head = commit is not None and commit == self.node.get("headRefOid")
        text = _REVIEW_TEXT.get(state, state.lower())
        if commit:
            text += " on head" if on_head else f" on {short_sha(commit)}"
        self.add(
            item, "review", text, body=raw.get("body"), state=state, commit=commit, on_head=on_head
        )
        threads = tuple(self.threads.pop(raw.get("id"), []))
        self.entries[-1] = replace(self.entries[-1], threads=threads)
        self.note_report(item, raw.get("body"))

    def run(self) -> list[Entry]:
        self.opened()
        items = [
            prepared
            for raw in self.node["timelineItems"]["nodes"]
            if raw
            if (prepared := _prepare(raw, self.info.author, self.reference_user, self.norms))
        ]
        items.sort(key=lambda i: i.at)
        for item in items:
            self.handle(item)
        self.flush_push()
        for threads in self.threads.values():
            for thread in threads:
                first = thread.comments[0]
                self.entries.append(
                    Entry(
                        at=first.at,
                        kind="thread",
                        char=NO_CHAR,
                        actor=first.actor,
                        actor_class=first.actor_class,
                        text="review thread (its review is not in the timeline)",
                        threads=(thread,),
                    )
                )
        self.entries.sort(key=lambda e: e.at)
        return self.entries

    def reports(self) -> list[ReportStatus]:
        if self.norms is None:
            return []
        current = self.node.get("headRefOid")
        statuses = []
        for name in self.norms.reports:
            if name not in self.report_hits:
                statuses.append(ReportStatus(name=name, found=False))
                continue
            item, head, failed = self.report_hits[name]
            statuses.append(
                ReportStatus(
                    name=name,
                    found=True,
                    at=iso_utc(item.at),
                    actor=item.actor,
                    head=head,
                    on_head=None if head is None else head == current,
                    failed=failed,
                )
            )
        return statuses


def build_pr_show(node: dict, reference_user: str, max_body: int) -> Show:
    builder = _Builder(node, reference_user, max_body)
    entries = builder.run()
    info = builder.info
    linked = [
        f"{n['repository']['nameWithOwner']}#{n['number']}"
        for n in (node.get("closingIssuesReferences") or {}).get("nodes", [])
        if n
    ]
    header = {
        "repo": info.repo,
        "number": info.number,
        "url": item_url(info.repo, KIND_PR, info.number),
        "state": info.state.value,
        "draft": info.is_draft,
        "author": info.author,
        "labels": list(info.labels),
        "created_at": iso_utc(info.created_at),
        "last_activity": iso_utc(info.last_activity),
        "history": info.history,
        "ci": info.ci_status.value,
        "unresolved_threads": info.unresolved_thread_count,
        "head": info.head_sha,
        "mergeable": info.mergeable,
        "merge_state": info.merge_state,
        "review_decision": info.review_decision,
        "reviewers_truncated": info.reviewers_truncated,
        "linked_issues": linked,
    }
    return Show(
        kind="pr",
        repo=info.repo,
        number=info.number,
        title=info.title,
        header=header,
        entries=entries,
        reviewers=[r.to_dict() for r in info.reviewers or ()],
        reports=builder.reports(),
        truncated=is_truncated(node, "timelineItems"),
    )
