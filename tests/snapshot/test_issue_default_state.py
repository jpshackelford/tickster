"""`tkt issue list` defaults to open issues, and old state-less snapshots stay comparable."""

from __future__ import annotations

import json
import sys

import pytest

from src.__main__ import main
from src.issue.github_api import IssueClient
from src.issue.models import IssueListResult
from src.snapshot import store
from src.snapshot.models import Snapshot, SnapshotScope


@pytest.fixture
def queries(monkeypatch) -> list[str]:
    """Run the real CLI and query builder; capture the search query instead of calling GitHub."""
    sent: list[str] = []

    def fake_search(_self, search_query: str, *_args, **_kw) -> IssueListResult:
        sent.append(search_query)
        return IssueListResult(issues=[], total_count=0)

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(IssueClient, "_search_issues", fake_search)
    monkeypatch.setattr(IssueClient, "get_current_user", lambda _self: "me")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    return sent


@pytest.mark.parametrize(
    ("flags", "has_open", "has_closed"),
    [
        ([], True, False),
        (["--open"], True, False),
        (["--closed"], False, True),
        (["--all"], False, False),
        (["--open", "--closed"], False, False),
    ],
)
def test_issue_list_state_qualifier(flags, has_open, has_closed, queries, tkt_home):  # noqa: ARG001
    assert main(["issue", "list", "--repo", "o/r", *flags]) == 0
    (query,) = queries
    assert ("is:open" in query) is has_open
    assert ("is:closed" in query) is has_closed


def test_default_and_explicit_open_share_a_watch_scope(queries, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--repo", "o/r", "--watch", "w"]) == 0
    assert store.load("issue", "w").scope.states == ("open",)
    capsys.readouterr()

    assert main(["issue", "list", "--repo", "o/r", "--open", "--watch", "w"]) == 0
    assert "scope mismatch" not in capsys.readouterr().out


def test_all_flag_is_a_different_watch_scope_than_the_default(queries, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--repo", "o/r", "--watch", "w"]) == 0
    capsys.readouterr()

    assert main(["issue", "list", "--repo", "o/r", "--all", "--watch", "w"]) == 2
    assert "scope mismatch" in capsys.readouterr().out


def _saved_without_states(kind: str) -> dict:
    data = Snapshot.make(kind=kind, name="old", scope=SnapshotScope(board="oh"), items=[]).to_dict()
    data["scope"]["states"] = None
    return data


def test_stored_issue_scope_without_states_loads_as_open():
    snap = Snapshot.from_dict(_saved_without_states("issue"))
    assert snap.scope.states == ("open",)
    assert snap.scope_hash == SnapshotScope(board="oh", states=("open",)).fingerprint()


@pytest.mark.parametrize("kind", ["pr", "review"])
def test_stored_scope_without_states_is_untouched_for_other_kinds(kind):
    assert Snapshot.from_dict(_saved_without_states(kind)).scope.states is None


def test_old_stateless_issue_watch_matches_after_the_fix(queries, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--repo", "o/r", "--watch", "w"]) == 0
    path = store.path_for("issue", "w")
    capsys.readouterr()
    assert path.exists()

    data = json.loads(path.read_text())
    data["scope"]["states"] = None
    path.write_text(json.dumps(data))

    assert main(["issue", "list", "--repo", "o/r", "--watch", "w"]) == 0
    assert "scope mismatch" not in capsys.readouterr().out
