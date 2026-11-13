"""Tests for `tkt issue show`."""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from src.__main__ import main
from src.board import config as board_config
from src.norms import store as norms_store
from src.norms.schema import parse_norms
from src.snapshot import store as snapshot_store
from tests.show.builders import comment, conn, issue_node, login, ts
from tests.show.fake_github import FakeGitHub
from tests.snapshot.conftest import make_item, make_snapshot

NORMS = parse_norms("""\
schema = 1

[actors]
agent_logins = ["all-hands-bot"]
agent_disclosure = 'created by an AI agent \\(OpenHands\\)'
""").norms


FIXTURES = Path(__file__).parent.parent / "fixtures"


def closing(number: int, state: str, at: str, who: str = "bob", repo: str = "o/r") -> dict:
    return {
        "number": number,
        "state": state,
        "createdAt": at,
        "author": login(who),
        "repository": {"nameWithOwner": repo},
    }


def event(typename: str, who: str, at: str, **fields) -> dict:
    return {"__typename": typename, "actor": login(who), "createdAt": at, **fields}


def busy_issue(**overrides) -> dict:
    timeline = [
        comment("bob", ts(10), "Have you considered a flag?"),
        comment("dependabot[bot]", ts(10, 5), "Bumps a dependency."),
        comment("all-hands-bot", ts(10, 10), "Expanded.\n\ncreated by an AI agent (OpenHands)"),
        event("LabeledEvent", "alice", ts(10, 15), label={"name": "ready"}),
        event("AssignedEvent", "alice", ts(10, 20), assignee=login("bob")),
        event(
            "CrossReferencedEvent",
            "bob",
            ts(11),
            source={
                "__typename": "PullRequest",
                "number": 55,
                "repository": {"nameWithOwner": "o/r"},
                "state": "OPEN",
            },
        ),
        comment("alice", ts(12), "Thanks, going with the PR."),
        event("ClosedEvent", "alice", ts(13)),
    ]
    return issue_node(timeline, **overrides)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_USERNAME", "alice")
    monkeypatch.setattr(board_config, "TKT_HOME", tmp_path)
    norms_store.set_loader(lambda _repo: NORMS)


@pytest.fixture
def show(capsys):
    def _show(node: dict | None, *args: str, ref: str = "o/r#40") -> tuple[int, str, str]:
        fake = FakeGitHub("issue", node)
        with patch("src.show.cli.GitHubClient", return_value=fake.client()):
            code = main(["issue", "show", ref, *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _show


class TestText:
    def test_header(self, show):
        code, out, _ = show(busy_issue())

        lines = out.splitlines()
        assert code == 0
        assert lines[0] == 'o/r#40 issue open "Show a timeline"'
        assert lines[1] == "history: oCBNlaPcx"
        assert "labels: enhancement, ready  assignees: bob" in lines
        assert "linked PRs: o/r#55 (open)" in lines
        assert any(line.startswith("Legend:") for line in lines)

    def test_timeline_has_human_bot_and_ai_comments(self, show):
        _, out, _ = show(busy_issue())

        events = out.split("timeline: 9 events, oldest first\n")[1].splitlines()
        assert events == [
            "2026-11-05T09:00:00Z o alice(me) opened: We need a timeline.",
            "2026-11-05T10:00:00Z C bob(human) commented: Have you considered a flag?",
            "2026-11-05T10:05:00Z B dependabot[bot](bot) commented: Bumps a dependency.",
            "2026-11-05T10:10:00Z N all-hands-bot(agent) commented: Expanded. "
            "created by an AI agent (OpenHands)",
            "2026-11-05T10:15:00Z l alice(me) labeled ready",
            "2026-11-05T10:20:00Z a alice(me) assigned bob",
            "2026-11-05T11:00:00Z P bob(human) linked PR o/r#55 (open)",
            "2026-11-05T12:00:00Z c alice(me) commented: Thanks, going with the PR.",
            "2026-11-05T13:00:00Z x alice(me) closed",
        ]

    def test_reference_users_own_ai_comment_is_me_agent(self, show):
        node = issue_node([comment("alice", ts(10), "ok\n\ncreated by an AI agent (OpenHands)")])

        _, out, _ = show(node)

        assert "n alice(me_agent) commented: ok created by an AI agent (OpenHands)" in out

    def test_no_assignees_or_labels(self, show):
        node = issue_node([], assignees=conn([]), labels=conn([]))

        _, out, _ = show(node)

        assert "labels: --  assignees: --" in out
        assert "linked PRs: --" in out
        assert "timeline: 1 events, oldest first" in out

    def test_deleted_authors_do_not_abort(self, show):
        node = issue_node(
            [comment(None, ts(10), "gone"), event("LabeledEvent", "", ts(11), label=None)],
            author=None,
        )

        code, out, _ = show(node)

        assert code == 0
        assert "ghost(human) commented: gone" in out

    def test_removed_labels_and_assignees_are_listed(self, show):
        node = issue_node(
            [
                event("LabeledEvent", "alice", ts(10), label={"name": "hold"}),
                event("UnlabeledEvent", "alice", ts(11), label={"name": "hold"}),
                event("AssignedEvent", "alice", ts(12), assignee=login("bob")),
                event("UnassignedEvent", "carol", ts(13), assignee=login("bob")),
            ]
        )

        _, out, _ = show(node, "--format", "json")

        events = json.loads(out)["events"]
        assert [(e["kind"], e["char"], e["text"]) for e in events[1:]] == [
            ("labeled", "l", "labeled hold"),
            ("unlabeled", "-", "unlabeled hold"),
            ("assigned", "a", "assigned bob"),
            ("unassigned", "-", "unassigned bob"),
        ]
        assert events[2]["label"] == "hold"
        assert events[4]["assignee"] == "bob"
        assert events[4]["actor_class"] == "human"

    def test_closed_pr_link_is_reported_with_its_state(self, show):
        node = issue_node(
            [
                event(
                    "CrossReferencedEvent",
                    "bob",
                    ts(11),
                    source={
                        "__typename": "PullRequest",
                        "number": 9,
                        "repository": {"nameWithOwner": "o/r"},
                        "state": "CLOSED",
                    },
                ),
                event(
                    "CrossReferencedEvent",
                    "bob",
                    ts(12),
                    source={"__typename": "Issue", "number": 3},
                ),
            ]
        )

        _, out, _ = show(node, "--format", "json")

        data = json.loads(out)
        assert data["linked_prs"] == [{"ref": "o/r#9", "state": "closed"}]
        assert data["linked_pr"] == "o/r#9"
        assert [e["kind"] for e in data["events"]] == ["opened", "pr_linked"]


class TestClosingKeyword:
    """`Fixes #N` in a PR leaves no timeline item; GitHub lists it as a closing reference."""

    def test_recorded_issue_closed_by_a_merged_pr(self, show):
        node = json.loads((FIXTURES / "issue_40_closed_by_pr_69.json").read_text())

        code, out, err = show(node, ref="jpshackelford/tickster#40")

        assert code == 0, err
        lines = out.splitlines()
        assert "linked PRs: jpshackelford/tickster#69 (merged)" in lines
        history = next(line for line in lines if line.startswith("history: "))
        assert "p" in history.lower()
        timeline = [line.split(maxsplit=2)[1] for line in lines if line.startswith("2026-")]
        assert timeline[-2:] == ["P", "X"]

    def test_open_closing_pr_is_linked_without_an_x(self, show):
        node = issue_node([], closedByPullRequestsReferences=conn([closing(85, "OPEN", ts(11))]))

        _, out, _ = show(node, "--format", "json")

        data = json.loads(out)
        assert data["history"] == "oP"
        assert data["linked_pr"] == "o/r#85"
        assert data["linked_prs"] == [{"ref": "o/r#85", "state": "open"}]
        assert data["events"][1]["kind"] == "pr_linked"
        assert data["events"][1]["pr"] == "o/r#85"

    def test_pr_found_by_cross_reference_and_closing_reference_is_listed_once(self, show):
        cross = event(
            "CrossReferencedEvent",
            "bob",
            ts(11),
            source={
                "__typename": "PullRequest",
                "number": 55,
                "repository": {"nameWithOwner": "o/r"},
                "state": "OPEN",
            },
        )
        node = issue_node(
            [cross], closedByPullRequestsReferences=conn([closing(55, "OPEN", ts(10))])
        )

        _, out, _ = show(node, "--format", "json")

        data = json.loads(out)
        assert data["linked_prs"] == [{"ref": "o/r#55", "state": "open"}]
        assert [e["kind"] for e in data["events"]] == ["opened", "pr_linked"]

    def test_merged_pr_is_the_linked_pr_over_an_earlier_closed_one(self, show):
        node = issue_node(
            [],
            closedByPullRequestsReferences=conn(
                [closing(9, "CLOSED", ts(10)), closing(12, "MERGED", ts(11))]
            ),
        )

        _, out, _ = show(node, "--format", "json")

        data = json.loads(out)
        assert data["linked_pr"] == "o/r#12"
        assert [p["ref"] for p in data["linked_prs"]] == ["o/r#9", "o/r#12"]

    def test_a_closing_pr_from_another_repo_keeps_its_repo(self, show):
        node = issue_node(
            [], closedByPullRequestsReferences=conn([closing(2, "MERGED", ts(11), repo="x/y")])
        )

        _, out, _ = show(node)

        assert "linked PRs: x/y#2 (merged)" in out

    def test_the_query_asks_for_closing_references(self):
        fake = FakeGitHub("issue", issue_node([]))
        with patch("src.show.cli.GitHubClient", return_value=fake.client()):
            main(["issue", "show", "o/r#40"])

        assert (
            "closedByPullRequestsReferences(first: 10, includeClosedPrs: true)"
            in (fake.requests[0]["query"])
        )


class TestJson:
    def test_carries_header_and_events(self, show):
        code, out, _ = show(busy_issue(), "--format", "json")

        data = json.loads(out)
        assert code == 0
        assert data["kind"] == "issue"
        assert data["ref"] == "o/r#40"
        assert data["state"] == "open"
        assert data["labels"] == ["enhancement", "ready"]
        assert data["assignees"] == ["bob"]
        assert data["history"] == "oCBNlaPcx"
        assert "reviewers" not in data
        kinds = [e["kind"] for e in data["events"]]
        assert kinds == [
            "opened",
            "comment",
            "comment",
            "comment",
            "labeled",
            "assigned",
            "pr_linked",
            "comment",
            "closed",
        ]
        bot, agent = data["events"][2], data["events"][3]
        assert (bot["char"], bot["actor_class"]) == ("B", "bot")
        assert (agent["char"], agent["actor_class"]) == ("N", "agent")
        assert data["events"][4]["label"] == "ready"
        assert data["events"][5]["assignee"] == "bob"
        assert data["events"][6]["pr"] == "o/r#55"


class TestSince:
    def test_only_newer_events(self, show):
        _, out, _ = show(busy_issue(), "--since-time", "2026-11-05T11:30:00Z")

        events = [line for line in out.splitlines() if line.startswith("2026-")]
        assert [line.split()[1] for line in events] == ["c", "x"]

    def test_no_new_events_prints_header_and_message(self, show):
        code, out, _ = show(busy_issue(), "--since-time", "2026-11-06T00:00:00Z")

        lines = out.splitlines()
        assert code == 0
        assert lines[0].startswith("o/r#40 issue open")
        assert lines[-1] == "no new events since 2026-11-06T00:00:00Z"

    def test_since_snapshot(self, show):
        item = make_item(key="o/r#40", last_activity="2026-11-05T12:30:00Z")
        snapshot_store.save(make_snapshot(kind="issue", name="tick", items=[item]))

        _, out, _ = show(busy_issue(), "--since-snapshot", "issue/tick")

        events = [line for line in out.splitlines() if line.startswith("2026-")]
        assert [line.split()[1] for line in events] == ["x"]

    def test_pr_snapshot_is_rejected(self, show):
        snapshot_store.save(make_snapshot(kind="pr", name="tick", items=[]))

        code, _, err = show(busy_issue(), "--since-snapshot", "pr/tick")

        assert code == 1
        assert "`issue show` reads an issue snapshot, not pr" in err


class TestBodiesAndCompleteness:
    def test_max_body(self, show):
        node = issue_node([comment("bob", ts(10), "x" * 50)], body="y" * 25)

        _, out, _ = show(node, "--max-body", "10")

        assert f"opened: {'y' * 10}…(15 more chars)" in out
        assert f"commented: {'x' * 10}…(40 more chars)" in out

    def test_zero_means_no_trimming(self, show):
        node = issue_node([comment("bob", ts(10), "x" * 2000)])

        _, out, _ = show(node, "--max-body", "0")

        assert "x" * 2000 in out

    def test_a_timeline_of_more_than_100_events_is_complete(self, show):
        comments = [comment("bob", ts(10 + i // 60, i % 60), f"c{i}") for i in range(230)]

        _, out, _ = show(issue_node(comments), "--format", "json")

        data = json.loads(out)
        assert [e["body"] for e in data["events"][1:]] == [f"c{i}" for i in range(230)]

    def test_labels_past_the_first_page_are_listed(self, show):
        labels = conn([{"name": f"l{i:02d}"} for i in range(45)])

        _, out, _ = show(issue_node([], labels=labels), "--format", "json")

        assert len(json.loads(out)["labels"]) == 45


class TestErrors:
    def test_unknown_issue(self, show):
        code, out, err = show(None)

        assert code == 1
        assert out == ""
        assert "issue not found: o/r#40" in err

    def test_bad_reference(self, show):
        code, _, err = show(busy_issue(), ref="o/r")

        assert code == 1
        assert "Invalid issue reference" in err

    def test_accepts_an_issue_url(self, show):
        code, out, _ = show(busy_issue(), ref="https://github.com/o/r/issues/40")

        assert code == 0
        assert out.startswith("o/r#40 issue open")

    def test_a_pr_url_is_not_an_issue_reference(self, show):
        code, _, err = show(busy_issue(), ref="https://github.com/o/r/pull/40")

        assert code == 1
        assert "Invalid issue reference" in err


def dep(number: int, state: str = "OPEN", repo: str = "o/r") -> dict:
    return {"number": number, "state": state, "repository": {"nameWithOwner": repo}}


def blockers(*nodes: dict) -> dict:
    return {"totalCount": len(nodes), "nodes": list(nodes)}


class TestDependencies:
    def test_json_carries_the_four_facts(self, show):
        node = issue_node(
            [],
            blockedBy=blockers(dep(121), dep(122, "CLOSED"), dep(5, repo="x/y")),
            blocking=blockers(dep(7), dep(8, "CLOSED")),
            parent={"number": 120, "repository": {"nameWithOwner": "o/r"}},
            milestone={"title": "v2", "dueOn": "2026-12-01T00:00:00Z"},
        )

        _, out, _ = show(node, "--format", "json")

        data = json.loads(out)
        assert data["open_blockers"] == ["o/r#121", "x/y#5"]
        assert data["blocking"] == 1
        assert data["parent"] == "o/r#120"
        assert data["milestone"] == {"title": "v2", "due_on": "2026-12-01T00:00:00Z"}

    def test_json_has_empty_facts_for_an_issue_without_any(self, show):
        _, out, _ = show(issue_node([]), "--format", "json")

        data = json.loads(out)
        assert data["open_blockers"] == []
        assert data["blocking"] == 0
        assert data["parent"] is None
        assert data["milestone"] is None

    def test_text_prints_one_line_with_the_non_empty_parts(self, show):
        node = issue_node(
            [],
            blockedBy=blockers(dep(121), dep(123), dep(122, "CLOSED")),
            blocking=blockers(dep(7)),
            parent={"number": 120, "repository": {"nameWithOwner": "o/r"}},
            milestone={"title": "v2", "dueOn": None},
        )

        _, out, _ = show(node)

        assert "blocked by: #121, #123  blocks: 1  parent: #120  milestone: v2" in out.splitlines()

    def test_text_omits_the_line_when_there_is_nothing_to_say(self, show):
        _, out, _ = show(issue_node([]))

        starts = ("blocked by:", "blocks:", "parent:", "milestone:")
        assert [line for line in out.splitlines() if line.startswith(starts)] == []

    def test_an_unreadable_blocker_is_a_question_mark(self, show):
        node = issue_node([], blockedBy={"totalCount": 2, "nodes": [dep(121)]})

        _, out, _ = show(node)

        assert "blocked by: #121, ?" in out.splitlines()

    def test_more_than_50_blockers_are_paged_not_cut(self, show):
        node = issue_node([], blockedBy=blockers(*(dep(n) for n in range(1, 131))))

        _, out, _ = show(node, "--format", "json")

        data = json.loads(out)
        assert len(data["open_blockers"]) == 130
        assert "?" not in data["open_blockers"]


class TestRemovedSince:
    """`--since` on show is a hidden stub that points at `--since-time`."""

    MESSAGE = "--since was removed on show: use --since-time TS"

    @pytest.mark.parametrize(
        "argv",
        [["--since", "2026-11-05T10:00:00Z"], ["--since=2026-11-05T10:00:00Z"], ["--since"]],
        ids=["separate", "equals", "bare"],
    )
    def test_fails_at_parse_time_with_no_github_call(self, argv, capsys):
        with patch("src.show.cli.GitHubClient") as client, pytest.raises(SystemExit) as exc:
            main(["issue", "show", "o/r#40", *argv])

        captured = capsys.readouterr()
        assert exc.value.code == 2
        assert captured.out == ""
        assert f"tkt issue show: error: {self.MESSAGE}" in captured.err
        client.assert_not_called()

    def test_wins_over_the_snapshot_exclusion_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["issue", "show", "o/r#40", "--since", "T", "--since-snapshot", "issue/tick"])

        assert exc.value.code == 2
        assert self.MESSAGE in capsys.readouterr().err

    def test_prefixes_of_the_new_flags_still_resolve(self, show):
        code, out, _ = show(busy_issue(), "--since-t", "2026-12-01T00:00:00Z")

        assert code == 0
        assert "no new events since 2026-12-01T00:00:00Z" in out

    def test_help_lists_the_new_flags_and_hides_the_stub(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["issue", "show", "--help"])

        out = capsys.readouterr().out
        assert exc.value.code == 0
        assert "--since-time TS" in out
        assert "--since-snapshot KIND/NAME" in out
        assert not re.search(r"--since(\s|$)", out)
