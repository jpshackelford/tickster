"""Tests for `tkt pr show`: header, timeline, threads, pushes, --since, --max-body."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from src.__main__ import main
from src.board import config as board_config
from src.norms import store as norms_store
from src.norms.schema import parse_norms
from src.show.pr import PR_SHOW_TIMELINE
from src.snapshot import store as snapshot_store
from tests.show.builders import (
    C1,
    C2,
    HEAD,
    comment,
    commit,
    conn,
    pr_node,
    request,
    review,
    thread,
    thread_comment,
    ts,
)
from tests.show.fake_github import FakeGitHub
from tests.snapshot.conftest import make_item, make_snapshot

NORMS = parse_norms("""\
schema = 1

[actors]
agent_logins = ["all-hands-bot"]
agent_disclosure = 'created by an AI agent \\(OpenHands\\)'

[reports.manual_test]
marker = '^#+ *Manual Test Results'
fail = '❌ *FAIL'

[reports.docs_review]
marker = '^## Docs review'
""").norms

BOT_REPORT = "## Manual Test Results\n\n❌ FAIL: the CLI crashes\nSee logs."


def busy_pr(**overrides) -> dict:
    timeline = [
        commit(C1, "alice", ts(10, 5), "initial"),
        request("bob", ts(10, 10), "alice"),
        review("R1", "bob", "CHANGES_REQUESTED", ts(11), C1, "Please rename foo to bar"),
        commit(C2, "alice", ts(12)),
        commit(HEAD, "alice", ts(12, 1), "address review"),
        review("R2", "bob", "APPROVED", ts(13), HEAD, "LGTM once the nit is fixed"),
        comment("carol", ts(13, 30), "Looks good to me"),
        comment("all-hands-bot", ts(13, 40), BOT_REPORT),
        comment(None, ts(13, 50), "from a deleted user"),
    ]
    threads = [
        thread(
            "T1",
            "src/a.py",
            12,
            False,
            [
                thread_comment("bob", ts(11), "rename this", "R1"),
                thread_comment("alice", ts(11, 30), "done", "R3"),
            ],
        ),
        thread("T2", "src/b.py", 3, True, [thread_comment("bob", ts(13), "nit", "R2")]),
    ]
    reviews = conn(
        [
            {
                "author": {"login": "bob"},
                "state": "APPROVED",
                "submittedAt": ts(13),
                "commit": {"oid": HEAD},
            }
        ]
    )
    return pr_node(timeline, threads, latestReviews=reviews, **overrides)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_USERNAME", "alice")
    monkeypatch.setattr(board_config, "TKT_HOME", tmp_path)
    norms_store.set_loader(lambda _repo: NORMS)


@pytest.fixture
def show(capsys):
    def _show(node: dict | None, *args: str, ref: str = "o/r#7") -> tuple[int, str, str]:
        fake = FakeGitHub("pullRequest", node)
        with patch("src.show.cli.GitHubClient", return_value=fake.client()):
            code = main(["pr", "show", ref, *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _show


class TestText:
    def test_header(self, show):
        code, out, _ = show(busy_pr())

        lines = out.splitlines()
        assert code == 0
        assert lines[0] == 'o/r#7 pr open ready ci:green 💬1 "Add the thing"'
        assert lines[1] == "history: ohRfACNC"
        assert "head: c3c3c3c  mergeable: mergeable  merge: clean  review: approved" in lines
        assert "reviewers: bob(human) ✓ approved on head" in lines
        assert "linked issues: o/r#40" in lines
        assert any(line.startswith("Legend:") for line in lines)

    def test_report_status_in_header(self, show):
        _, out, _ = show(busy_pr())

        report_line = next(line for line in out.splitlines() if line.startswith("reports:"))
        assert (
            "manual_test 2026-11-05T13:40:00Z by all-hands-bot at c3c3c3c (on head) FAIL"
            in report_line
        )
        assert "docs_review none" in report_line

    def test_timeline_events_in_order_with_actor_class_and_history_char(self, show):
        _, out, _ = show(busy_pr())

        timeline = out.split("timeline: 9 events, oldest first\n")[1].splitlines()
        events = [line for line in timeline if not line.startswith(" ")]
        assert events == [
            "2026-11-05T10:00:00Z o alice(me) opened: Adds the thing.",
            '2026-11-05T10:05:00Z - alice(me) pushed 1 commit, last c1c1c1c "initial"',
            "2026-11-05T10:10:00Z h alice(me) requested review from bob",
            "2026-11-05T11:00:00Z R bob(human) requested changes on c1c1c1c: "
            "Please rename foo to bar",
            '2026-11-05T12:01:00Z f alice(me) pushed 2 commits, last c3c3c3c "address review"',
            "2026-11-05T13:00:00Z A bob(human) approved on head: LGTM once the nit is fixed",
            "2026-11-05T13:30:00Z C carol(human) commented: Looks good to me",
            "2026-11-05T13:40:00Z N all-hands-bot(agent) commented: "
            "## Manual Test Results ❌ FAIL: the CLI crashes See logs.",
            "2026-11-05T13:50:00Z C ghost(human) commented: from a deleted user",
        ]

    def test_review_threads_sit_under_their_review(self, show):
        _, out, _ = show(busy_pr())

        lines = out.splitlines()
        first = lines.index(
            "2026-11-05T11:00:00Z R bob(human) requested changes on c1c1c1c: "
            "Please rename foo to bar"
        )
        assert lines[first + 1 : first + 4] == [
            "  ↳ src/a.py:12 [unresolved]",
            "    2026-11-05T11:00:00Z bob(human): rename this",
            "    2026-11-05T11:30:00Z alice(me): done",
        ]
        approved = next(i for i, line in enumerate(lines) if " A bob(human) approved" in line)
        assert lines[approved + 1 : approved + 3] == [
            "  ↳ src/b.py:3 [resolved]",
            "    2026-11-05T13:00:00Z bob(human): nit",
        ]

    def test_a_commit_before_any_review_is_marked_as_not_in_history(self, show):
        _, out, _ = show(busy_pr())

        assert "2026-11-05T10:05:00Z - alice(me) pushed 1 commit" in out

    def test_ai_disclosure_in_the_reference_users_own_comment_is_me_agent(self, show):
        node = busy_pr()
        node["timelineItems"]["nodes"].append(
            comment("alice", ts(14), "done\n\ncreated by an AI agent (OpenHands)")
        )

        _, out, _ = show(node)

        assert "2026-11-05T14:00:00Z n alice(me_agent) commented: done created by an AI" in out

    def test_review_requests_removals_and_dismissals(self, show):
        node = pr_node(
            [
                request("bob", ts(10, 10), "alice"),
                request("bob", ts(10, 20), "alice", removed=True),
                review("R1", "carol", "DISMISSED", ts(11), C1, "old concern"),
                {
                    "__typename": "ReviewDismissedEvent",
                    "createdAt": ts(12),
                    "actor": {"login": "alice"},
                    "dismissalMessage": "addressed",
                    "review": {"author": {"login": "carol"}},
                },
            ]
        )

        _, out, _ = show(node)

        assert "h alice(me) requested review from bob" in out
        assert "- alice(me) removed review request for bob" in out
        assert "- carol(human) review, since dismissed on c1c1c1c: old concern" in out
        assert "- alice(me) dismissed review by carol: addressed" in out

    def test_force_push_and_reopen_are_listed(self, show):
        node = pr_node(
            [
                {
                    "__typename": "HeadRefForcePushedEvent",
                    "createdAt": ts(11),
                    "actor": {"login": "alice"},
                    "afterCommit": {"oid": HEAD},
                },
                {"__typename": "ReopenedEvent", "createdAt": ts(12), "actor": {"login": "alice"}},
            ]
        )

        _, out, _ = show(node)

        assert "- alice(me) force-pushed to c3c3c3c" in out
        assert "- alice(me) reopened" in out

    def test_a_review_on_an_older_head_says_so(self, show):
        node = pr_node([review("R1", "bob", "APPROVED", ts(11), C1)])

        _, out, _ = show(node)

        assert "A bob(human) approved on c1c1c1c" in out
        assert "approved on head" not in out

    def test_merged_pr_lists_merge_but_not_the_close_that_came_with_it(self, show):
        node = pr_node(
            [
                {"__typename": "MergedEvent", "createdAt": ts(15), "actor": {"login": "alice"}},
                {"__typename": "ClosedEvent", "createdAt": ts(15), "actor": {"login": "alice"}},
            ],
            state="MERGED",
        )

        _, out, _ = show(node)

        assert "m alice(me) merged" in out
        assert "closed" not in out.split("timeline:")[1]

    def test_thread_whose_review_is_not_in_the_timeline_is_still_shown(self, show):
        node = pr_node(
            [comment("carol", ts(12), "hi")],
            [thread("T9", "x.py", 1, False, [thread_comment("bob", ts(11), "hmm", "GONE")])],
        )

        _, out, _ = show(node)

        lines = out.splitlines()
        i = next(n for n, line in enumerate(lines) if "review thread (its review" in line)
        assert lines[i + 1] == "  ↳ x.py:1 [unresolved]"
        assert lines[i + 2] == "    2026-11-05T11:00:00Z bob(human): hmm"
        assert i < next(n for n, line in enumerate(lines) if "carol(human)" in line)


class TestJson:
    def test_carries_header_reviewers_reports_and_events(self, show):
        code, out, _ = show(busy_pr(), "--format", "json")

        data = json.loads(out)
        assert code == 0
        assert data["ref"] == "o/r#7"
        assert data["kind"] == "pr"
        assert data["title"] == "Add the thing"
        assert data["history"] == "ohRfACNC"
        assert data["head"] == HEAD
        assert data["mergeable"] == "MERGEABLE"
        assert data["merge_state"] == "CLEAN"
        assert data["ci"] == "green"
        assert data["unresolved_threads"] == 1
        assert data["linked_issues"] == ["o/r#40"]
        assert data["since"] is None
        assert data["timeline_truncated"] is False
        [bob] = data["reviewers"]
        assert (bob["login"], bob["latest_state"], bob["on_head"]) == ("bob", "APPROVED", True)
        manual = next(r for r in data["reports"] if r["name"] == "manual_test")
        assert (manual["found"], manual["on_head"], manual["failed"]) == (True, True, True)
        assert len(data["events"]) == 9

    def test_events_carry_the_same_fields_as_the_text(self, show):
        _, out, _ = show(busy_pr(), "--format", "json")

        events = json.loads(out)["events"]
        changes = events[3]
        assert changes["kind"] == "review"
        assert (changes["char"], changes["actor"], changes["actor_class"]) == ("R", "bob", "human")
        assert changes["state"] == "CHANGES_REQUESTED"
        assert changes["commit"] == C1
        assert changes["on_head"] is False
        assert changes["body"] == "Please rename foo to bar"
        assert changes["threads"][0]["path"] == "src/a.py"
        assert changes["threads"][0]["resolved"] is False
        assert [c["actor"] for c in changes["threads"][0]["comments"]] == ["bob", "alice"]
        push = events[4]
        assert (push["kind"], push["commits"], push["head"]) == ("push", 2, HEAD)
        assert events[7]["actor_class"] == "agent"
        assert events[8]["actor"] == "ghost"


class TestSince:
    def test_only_newer_events(self, show):
        _, out, _ = show(busy_pr(), "--since", "2026-11-05T13:00:00Z")

        events = [line for line in out.splitlines() if line.startswith("2026-")]
        assert [line.split()[1] for line in events] == ["C", "N", "C"]
        assert "timeline since 2026-11-05T13:00:00Z: 3 events, oldest first" in out
        assert "reviewers: bob(human)" in out  # the header is always there

    def test_since_is_exclusive(self, show):
        _, out, _ = show(busy_pr(), "--since", "2026-11-05T13:50:00Z")

        assert "no new events since 2026-11-05T13:50:00Z" in out

    def test_no_new_events_still_prints_header(self, show):
        code, out, _ = show(busy_pr(), "--since", "2026-12-01T00:00:00Z")

        lines = out.splitlines()
        assert code == 0
        assert lines[0].startswith("o/r#7 pr open")
        assert lines[-1] == "no new events since 2026-12-01T00:00:00Z"
        assert not any(line.startswith("2026-") for line in lines)

    def test_no_new_events_in_json_is_an_empty_list(self, show):
        _, out, _ = show(busy_pr(), "--since", "2026-12-01", "--format", "json")

        data = json.loads(out)
        assert data["events"] == []
        assert data["since"] == "2026-12-01T00:00:00Z"
        assert data["head"] == HEAD

    def test_a_new_thread_reply_keeps_its_old_review_as_context(self, show):
        _, out, _ = show(busy_pr(), "--since", "2026-11-05T11:15:00Z")

        lines = out.splitlines()
        i = next(n for n, line in enumerate(lines) if "requested changes on c1c1c1c" in line)
        assert lines[i + 1 : i + 3] == [
            "  ↳ src/a.py:12 [unresolved]",
            "    2026-11-05T11:30:00Z alice(me): done",
        ]

    def test_since_snapshot_uses_the_stored_last_activity(self, show):
        item = make_item(key="o/r#7", last_activity="2026-11-05T13:35:00Z")
        snapshot_store.save(make_snapshot(kind="pr", name="tick", items=[item]))

        _, out, _ = show(busy_pr(), "--since-snapshot", "pr/tick")

        events = [line for line in out.splitlines() if line.startswith("2026-")]
        assert [line.split()[1] for line in events] == ["N", "C"]
        assert "timeline since 2026-11-05T13:35:00Z" in out

    def test_since_snapshot_accepts_a_review_snapshot(self, show):
        item = make_item(key="o/r#7", last_activity="2026-11-05T13:35:00Z")
        snapshot_store.save(make_snapshot(kind="review", name="queue", items=[item]))

        code, out, _ = show(busy_pr(), "--since-snapshot", "review/queue")

        assert code == 0
        assert "timeline since 2026-11-05T13:35:00Z: 2 events" in out

    def test_since_snapshot_without_a_row_for_the_item_is_an_error(self, show):
        snapshot_store.save(make_snapshot(kind="pr", name="tick", items=[make_item(key="o/r#99")]))

        code, out, err = show(busy_pr(), "--since-snapshot", "pr/tick")

        assert code == 1
        assert out == ""
        assert "snapshot pr/tick has no row for o/r#7" in err

    def test_since_snapshot_of_another_kind_is_an_error(self, show):
        snapshot_store.save(make_snapshot(kind="issue", name="tick", items=[]))

        code, _, err = show(busy_pr(), "--since-snapshot", "issue/tick")

        assert code == 1
        assert "`pr show` reads a pr or review snapshot, not issue" in err

    def test_missing_snapshot_is_an_error(self, show):
        code, _, err = show(busy_pr(), "--since-snapshot", "pr/nope")

        assert code == 1
        assert "snapshot not found: pr/nope" in err

    def test_snapshot_ref_needs_a_kind(self, show):
        code, _, err = show(busy_pr(), "--since-snapshot", "tick")

        assert code == 1
        assert "KIND/NAME" in err

    def test_bad_time_is_an_error(self, show):
        code, _, err = show(busy_pr(), "--since", "yesterday")

        assert code == 1
        assert "invalid time 'yesterday'" in err

    def test_since_and_since_snapshot_cannot_be_combined(self, show):
        with pytest.raises(SystemExit):
            show(busy_pr(), "--since", "2026-11-05", "--since-snapshot", "pr/tick")


class TestMaxBody:
    @pytest.fixture
    def long_pr(self):
        return pr_node(
            [comment("carol", ts(11), "x" * 50)],
            [thread("T1", "a.py", 1, False, [thread_comment("bob", ts(11), "y" * 30, None)])],
            body="z" * 40,
        )

    def test_trims_with_a_count_of_what_was_cut(self, show, long_pr):
        _, out, _ = show(long_pr, "--max-body", "20")

        assert f"opened: {'z' * 20}…(20 more chars)" in out
        assert f"commented: {'x' * 20}…(30 more chars)" in out
        assert f"bob(human): {'y' * 20}…(10 more chars)" in out

    def test_zero_means_no_trimming(self, show, long_pr):
        _, out, _ = show(long_pr, "--max-body", "0")

        assert "x" * 50 in out
        assert "more chars" not in out

    def test_default_keeps_600_characters(self, show):
        node = pr_node([comment("carol", ts(11), "x" * 700)])

        _, out, _ = show(node)

        assert f"commented: {'x' * 600}…(100 more chars)" in out

    def test_json_reports_the_cut(self, show, long_pr):
        _, out, _ = show(long_pr, "--max-body", "20", "--format", "json")

        events = json.loads(out)["events"]
        assert events[1]["body"] == f"{'x' * 20}…(30 more chars)"
        assert events[1]["more_chars"] == 30
        assert events[0]["more_chars"] == 20

    def test_negative_is_rejected(self, show, long_pr):
        with pytest.raises(SystemExit):
            show(long_pr, "--max-body", "-1")


class TestCompleteness:
    def test_a_timeline_of_more_than_100_events_is_complete(self, show):
        comments = [comment("carol", ts(11 + i // 60, i % 60), f"comment {i}") for i in range(250)]

        _, out, _ = show(pr_node(comments), "--format", "json")

        data = json.loads(out)
        assert [e["body"] for e in data["events"][1:]] == [f"comment {i}" for i in range(250)]
        assert data["timeline_truncated"] is False

    def test_a_thread_with_more_than_50_comments_is_complete(self, show):
        replies = [thread_comment("bob", ts(11, i % 60), f"reply {i}", "R1") for i in range(120)]
        node = pr_node(
            [review("R1", "bob", "COMMENTED", ts(11), C1)],
            [thread("T1", "a.py", 1, False, replies)],
        )

        _, out, _ = show(node, "--format", "json")

        review_event = json.loads(out)["events"][1]
        comments = review_event["threads"][0]["comments"]
        assert [c["body"] for c in comments] == [f"reply {i}" for i in range(120)]

    def test_more_than_50_threads_are_all_listed(self, show):
        threads = [
            thread(f"T{i}", f"f{i}.py", i, False, [thread_comment("bob", ts(11), "c", "R1")])
            for i in range(130)
        ]
        node = pr_node([review("R1", "bob", "COMMENTED", ts(11), C1)], threads)

        _, out, _ = show(node, "--format", "json")

        data = json.loads(out)
        assert len(data["events"][1]["threads"]) == 130
        assert data["unresolved_threads"] == 130

    def test_timeline_past_the_cap_is_flagged(self, show, monkeypatch):
        monkeypatch.setattr("src.show.pr.PR_SHOW_TIMELINE", replace(PR_SHOW_TIMELINE, cap=150))
        comments = [comment("carol", ts(11 + i // 60, i % 60), str(i)) for i in range(250)]

        _, out, _ = show(pr_node(comments))

        assert "(timeline truncated: events past the fetch cap are missing)" in out


class TestRobustness:
    def test_deleted_authors_and_actors_do_not_abort(self, show):
        node = pr_node(
            [
                comment(None, ts(11), "gone"),
                review("R1", "bob", "COMMENTED", ts(12), None, "hm"),
                {"__typename": "MergedEvent", "createdAt": ts(13), "actor": None},
                commit(C1, None, ts(14)),
            ],
            [thread("T1", "a.py", 1, False, [thread_comment(None, ts(12), "orphan", "R1")])],
            author=None,
        )

        code, out, _ = show(node)

        assert code == 0
        assert "ghost(human) commented: gone" in out
        assert "ghost(human): orphan" in out
        assert "ghost(human) merged" in out

    def test_unknown_pr_is_an_error(self, show):
        code, out, err = show(None)

        assert code == 1
        assert out == ""
        assert "PR not found: o/r#7" in err

    def test_bad_reference_is_an_error(self, show):
        code, _, err = show(busy_pr(), ref="not-a-ref")

        assert code == 1
        assert "Invalid PR reference" in err

    def test_accepts_a_pr_url(self, show):
        code, out, _ = show(busy_pr(), ref="https://github.com/o/r/pull/7")

        assert code == 0
        assert out.startswith("o/r#7 pr open")

    def test_repo_without_norms_shows_no_reports(self, show):
        norms_store.set_loader(lambda _repo: None)

        _, out, _ = show(busy_pr())

        assert "reports:" not in out
        assert "N all-hands-bot" not in out
        assert "C all-hands-bot(human)" in out

    def test_report_with_no_commit_seen_has_unknown_head(self, show):
        node = pr_node([comment("carol", ts(11), "## Docs review\nfine")])

        _, out, _ = show(node, "--format", "json")

        docs = next(r for r in json.loads(out)["reports"] if r["name"] == "docs_review")
        assert (docs["found"], docs["head"], docs["on_head"], docs["failed"]) == (
            True,
            None,
            None,
            False,
        )

    def test_report_on_an_older_head_says_so(self, show):
        node = pr_node(
            [
                commit(C1, "alice", ts(10)),
                comment("carol", ts(11), "## Docs review\nfine"),
                commit(HEAD, "alice", ts(12)),
            ]
        )

        _, out, _ = show(node)

        assert (
            "docs_review 2026-11-05T11:00:00Z by carol at c1c1c1c (not on head) no fail match"
            in out
        )

    def test_the_latest_matching_comment_is_the_report(self, show):
        node = pr_node(
            [
                comment("carol", ts(11), "## Docs review\nfine"),
                comment("dave", ts(12), "## Docs review\nstill fine"),
            ]
        )

        _, out, _ = show(node, "--format", "json")

        docs = next(r for r in json.loads(out)["reports"] if r["name"] == "docs_review")
        assert docs["actor"] == "dave"
