"""The one compact JSON document of `issue list`, `pr list` and `review` (#142)."""

# ruff: noqa: ARG001, F401, F811

from __future__ import annotations

import json
import logging

import pytest

from src.issue.cli import list_cmd as issue_list
from src.pr.cli import list_cmd as pr_list
from src.review.cli import list_cmd as review_list
from src.snapshot import store
from tests.snapshot.test_list_cmd_watch import COMMANDS, FakeClient, fake_client

TOP_KEYS = ["schema", "filters", "total_count", "has_more", "items"]


def _doc(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


@pytest.mark.parametrize("command", list(COMMANDS))
def test_total_count_is_an_integer_when_known(command, tkt_home, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [3, 2]
    fake_client.total_count = 2
    assert cmd_list(output_format="json") == 0
    doc = _doc(capsys)
    assert list(doc) == TOP_KEYS
    assert doc["total_count"] == len(doc["items"]) == 2
    assert doc["has_more"] is False


@pytest.mark.parametrize("command", list(COMMANDS))
def test_total_count_is_null_when_github_cannot_say(command, tkt_home, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [3]
    fake_client.total_count = None
    fake_client.has_more = True
    assert cmd_list(output_format="json") == 0
    doc = _doc(capsys)
    assert doc["total_count"] is None
    assert doc["has_more"] is True


@pytest.mark.parametrize("command", list(COMMANDS))
def test_total_count_can_exceed_the_rows_when_there_are_more(
    command, tkt_home, fake_client, capsys
):
    _, cmd_list = COMMANDS[command]
    fake_client.numbers = [3, 2]
    fake_client.total_count = 31
    fake_client.has_more = True
    assert cmd_list(output_format="json") == 0
    doc = _doc(capsys)
    assert (len(doc["items"]), doc["total_count"], doc["has_more"]) == (2, 31, True)


@pytest.mark.parametrize("command", list(COMMANDS))
def test_an_empty_result_is_a_valid_document(command, tkt_home, fake_client, capsys):
    _, cmd_list = COMMANDS[command]
    fake_client.total_count = 0
    assert cmd_list(output_format="json") == 0
    assert _doc(capsys) == {
        "schema": 2,
        "filters": {**_doc_filters(command)},
        "total_count": 0,
        "has_more": False,
        "items": [],
    }


def _doc_filters(command: str) -> dict:
    return {
        "pr": {"author": "octocat", "limit": 100},
        "issue": {"author": "octocat", "states": ["open"], "limit": 100},
        "review": {"reviewer": "octocat", "limit": 100},
    }[command]


def test_pr_list_filters_hold_the_resolved_author(tkt_home, fake_client, capsys):
    assert pr_list.cmd_list(output_format="json") == 0
    filters = _doc(capsys)["filters"]
    assert filters["author"] == "octocat"
    assert "reviewer" not in filters


def test_pr_list_with_all_authors_has_no_author(tkt_home, fake_client, capsys, monkeypatch):
    monkeypatch.setattr(pr_list, "_get_repos", lambda *_: ["o/r"])
    assert pr_list.cmd_list(all_authors=True, output_format="json") == 0
    filters = _doc(capsys)["filters"]
    assert "author" not in filters
    assert filters["all_authors"] is True


def test_pr_list_by_reviewer_holds_the_resolved_reviewer_and_no_author(
    tkt_home, fake_client, capsys
):
    assert pr_list.cmd_list(reviewer="me", output_format="json") == 0
    filters = _doc(capsys)["filters"]
    assert filters["reviewer"] == "octocat"
    assert "author" not in filters


def test_pr_list_with_an_explicit_reviewer_keeps_that_login(tkt_home, fake_client, capsys):
    assert pr_list.cmd_list(reviewer="enyst", output_format="json") == 0
    assert _doc(capsys)["filters"]["reviewer"] == "enyst"


def test_issue_list_filters_hold_the_resolved_author(tkt_home, fake_client, capsys):
    assert issue_list.cmd_list(output_format="json") == 0
    assert _doc(capsys)["filters"]["author"] == "octocat"
    assert issue_list.cmd_list(author="me", output_format="json") == 0
    assert _doc(capsys)["filters"]["author"] == "octocat"
    assert issue_list.cmd_list(author="enyst", output_format="json") == 0
    assert _doc(capsys)["filters"]["author"] == "enyst"


def test_issue_list_with_all_authors_has_no_author(tkt_home, fake_client, capsys, monkeypatch):
    monkeypatch.setattr(issue_list, "_get_repos", lambda *_: ["o/r"])
    assert issue_list.cmd_list(all_authors=True, output_format="json") == 0
    filters = _doc(capsys)["filters"]
    assert "author" not in filters
    assert filters["repos"] == ["o/r"]


@pytest.mark.parametrize("cmd", [issue_list.cmd_list, pr_list.cmd_list])
def test_explicit_refs_have_refs_and_no_author(cmd, tkt_home, fake_client, capsys):
    ref_arg = "issue_refs" if cmd is issue_list.cmd_list else "pr_refs"
    assert cmd(**{ref_arg: ["o/r#5", "o/r#2"]}, author="me", output_format="json") == 0
    doc = _doc(capsys)
    assert doc["filters"]["refs"] == ["o/r#2", "o/r#5"]
    assert "author" not in doc["filters"]
    assert doc["total_count"] == len(doc["items"]) == 2


def test_review_filters_hold_the_resolved_reviewer(tkt_home, fake_client, capsys):
    assert review_list.cmd_list(output_format="json") == 0
    assert _doc(capsys)["filters"]["reviewer"] == "octocat"
    assert review_list.cmd_list(reviewer="enyst", output_format="json") == 0
    assert _doc(capsys)["filters"]["reviewer"] == "enyst"


def test_review_author_filter_passes_unchanged(tkt_home, fake_client, capsys):
    assert review_list.cmd_list(author="alice", output_format="json") == 0
    filters = _doc(capsys)["filters"]
    assert filters["author"] == "alice"
    assert filters["reviewer"] == "octocat"


def test_filters_carry_only_the_applied_flags(tkt_home, fake_client, capsys):
    code = issue_list.cmd_list(
        pr_filter="no-pr",
        blocked_filter="unblocked",
        labels=["bug"],
        not_labels=["Wontfix"],
        sort=["-number"],
        output_format="json",
    )
    assert code == 0
    assert _doc(capsys)["filters"] == {
        "author": "octocat",
        "states": ["open"],
        "labels": ["bug"],
        "not_labels": ["wontfix"],
        "pr_filter": "no-pr",
        "blocked_filter": "unblocked",
        "sort": ["-number"],
        "limit": 100,
    }


@pytest.mark.parametrize("command", list(COMMANDS))
def test_stdout_holds_only_the_document_with_a_warning_and_more_rows(
    command, tkt_home, fake_client, capsys, caplog
):
    class Noisy(FakeClient):
        def __enter__(self):
            logging.getLogger("src.board.github_api").warning("Search page timed out; retrying")
            return self

    _, cmd_list = COMMANDS[command]
    for module, attr in (
        (pr_list, "PRClient"),
        (issue_list, "IssueClient"),
        (review_list, "ReviewClient"),
    ):
        setattr(module, attr, Noisy)
    Noisy.numbers = [4, 3]
    Noisy.has_more = True
    Noisy.total_count = None
    assert cmd_list(output_format="json") == 0
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert captured.out.startswith('{\n  "schema": 2,')
    assert captured.out.rstrip("\n").endswith("}")
    assert doc["has_more"] is True
    assert "Filters:" not in captured.out
    assert "Showing" not in captured.out
    assert "timed out" in caplog.text


@pytest.mark.parametrize("command", list(COMMANDS))
def test_a_snapshot_run_prints_the_file_byte_for_byte(command, tkt_home, fake_client, capsys):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    fake_client.total_count = 1
    assert cmd_list(snapshot_name="a", output_format="json") == 0
    printed = capsys.readouterr().out
    [path] = tkt_home.glob("snapshots/*.json")
    assert path.read_text() + "\n" == printed
    loaded = store.load(kind, "a")
    assert loaded.total_count == 1
    assert loaded.to_json() + "\n" == printed


@pytest.mark.parametrize("command", list(COMMANDS))
def test_an_old_layout_file_is_deleted_and_treated_as_missing(
    command, tkt_home, fake_client, capsys, caplog
):
    kind, cmd_list = COMMANDS[command]
    fake_client.numbers = [1]
    assert cmd_list(snapshot_name="old", output_format="json") == 0
    capsys.readouterr()
    [path] = tkt_home.glob("snapshots/*.json")
    doc = json.loads(path.read_text())
    old = {
        "schema": 2,
        "kind": kind,
        "name": "old",
        "captured_at": doc["snapshot"]["captured_at"],
        "scope": doc["filters"],
        "scope_hash": "deadbeef",
        "has_more": False,
        "items": doc["items"],
    }
    path.write_text(json.dumps(old))
    with pytest.raises(FileNotFoundError):
        store.load(kind, "old")
    assert not path.exists()
    assert "discarded" in caplog.text
