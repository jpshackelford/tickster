"""An item an AI actor opened starts with s / S, in every view that shows a history."""

import re

import pytest

from src.issue.github_api import ISSUE_FIELDS_FRAGMENT
from src.issue.history import process_issue_data
from src.norms import store as norms_store
from src.norms.schema import parse_norms
from src.pr.github_api import PR_FIELDS_FRAGMENT
from src.pr.history import process_pr_data
from src.show.issue import build_issue_show
from src.show.pr import build_pr_show
from src.show.render import ISSUE_LEGEND, PR_LEGEND
from src.snapshot.diff import diff_snapshots
from tests.show.builders import comment, issue_node, login, pr_node, review, ts
from tests.snapshot.conftest import make_item, make_snapshot

DISCLOSURE = "created by an AI agent (OpenHands) on behalf of @alice"
NORMS = parse_norms("""\
schema = 1

[actors]
agent_logins = ["all-hands-bot", "alice-agent"]
agent_disclosure = 'created by an AI agent \\(OpenHands\\)'
""").norms

# (author, body, expected first character) for reference user "alice"
OPENED_CASES = [
    pytest.param("all-hands-bot", "plain", "S", id="agent-login-own-account"),
    pytest.param("alice", "plain", "o", id="reference-user-human"),
    pytest.param("alice", f"Fixes #1\n\n{DISCLOSURE}", "s", id="reference-user-disclosure"),
    pytest.param("bob", f"Fixes #1\n\n{DISCLOSURE}", "O", id="other-user-disclosure-is-human"),
    pytest.param("bob", "plain", "O", id="other-human"),
    pytest.param("dependabot[bot]", "plain", "O", id="bot"),
]


@pytest.fixture(autouse=True)
def norms():
    norms_store.set_loader(lambda _repo: NORMS)


def pr(author: str, body: str | None, timeline: list | None = None) -> dict:
    return pr_node(timeline or [], author=login(author), body=body)


def issue(author: str, body: str | None, timeline: list | None = None) -> dict:
    return issue_node(timeline or [], author=login(author), body=body)


class TestFirstCharacter:
    @pytest.mark.parametrize(("author", "body", "char"), OPENED_CASES)
    def test_pr_list(self, author, body, char):
        info = process_pr_data(pr(author, body), "alice")
        assert info.history == char
        assert info.events[0].char == char

    @pytest.mark.parametrize(("author", "body", "char"), OPENED_CASES)
    def test_issue_list(self, author, body, char):
        info = process_issue_data(issue(author, body), "alice")
        assert info.history == char
        assert info.events[0].char == char

    @pytest.mark.parametrize(("author", "body", "char"), OPENED_CASES)
    def test_pr_show_agrees_with_list(self, author, body, char):
        node = pr(author, body)
        show = build_pr_show(node, "alice", 100)
        assert show.entries[0].char == char == process_pr_data(node, "alice").history[0]

    @pytest.mark.parametrize(("author", "body", "char"), OPENED_CASES)
    def test_issue_show_agrees_with_list(self, author, body, char):
        node = issue(author, body)
        show = build_issue_show(node, "alice", 100)
        assert show.entries[0].char == char == process_issue_data(node, "alice").history[0]

    def test_item_without_a_body_is_unchanged(self):
        assert process_pr_data(pr("alice", None), "alice").history == "o"
        assert process_issue_data(issue("alice", None), "alice").history == "o"

    def test_no_norms_file_leaves_output_unchanged(self):
        norms_store.set_loader(lambda _repo: None)
        for author, body in (("all-hands-bot", DISCLOSURE), ("alice", DISCLOSURE)):
            expected = "O" if author != "alice" else "o"
            assert process_pr_data(pr(author, body), "alice").history == expected
            assert process_issue_data(issue(author, body), "alice").history == expected


class TestFullStrings:
    def test_pr_opened_by_an_agent_then_reviewed_and_approved(self):
        timeline = [
            review("R1", "all-hands-bot", "CHANGES_REQUESTED", ts(11), "c1", "Please fix"),
            review("R2", "all-hands-bot", "APPROVED", ts(12), "c1", "LGTM"),
        ]
        info = process_pr_data(pr("all-hands-bot", "plain", timeline), "alice")
        assert info.history == "SEV"
        assert [e.char for e in info.events] == list(info.history)
        assert info.events[0].actor_class.value == "agent"

    def test_issue_opened_by_an_agent_then_commented(self):
        timeline = [
            comment("bob", ts(10), "a human comment"),
            comment("all-hands-bot", ts(11), f"expanded {DISCLOSURE}"),
        ]
        info = process_issue_data(issue("all-hands-bot", "plain", timeline), "alice")
        assert info.history == "SCN"
        assert info.events[0].char == info.history[0]

    def test_reference_user_agent_opens_and_comments(self):
        node = issue("alice", DISCLOSURE, [comment("alice", ts(10), DISCLOSURE)])
        assert process_issue_data(node, "alice").history == "sn"


class TestLegendsAndFragments:
    def test_legends_name_the_letter(self):
        assert "s AI opened" in PR_LEGEND
        assert "v AI approval" in PR_LEGEND
        assert "e AI review" in PR_LEGEND
        assert "s AI opened" in ISSUE_LEGEND
        assert "n AI comment" in ISSUE_LEGEND

    def test_s_is_free_in_the_existing_tables(self):
        pr_letters = set("ohrace vnfmk".replace(" ", ""))
        issue_letters = set("ocBlaxrpn")
        assert "s" not in pr_letters | issue_letters
        legend_letters = re.findall(r"\b([a-zA-Z]) (?:opened|review|comment|labeled)", PR_LEGEND)
        assert "s" not in legend_letters
        assert "s opened" not in PR_LEGEND

    @pytest.mark.parametrize("fragment", [PR_FIELDS_FRAGMENT, ISSUE_FIELDS_FRAGMENT])
    def test_list_fragments_fetch_the_body(self, fragment):
        top_level = re.sub(r"\{[^{}]*\}", "", fragment.split("{", 1)[1])
        assert re.search(r"^\s*body\s*$", fragment, re.M)
        assert "body" in top_level


class TestSnapshots:
    def test_history_character_change_is_reported_once(self):
        prev = make_snapshot(items=[make_item(ref="a/b#1", history="Oam")])
        curr = make_snapshot(items=[make_item(ref="a/b#1", history="Sam")])
        delta = diff_snapshots(prev, curr).deltas[0]
        assert "history-rewritten" in delta.changed_fields
