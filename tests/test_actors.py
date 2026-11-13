"""Actor classes: classification, history letters, JSON events."""

from __future__ import annotations

import re

import pytest

from src.actors import ActorClass, HistoryEvent, classify_actor, iso_utc
from src.issue.github_api import ISSUE_FIELDS_FRAGMENT
from src.issue.history import process_issue_data
from src.norms import store
from src.norms.model import Norms
from src.norms.schema import parse_norms
from src.pr.github_api import PR_FIELDS_FRAGMENT
from src.pr.history import process_pr_data
from src.review.github_api import ReviewClient
from src.snapshot.convert import item_from_pr
from src.snapshot.models import ItemSnapshot

NORMS_TEXT = """\
schema = 1
[actors]
agent_logins = ["all-hands-bot", "ai-review[bot]"]
agent_disclosure = 'created by an AI agent \\(OpenHands\\)'
bots = ["ci-runner"]
"""
DISCLOSURE = "Done.\n\n_This comment was created by an AI agent (OpenHands) on behalf of @me._"


@pytest.fixture
def norms() -> Norms:
    return parse_norms(NORMS_TEXT).norms


@pytest.fixture
def repo_norms(norms):
    store.set_loader(lambda _repo: norms)


class TestClassifyActor:
    def test_reference_user_is_me(self, norms):
        assert classify_actor("Me", "me", norms) == ActorClass.ME

    def test_reference_user_with_disclosure_is_me_agent(self, norms):
        assert classify_actor("me", "me", norms, DISCLOSURE) == ActorClass.ME_AGENT

    def test_reference_user_without_disclosure_in_body_is_me(self, norms):
        assert classify_actor("me", "me", norms, "just a comment") == ActorClass.ME

    def test_disclosure_anywhere_in_a_long_body_counts(self, norms):
        assert classify_actor("me", "me", norms, "x" * 5000 + DISCLOSURE) == ActorClass.ME_AGENT

    def test_reference_user_listed_as_agent_is_me_agent(self, norms):
        assert classify_actor("all-hands-bot", "all-hands-bot", norms) == ActorClass.ME_AGENT

    def test_disclosure_from_someone_else_is_not_me_agent(self, norms):
        assert classify_actor("alice", "me", norms, DISCLOSURE) == ActorClass.HUMAN

    def test_agent_login(self, norms):
        assert classify_actor("All-Hands-Bot", "me", norms) == ActorClass.AGENT

    def test_agent_login_ending_in_bot_is_agent(self, norms):
        assert classify_actor("ai-review[bot]", "me", norms) == ActorClass.AGENT

    def test_other_bot_suffix_stays_bot(self, norms):
        assert classify_actor("dependabot[bot]", "me", norms) == ActorClass.BOT

    def test_listed_bot_is_bot(self, norms):
        assert classify_actor("ci-runner", "me", norms) == ActorClass.BOT

    def test_human(self, norms):
        assert classify_actor("alice", "me", norms) == ActorClass.HUMAN

    @pytest.mark.parametrize(
        ("login", "expected"),
        [
            ("all-hands-bot", ActorClass.HUMAN),
            ("dependabot[bot]", ActorClass.BOT),
            ("me", ActorClass.ME),
        ],
    )
    def test_no_norms_recognises_no_ai_actors(self, login, expected):
        assert classify_actor(login, "me", None, DISCLOSURE) == expected

    def test_norms_without_disclosure_pattern(self):
        bare = parse_norms("schema = 1\n").norms
        assert classify_actor("me", "me", bare, DISCLOSURE) == ActorClass.ME

    def test_is_ai(self):
        assert {c for c in ActorClass if c.is_ai} == {ActorClass.AGENT, ActorClass.ME_AGENT}

    def test_values_are_the_json_names(self):
        assert [c.value for c in ActorClass] == ["me", "human", "bot", "agent", "me_agent"]


class TestHistoryEvent:
    def test_to_dict(self):
        event = HistoryEvent(
            "N", "comment", "all-hands-bot", ActorClass.AGENT, "2024-01-02T03:04:05Z"
        )
        assert event.to_dict()["actor_class"] == "agent"

    def test_iso_utc(self):
        from datetime import UTC, datetime

        assert iso_utc(datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2024-01-02T03:04:05Z"


def review(login: str, state: str, at: str, body: str = "", inline: int = 0) -> dict:
    return {
        "__typename": "PullRequestReview",
        "author": {"login": login},
        "body": body,
        "state": state,
        "createdAt": at,
        "comments": {"totalCount": inline},
    }


def pr_data(*nodes: dict, author: str = "alice") -> dict:
    return {
        "repository": {"nameWithOwner": "owner/repo"},
        "number": 1,
        "title": "t",
        "author": {"login": author},
        "createdAt": "2024-01-01T00:00:00Z",
        "closedAt": None,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "reviewThreads": {"nodes": []},
        "commits": {"nodes": []},
        "timelineItems": {"nodes": list(nodes)},
    }


class TestPrHistory:
    @pytest.mark.usefixtures("repo_norms")
    def test_agent_and_human_reviews_differ(self):
        info = process_pr_data(
            pr_data(
                review("all-hands-bot", "CHANGES_REQUESTED", "2024-01-02T00:00:00Z"),
                review("bob", "CHANGES_REQUESTED", "2024-01-03T00:00:00Z"),
            ),
            "alice",
        )
        assert info.history == "oER"
        assert [(e.actor, e.actor_class) for e in info.events] == [
            ("alice", ActorClass.ME),
            ("all-hands-bot", ActorClass.AGENT),
            ("bob", ActorClass.HUMAN),
        ]

    @pytest.mark.usefixtures("repo_norms")
    def test_agent_approval_and_comment_letters(self):
        info = process_pr_data(
            pr_data(
                review("all-hands-bot", "APPROVED", "2024-01-02T00:00:00Z"),
                review("all-hands-bot", "COMMENTED", "2024-01-03T00:00:00Z"),
                review("bob", "APPROVED", "2024-01-04T00:00:00Z"),
            ),
            "alice",
        )
        assert info.history == "oVNA"

    @pytest.mark.usefixtures("repo_norms")
    def test_inline_agent_review_is_a_changes_letter(self):
        info = process_pr_data(
            pr_data(review("all-hands-bot", "COMMENTED", "2024-01-02T00:00:00Z", inline=2)),
            "alice",
        )
        assert info.history == "oE"

    @pytest.mark.usefixtures("repo_norms")
    def test_consecutive_agent_and_human_comments_do_not_collapse(self):
        comment = {"__typename": "IssueComment", "createdAt": "2024-01-02T00:00:00Z"}
        info = process_pr_data(
            pr_data(
                {**comment, "author": {"login": "bob"}},
                {**comment, "author": {"login": "carol"}},
                {**comment, "author": {"login": "all-hands-bot"}},
                {**comment, "author": {"login": "openhands-agent[bot]"}},
            ),
            "alice",
        )
        assert info.history == "oCNC"

    @pytest.mark.usefixtures("repo_norms")
    def test_agent_listed_bot_suffix_is_agent_other_bot_is_not(self):
        info = process_pr_data(
            pr_data(
                review("ai-review[bot]", "APPROVED", "2024-01-02T00:00:00Z"),
                review("dependabot[bot]", "APPROVED", "2024-01-03T00:00:00Z"),
            ),
            "alice",
        )
        assert info.history == "oVA"
        assert [e.actor_class.value for e in info.events] == ["me", "agent", "bot"]

    @pytest.mark.usefixtures("repo_norms")
    def test_my_comment_with_disclosure_is_me_agent_and_lowercase(self):
        info = process_pr_data(
            pr_data(
                {
                    "__typename": "IssueComment",
                    "author": {"login": "alice"},
                    "body": DISCLOSURE,
                    "createdAt": "2024-01-02T00:00:00Z",
                },
                {
                    "__typename": "IssueComment",
                    "author": {"login": "alice"},
                    "body": "plain",
                    "createdAt": "2024-01-03T00:00:00Z",
                },
            ),
            "alice",
        )
        assert info.history == "onc"
        assert [e.actor_class.value for e in info.events] == ["me", "me_agent", "me"]

    def test_no_norms_gives_the_golden_strings(self):
        data = pr_data(
            review("all-hands-bot", "CHANGES_REQUESTED", "2024-01-02T00:00:00Z"),
            review("bob", "APPROVED", "2024-01-03T00:00:00Z", body=DISCLOSURE),
        )
        info = process_pr_data(data, "alice")
        assert info.history == "oRA"
        assert {e.actor_class for e in info.events} <= {ActorClass.ME, ActorClass.HUMAN}

    @pytest.mark.usefixtures("repo_norms")
    def test_events_line_up_with_history_characters(self):
        info = process_pr_data(
            pr_data(
                review("all-hands-bot", "CHANGES_REQUESTED", "2024-01-02T00:00:00Z"),
                review("all-hands-bot", "CHANGES_REQUESTED", "2024-01-02T01:00:00Z"),
            ),
            "alice",
        )
        assert "".join(e.char for e in info.events) == info.history == "oE"
        assert info.events[1].action == "review"
        assert info.events[1].at == "2024-01-02T00:00:00Z"


def issue_data(*nodes: dict) -> dict:
    return {
        "number": 1,
        "title": "t",
        "state": "OPEN",
        "createdAt": "2024-01-15T10:00:00Z",
        "closedAt": None,
        "author": {"login": "alice"},
        "repository": {"nameWithOwner": "owner/repo"},
        "labels": {"nodes": []},
        "timelineItems": {"nodes": list(nodes)},
    }


def comment(login: str, at: str, body: str = "") -> dict:
    return {
        "__typename": "IssueComment",
        "author": {"login": login},
        "body": body,
        "createdAt": at,
    }


class TestIssueHistory:
    @pytest.mark.usefixtures("repo_norms")
    def test_comment_with_my_token_and_disclosure_is_me_agent(self):
        info = process_issue_data(
            issue_data(
                comment("alice", "2024-01-15T11:00:00Z", DISCLOSURE),
                comment("alice", "2024-01-15T12:00:00Z", "human words"),
            ),
            "alice",
        )
        assert info.history == "onc"
        assert info.events[1].actor_class == ActorClass.ME_AGENT
        assert info.events[2].actor_class == ActorClass.ME

    @pytest.mark.usefixtures("repo_norms")
    def test_agent_login_comment_is_n(self):
        info = process_issue_data(
            issue_data(comment("all-hands-bot", "2024-01-15T11:00:00Z")), "alice"
        )
        assert info.history == "oN"
        assert info.events[1].actor_class == ActorClass.AGENT

    @pytest.mark.usefixtures("repo_norms")
    def test_agent_bot_suffix_is_agent_but_other_bots_stay_B(self):
        info = process_issue_data(
            issue_data(
                comment("ai-review[bot]", "2024-01-15T11:00:00Z"),
                comment("dependabot[bot]", "2024-01-15T12:00:00Z"),
                comment("ci-runner", "2024-01-15T13:00:00Z"),
            ),
            "alice",
        )
        assert info.history == "oNB"
        assert [e.actor_class.value for e in info.events] == ["me", "agent", "bot"]

    @pytest.mark.usefixtures("repo_norms")
    def test_agent_and_human_comments_do_not_collapse(self):
        info = process_issue_data(
            issue_data(
                comment("bob", "2024-01-15T11:00:00Z"),
                comment("all-hands-bot", "2024-01-15T12:00:00Z"),
                comment("carol", "2024-01-15T13:00:00Z"),
            ),
            "alice",
        )
        assert info.history == "oCNC"

    def test_no_norms_no_ai_actors(self):
        info = process_issue_data(
            issue_data(
                comment("all-hands-bot", "2024-01-15T11:00:00Z"),
                comment("dependabot[bot]", "2024-01-15T12:00:00Z"),
                comment("alice", "2024-01-15T13:00:00Z", DISCLOSURE),
            ),
            "alice",
        )
        assert info.history == "oCBc"
        assert [e.actor_class.value for e in info.events] == ["me", "human", "bot", "me"]


class TestReviewHistory:
    @pytest.mark.usefixtures("repo_norms")
    def test_review_queue_marks_agent_reviews(self):
        data = pr_data(review("all-hands-bot", "APPROVED", "2024-01-02T00:00:00Z"))
        client = ReviewClient.__new__(ReviewClient)
        info = client._process_pr_for_reviewer(data, "bob")
        assert info is not None
        assert info.history == "OV"
        assert [e.actor_class.value for e in info.events] == ["human", "agent"]


class TestSnapshotJson:
    @pytest.mark.usefixtures("repo_norms")
    def test_rows_carry_the_history_string_but_not_its_events(self):
        info = process_pr_data(
            pr_data(review("all-hands-bot", "APPROVED", "2024-01-02T00:00:00Z")), "alice"
        )
        row = item_from_pr(info).to_dict()
        assert row["history"] == info.history
        assert "events" not in row
        assert ItemSnapshot.from_dict(row) == item_from_pr(info)


@pytest.mark.parametrize(
    ("fragment", "types"),
    [
        (PR_FIELDS_FRAGMENT, ("PullRequestReview", "IssueComment")),
        (ISSUE_FIELDS_FRAGMENT, ("IssueComment",)),
    ],
)
def test_queries_fetch_the_comment_bodies_the_disclosure_check_reads(fragment, types):
    for typename in types:
        block = fragment.split(f"... on {typename} {{", 1)[1].split("... on", 1)[0]
        assert re.search(r"^\s*body\s*$", block, re.MULTILINE), typename
