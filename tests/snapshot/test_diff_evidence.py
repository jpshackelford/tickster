"""`pr list --diff --format json`: events_since and steps on each added or changed row.

The list client is a stub. The timeline endpoint is `FakeGitHub` behind a real httpx
client, and the snapshot store, diff and render code run for real.
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console

from src.__main__ import main
from src.pr.cli import list_cmd as pr_list
from src.pr.cli import steps_cmd
from src.pr.models import CIStatus, PRInfo, PRListResult, PRState
from src.show.pr import PR_SHOW_TIMELINE
from src.snapshot import store
from tests.show.builders import comment, pr_node, ts
from tests.show.fake_github import FakeGitHub

LONG_BODY = "x" * 300
BASELINE_ACTIVITY = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
BASELINE_ISO = "2026-11-05T12:00:00Z"
LATER_ACTIVITY = datetime(2026, 11, 5, 14, 0, tzinfo=UTC)


def _pr(number: int = 7, **overrides: Any) -> PRInfo:
    fields: dict[str, Any] = {
        "repo": "o/r",
        "number": number,
        "title": "t",
        "state": PRState.OPEN,
        "ci_status": CIStatus.GREEN,
        "history": "oA",
        "created_at": BASELINE_ACTIVITY,
        "closed_at": None,
        "last_activity": BASELINE_ACTIVITY,
        "author": "alice",
        "head_sha": "a" * 40,
        "mergeable": "MERGEABLE",
        "checks_state": "SUCCESS",
        "reviewers": (),
    }
    fields.update(overrides)
    return PRInfo(**fields)


def _moved(number: int = 7, **overrides: Any) -> PRInfo:
    return _pr(number, last_activity=LATER_ACTIVITY, history="oAC", **overrides)


class FakePRClient:
    prs: list[PRInfo] = []

    def __enter__(self) -> FakePRClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_current_user(self) -> str:
        return "octocat"

    def list_prs_by_author(self, *_: Any, **__: Any) -> PRListResult:
        return PRListResult(prs=list(self.prs))

    def get_prs_by_ref(self, refs: list[str]) -> PRListResult:
        wanted = {r.lower() for r in refs}
        return PRListResult(prs=[p for p in self.prs if f"{p.repo}#{p.number}" in wanted])


@pytest.fixture
def prs(monkeypatch, tkt_home) -> type[FakePRClient]:  # noqa: ARG001
    monkeypatch.setattr(FakePRClient, "prs", [])
    monkeypatch.setattr(pr_list, "PRClient", FakePRClient)
    monkeypatch.setattr(steps_cmd, "PRClient", FakePRClient)
    monkeypatch.setattr(pr_list, "_get_repos", lambda *_: None)
    monkeypatch.setattr(pr_list, "console", Console(width=200, color_system=None))
    tty = io.StringIO()
    tty.isatty = lambda: True  # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stdin", tty)
    return FakePRClient


@pytest.fixture
def timeline(diff_timelines: FakeGitHub) -> FakeGitHub:
    diff_timelines.item = pr_node(
        [
            comment("bob", ts(11), "before the baseline"),
            comment("carol", ts(13), "after the baseline"),
            comment("carol", ts(14), LONG_BODY),
        ]
    )
    return diff_timelines


def _watch(capsys, *flags: str) -> dict:
    assert main(["pr", "list", "--watch", "w", "--format", "json", *flags]) == 0
    return json.loads(capsys.readouterr().out)


def _baseline(prs, capsys, timeline, *numbers: int) -> None:
    """Save the baseline; its first run fetches every row as added, so clear the request log."""
    prs.prs = [_pr(n) for n in numbers]
    _watch(capsys)
    timeline.requests.clear()


def _delta(doc: dict, kind: str) -> dict:
    [delta] = [d for d in doc["deltas"] if d["kind"] == kind]
    return delta


def _bodies(delta: dict) -> list[str | None]:
    return [e["body"] for e in delta["events_since"]]


class TestChangedRow:
    def test_events_since_holds_exactly_the_events_after_the_previous_last_activity(
        self, prs, timeline, capsys
    ):
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved()]

        delta = _delta(_watch(capsys), "changed")

        assert [e["actor"] for e in delta["events_since"]] == ["carol", "carol"]
        assert _bodies(delta)[0] == "after the baseline"
        assert all(e["at"] > BASELINE_ISO for e in delta["events_since"])
        assert "events_truncated" not in delta
        assert len(timeline.requests) == 1

    def test_events_equal_pr_show_since_the_same_time(self, prs, timeline, capsys):
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved()]
        delta = _delta(_watch(capsys, "--events", "full"), "changed")

        with patch("src.show.cli.GitHubClient", return_value=timeline.client()):
            code = main(
                ["pr", "show", "o/r#7", "--since-time", BASELINE_ISO, "--max-body", "0"]
                + ["--format", "json"]
            )
        assert code == 0

        assert delta["events_since"] == json.loads(capsys.readouterr().out)["events"]

    def test_steps_with_evidence_equal_pr_steps_json(self, prs, timeline, capsys):  # noqa: ARG002
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved(checks_state="FAILURE")]

        delta = _delta(_watch(capsys), "changed")

        assert steps_cmd.cmd_steps(refs=["o/r#7"], output_format="json") == 0
        [expected] = json.loads(capsys.readouterr().out)
        assert delta["steps"] == expected["steps"]
        assert any(step["evidence"] for step in delta["steps"])

    def test_evidence_is_not_stored_in_the_snapshot(self, prs, timeline, capsys):  # noqa: ARG002
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved(checks_state="FAILURE")]
        _watch(capsys)

        [item] = store.load("pr", "w").items
        assert "evidence" not in json.dumps(item.to_dict())
        assert "events_since" not in json.dumps(item.to_dict())

    def test_existing_diff_fields_are_unchanged(self, prs, timeline, capsys):  # noqa: ARG002
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved()]

        delta = _delta(_watch(capsys), "changed")

        assert delta["new_history_tail"] == "C"
        assert delta["changed_fields"] == ["history", "activity"]
        assert delta["prev"]["last_activity"] == BASELINE_ISO
        assert delta["curr"]["history"] == "oAC"


class TestAddedRow:
    def test_gets_the_whole_timeline(self, prs, timeline, capsys):  # noqa: ARG002
        _baseline(prs, capsys, timeline)
        prs.prs = [_pr(7)]

        delta = _delta(_watch(capsys), "added")

        assert [e["kind"] for e in delta["events_since"]] == [
            "opened",
            "comment",
            "comment",
            "comment",
        ]
        assert _bodies(delta)[1] == "before the baseline"
        assert delta["steps"]

    def test_first_run_without_a_baseline_treats_every_row_as_added(self, prs, timeline, capsys):
        prs.prs = [_pr(7)]

        delta = _delta(_watch(capsys), "added")

        assert len(delta["events_since"]) == 4
        assert len(timeline.requests) == 1


class TestEventsOption:
    @pytest.fixture
    def changed(self, prs, timeline, capsys):  # noqa: ARG002
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved()]

    def test_none_makes_no_timeline_request_and_omits_events(self, changed, timeline, capsys):  # noqa: ARG002
        delta = _delta(_watch(capsys, "--events", "none"), "changed")

        assert timeline.requests == []
        assert "events_since" not in delta
        assert "events_truncated" not in delta
        assert delta["steps"]

    def test_default_cuts_bodies_at_160(self, changed, capsys):  # noqa: ARG002
        delta = _delta(_watch(capsys), "changed")

        assert _bodies(delta)[1] == "x" * 160 + "…(140 more chars)"
        assert delta["events_since"][1]["more_chars"] == 140

    def test_brief_is_the_default(self, changed, capsys):  # noqa: ARG002
        assert (
            _delta(_watch(capsys, "--events", "brief"), "changed")["events_since"][1]["body"]
            == "x" * 160 + "…(140 more chars)"
        )

    def test_full_keeps_whole_bodies(self, changed, capsys):  # noqa: ARG002
        delta = _delta(_watch(capsys, "--events", "full"), "changed")

        assert _bodies(delta)[1] == LONG_BODY
        assert delta["events_since"][1]["more_chars"] == 0

    def test_max_body_overrides_the_cut(self, changed, capsys):  # noqa: ARG002
        delta = _delta(_watch(capsys, "--max-body", "40"), "changed")

        assert _bodies(delta)[1] == "x" * 40 + "…(260 more chars)"

    def test_brief_with_max_body(self, changed, capsys):  # noqa: ARG002
        delta = _delta(_watch(capsys, "--events", "brief", "--max-body", "40"), "changed")

        assert _bodies(delta)[1] == "x" * 40 + "…(260 more chars)"


class TestTruncation:
    def test_the_timeline_cap_sets_events_truncated(self, prs, timeline, capsys, monkeypatch):
        monkeypatch.setattr("src.show.pr.PR_SHOW_TIMELINE", replace(PR_SHOW_TIMELINE, cap=150))
        timeline.item = pr_node(
            [comment("carol", ts(13 + i // 60, i % 60), "c") for i in range(250)]
        )
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved()]

        delta = _delta(_watch(capsys), "changed")

        assert delta["events_truncated"] is True


class TestOtherRows:
    def test_unchanged_and_removed_rows_make_no_extra_calls(self, prs, timeline, capsys):
        _baseline(prs, capsys, timeline, 1, 2)
        prs.prs = [_pr(1)]

        doc = _watch(capsys)

        assert [d["kind"] for d in doc["deltas"]] == ["removed", "unchanged"]
        assert timeline.requests == []
        for delta in doc["deltas"]:
            assert not {"events_since", "events_truncated", "steps"} & delta.keys()

    def test_only_added_and_changed_rows_are_fetched(self, prs, timeline, capsys):
        _baseline(prs, capsys, timeline, 1, 2, 3)
        prs.prs = [_pr(1), _moved(2), _pr(4)]

        doc = _watch(capsys)

        assert {d["key"]: d["kind"] for d in doc["deltas"]} == {
            "o/r#4": "added",
            "o/r#2": "changed",
            "o/r#3": "removed",
            "o/r#1": "unchanged",
        }
        assert len(timeline.requests) == 2

    def test_stdout_is_one_json_document(self, prs, timeline, capsys):  # noqa: ARG002
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved()]

        assert main(["pr", "list", "--diff", "w", "--format", "json"]) == 0
        captured = capsys.readouterr()

        json.loads(captured.out)
        assert captured.err == ""

    def test_table_output_has_no_evidence_and_no_timeline_request(self, prs, timeline, capsys):
        _baseline(prs, capsys, timeline, 7)
        prs.prs = [_moved()]

        assert main(["pr", "list", "--watch", "w"]) == 0

        assert "events_since" not in capsys.readouterr().out
        assert timeline.requests == []


class TestUsageErrors:
    @pytest.mark.parametrize(
        "flags",
        [
            ["--watch", "w", "--format", "json", "--events", "full", "--max-body", "40"],
            ["--watch", "w", "--format", "json", "--events", "none", "--max-body", "40"],
            ["--events", "full", "--format", "json"],
            ["--max-body", "40", "--format", "json"],
            ["--watch", "w", "--events", "full"],
            ["--diff", "w", "--max-body", "40"],
            ["--snapshot", "w", "--format", "json", "--events", "brief"],
            ["--watch", "w", "--format", "json", "--max-body", "0"],
            ["--watch", "w", "--format", "json", "--events", "most"],
        ],
    )
    def test_exits_2(self, flags, prs, timeline, capsys):  # noqa: ARG002
        with pytest.raises(SystemExit) as exc:
            main(["pr", "list", *flags])

        assert exc.value.code == 2
        assert timeline.requests == []
        assert "usage:" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("flags", "message"),
        [
            (["--watch", "w", "--max-body", "5"], "--max-body needs --format json"),
            (["--format", "json", "--events", "none"], "--events needs --diff or --watch"),
            (
                ["--watch", "w", "--format", "json", "--events", "full", "--max-body", "5"],
                "--max-body only applies to --events brief, not --events full",
            ),
        ],
    )
    def test_says_what_is_wrong(self, flags, message, prs, capsys):  # noqa: ARG002
        with pytest.raises(SystemExit):
            main(["pr", "list", *flags])

        assert message in capsys.readouterr().err
