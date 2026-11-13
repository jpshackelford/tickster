"""`tkt issue list --sort`: key parsing, ordering, sort-before-limit, the 500 cap, snapshot scope."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from rich.console import Console

from src.__main__ import main
from src.issue.cli import list_cmd as issue_list
from src.issue.github_api import IssueClient
from src.issue.models import IssueInfo, IssueState
from src.issue.sort import (
    SORT_CAP,
    VALID_KEYS,
    MissingRankError,
    parse_sort,
    require_rank,
    sort_issues,
)
from src.norms.model import Labels, Norms
from src.norms.store import set_loader
from src.snapshot import store
from src.snapshot.diff import diff_snapshots
from src.snapshot.models import SnapshotScope
from src.snapshot.render import sort_note

from ..snapshot.conftest import make_item, make_snapshot
from ..snapshot.conftest import tkt_home as tkt_home

BASE = datetime(2026, 10, 1, tzinfo=UTC)


def _issue(number: int, *, day: int = 1, active: int = 1, blocking: int = 0, repo: str = "o/r"):
    return IssueInfo(
        repo=repo,
        number=number,
        title="t",
        state=IssueState.OPEN,
        history="o",
        linked_pr=None,
        labels=[],
        created_at=BASE + timedelta(days=day),
        closed_at=None,
        last_activity=BASE + timedelta(days=active),
        author="someone",
        blocking=blocking,
    )


def _numbers(issues: list[IssueInfo]) -> list[int]:
    return [i.number for i in issues]


# --- parsing -----------------------------------------------------------------


def test_parse_keeps_keys_in_order_with_their_prefix():
    assert parse_sort("blocking,-created, number") == ("blocking", "-created", "number")


@pytest.mark.parametrize("text", ["priority", "created,bogus", "--created", "", "created,"])
def test_parse_rejects_unknown_keys_and_names_the_valid_ones(text):
    with pytest.raises(ValueError) as exc:
        parse_sort(text)
    assert all(key in str(exc.value) for key in VALID_KEYS)


# --- ordering ----------------------------------------------------------------

FIXTURE = [
    _issue(1, day=3, active=2, blocking=0),
    _issue(2, day=1, active=3, blocking=2),
    _issue(3, day=2, active=1, blocking=1),
    _issue(4, day=1, active=1, blocking=2),
]


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (["number"], [1, 2, 3, 4]),
        (["-number"], [4, 3, 2, 1]),
        (["created"], [2, 4, 3, 1]),
        (["-created"], [1, 3, 2, 4]),
        (["updated"], [3, 4, 1, 2]),
        (["-updated"], [2, 1, 3, 4]),
        (["blocking"], [2, 4, 3, 1]),
        (["-blocking"], [1, 3, 2, 4]),
    ],
)
def test_each_key_ascending_and_reversed_with_ties_broken_by_number(keys, expected):
    assert _numbers(sort_issues(FIXTURE, keys)) == expected


def test_later_keys_break_ties_of_earlier_ones():
    assert _numbers(sort_issues(FIXTURE, ["blocking", "updated"])) == [4, 2, 3, 1]
    assert _numbers(sort_issues(FIXTURE, ["blocking", "-updated"])) == [2, 4, 3, 1]
    assert _numbers(sort_issues(FIXTURE, ["created", "-blocking"])) == [2, 4, 3, 1]


def test_an_earlier_key_wins_over_a_later_one():
    assert _numbers(sort_issues(FIXTURE, ["-number", "created"])) == [4, 3, 2, 1]


def test_equal_numbers_across_repos_are_ordered_by_repo():
    issues = [_issue(1, repo="b/x"), _issue(1, repo="a/x")]
    assert [i.repo for i in sort_issues(issues, ["number"])] == ["a/x", "b/x"]


def test_sorting_does_not_change_its_input():
    before = _numbers(FIXTURE)
    sort_issues(FIXTURE, ["-number"])
    assert _numbers(FIXTURE) == before


# --- client: sort happens before limit ---------------------------------------


def _node(number: int, *, blocking: int = 0) -> dict:
    return {
        "__typename": "Issue",
        "number": number,
        "title": "t",
        "state": "OPEN",
        "createdAt": f"2024-01-{(number % 28) + 1:02d}T00:00:00Z",
        "closedAt": None,
        "author": {"login": "someone"},
        "repository": {"nameWithOwner": "o/r"},
        "labels": {"nodes": []},
        "blockedBy": {"totalCount": 0, "nodes": []},
        "blocking": {
            "totalCount": blocking,
            "nodes": [
                {"number": 900 + k, "state": "OPEN", "repository": {"nameWithOwner": "o/r"}}
                for k in range(blocking)
            ],
        },
        "parent": None,
        "milestone": None,
        "timelineItems": {"nodes": []},
    }


def _page(nodes: list[dict], *, has_next: bool = False) -> httpx.Response:
    body = {
        "data": {
            "search": {
                "issueCount": len(nodes),
                "pageInfo": {"hasNextPage": has_next, "endCursor": "c" if has_next else None},
                "nodes": nodes,
            }
        }
    }
    return httpx.Response(200, json=body, request=httpx.Request("POST", "https://x"))


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_USERNAME", "octocat")


def _list(pages, **kwargs):
    with patch.object(httpx.Client, "post", side_effect=pages) as post:
        client = IssueClient(token="test-token")
        result = client.list_issues_by_author(None, repos=["o/r"], **kwargs)
        client.close()
    return result, post


def test_sort_blocking_limit_1_finds_the_top_issue_beyond_the_first_page(github_env):  # noqa: ARG001
    first = _page([_node(1), _node(2, blocking=1), _node(3)], has_next=True)
    second = _page([_node(4), _node(5, blocking=3)])
    result, post = _list([first, second], sort=["blocking"], limit=1)
    assert _numbers(result.issues) == [5]
    assert post.call_count == 2
    assert result.has_more is True
    assert result.total_count == 5


def test_sort_with_a_limit_above_the_matches_has_no_more(github_env):  # noqa: ARG001
    result, _ = _list([_page([_node(2), _node(1)])], sort=["number"], limit=10)
    assert _numbers(result.issues) == [1, 2]
    assert result.has_more is False


def test_without_sort_limit_still_stops_the_scan_early(github_env):  # noqa: ARG001
    first = _page([_node(1), _node(2), _node(3)], has_next=True)
    result, post = _list([first], limit=2)
    assert len(result.issues) == 2
    assert post.call_count == 1


def test_exactly_the_cap_is_sorted(github_env):  # noqa: ARG001
    nodes = [_node(n) for n in range(SORT_CAP, 0, -1)]
    result, _ = _list([_page(nodes)], sort=["number"], limit=SORT_CAP)
    assert _numbers(result.issues) == list(range(1, SORT_CAP + 1))


# --- command -----------------------------------------------------------------


def test_more_than_the_cap_exits_1_with_the_message_and_no_rows(github_env, monkeypatch, capsys):  # noqa: ARG001
    monkeypatch.setattr(issue_list, "_get_repos", lambda explicit, _board: explicit or ["o/r"])
    monkeypatch.setattr(issue_list, "console", Console(width=200, color_system=None))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    nodes = [_node(n) for n in range(1, SORT_CAP + 2)]
    with patch.object(httpx.Client, "post", side_effect=[_page(nodes)]):
        assert main(["issue", "list", "--all-authors", "--repo", "o/r", "--sort", "number"]) == 1
    captured = capsys.readouterr()
    assert "more than 500 issues match; narrow the query" in captured.err
    assert "#1" not in captured.out
    assert "o/r" not in captured.out


def test_unknown_key_exits_2_and_names_the_valid_keys(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["issue", "list", "--sort", "created,priority"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "'priority'" in err
    assert all(key in err for key in VALID_KEYS)


def test_sort_and_activity_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["issue", "list", "--sort", "number", "--activity"])
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_help_lists_the_keys(capsys):
    with pytest.raises(SystemExit):
        main(["issue", "list", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "--sort KEY[,KEY...]" in out
    assert all(key in out for key in VALID_KEYS)


class _Client:
    seen: list[dict] = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_current_user(self) -> str:
        return "octocat"

    def list_issues_by_author(self, author, **kw):  # noqa: ARG002
        from src.issue.models import IssueListResult

        self.seen.append(kw)
        return IssueListResult(issues=sort_issues(FIXTURE, kw["sort"] or ["-created"]))

    def get_issues_by_ref(self, refs):  # noqa: ARG002
        from src.issue.models import IssueListResult

        return IssueListResult(issues=list(reversed(FIXTURE)))


@pytest.fixture
def stub_client(monkeypatch):
    monkeypatch.setattr(_Client, "seen", [])
    monkeypatch.setattr(issue_list, "IssueClient", _Client)
    monkeypatch.setattr(issue_list, "_get_repos", lambda explicit, _board: explicit or ["o/r"])
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


def test_cli_passes_the_keys_to_the_client(stub_client):  # noqa: ARG001
    assert main(["issue", "list", "--sort", "blocking,-created"]) == 0
    assert [kw["sort"] for kw in _Client.seen] == [("blocking", "-created")]


def test_without_the_flag_the_client_gets_no_sort(stub_client):  # noqa: ARG001
    assert main(["issue", "list"]) == 0
    assert [kw["sort"] for kw in _Client.seen] == [None]


def test_filters_line_shows_the_sort_only_when_given(stub_client, capsys):  # noqa: ARG001
    main(["issue", "list", "--sort", "blocking,-created", "-n", "5"])
    assert "sort=blocking,-created · limit=5" in capsys.readouterr().out
    main(["issue", "list"])
    assert "sort=" not in capsys.readouterr().out


def test_explicit_refs_are_sorted_too(stub_client, capsys):  # noqa: ARG001
    assert main(["issue", "list", "o/r#1", "o/r#2", "--sort", "-number", "--format", "json"]) == 0
    numbers = [item["number"] for item in json.loads(capsys.readouterr().out)["items"]]
    assert numbers == [4, 3, 2, 1]


def test_json_output_is_in_sort_order(stub_client, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--sort", "-blocking", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [item["number"] for item in data["items"]] == [1, 3, 2, 4]
    assert data["filters"]["sort"] == ["-blocking"]


# --- snapshot scope ----------------------------------------------------------


def _scope(sort: list[str] | None) -> SnapshotScope:
    return SnapshotScope.from_issue_args(
        board=None,
        author=None,
        repos=["o/r"],
        refs=None,
        states=["open"],
        labels=None,
        limit=100,
        sort=sort,
    )


def test_scope_with_sort_differs_by_keys_and_order_and_round_trips():
    plain, a, b, c = (
        _scope(None),
        _scope(["number"]),
        _scope(["-number"]),
        _scope(["updated", "number"]),
    )
    assert a.to_dict()["sort"] == ["number"]
    assert len({s.fingerprint() for s in (plain, a, b, c)}) == 4
    assert (
        _scope(["updated", "number"]).fingerprint() != _scope(["number", "updated"]).fingerprint()
    )
    for scope in (a, b, c):
        assert SnapshotScope.from_dict(scope.to_dict()) == scope
    assert SnapshotScope.from_dict(plain.to_dict()).sort is None


def test_scopes_of_other_kinds_ignore_sort():
    scope = SnapshotScope.from_pr_args(
        board=None, author=None, reviewer=None, repos=None, refs=None, states=None, limit=1
    )
    assert scope.sort is None


def test_snapshot_flow_matches_with_the_flag_and_not_without_it(stub_client, tkt_home, capsys):  # noqa: ARG001
    assert main(["issue", "list", "--sort", "number", "--snapshot", "a"]) == 0
    assert store.load("issue", "a").scope.sort == ("number",)
    capsys.readouterr()
    assert main(["issue", "list", "--sort", "number", "--diff", "a"]) == 0
    assert "scope-changed" not in capsys.readouterr().out
    assert main(["issue", "list", "--diff", "a"]) == 2
    err = capsys.readouterr()
    assert "scope mismatch" in err.out + err.err
    assert "sort: number → none" in err.out + err.err


def test_sort_note_names_the_change():
    def snap(sort):
        return make_snapshot(
            kind="issue", name="a", items=[make_item(ref="o/r#1")], scope=_scope(sort)
        )

    assert sort_note(snap(None), snap(["number"])) == "sort: none → number"
    assert (
        sort_note(snap(["number"]), snap(["-created", "number"]))
        == "sort: number → -created,number"
    )
    assert sort_note(snap(["number"]), snap(["number"])) is None
    assert not diff_snapshots(snap(None), snap(["number"])).scope_matches


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--sort", "-created"], ["--sort=-created"]),
        (["--sort", "number,-created", "-n", "2"], ["--sort", "number,-created", "-n", "2"]),
        (["--sort", "--limit", "2"], ["--sort", "--limit", "2"]),
        (["--sort"], ["--sort"]),
        (["--sort", "-blocking", "--limit", "1"], ["--sort=-blocking", "--limit", "1"]),
    ],
)
def test_a_reversed_first_key_is_attached_to_the_flag(argv, expected):
    from src.__main__ import _join_reversed_sort_keys

    assert _join_reversed_sort_keys(argv) == expected


# --- rank --------------------------------------------------------------------

RANK = ("priority:critical", "priority:high", "priority:medium", "priority:low")


def _ranked(number: int, *labels: str, repo: str = "o/r", blocking: int = 0) -> IssueInfo:
    issue = _issue(number, repo=repo, blocking=blocking)
    issue.labels = list(labels)
    return issue


def _install_norms(**rank_by_repo: tuple[str, ...]) -> None:
    """Give each `owner_name` repo the rank (`owner/name` in the loader); others have no norms."""

    def load(repo: str) -> Norms | None:
        rank = rank_by_repo.get(repo.replace("/", "_"))
        return None if rank is None else Norms(labels=Labels(rank=rank))

    set_loader(load)


RANK_FIXTURE = [
    _ranked(1, "bug"),
    _ranked(2, "priority:low"),
    _ranked(3, "priority:critical"),
    _ranked(4, "priority:medium", "enhancement"),
    _ranked(5, "priority:high"),
    _ranked(6, "priority:low", "priority:high"),
    _ranked(7, "Priority:Critical"),
]


def test_rank_orders_best_first_then_unranked_and_uses_the_better_of_two_labels():
    _install_norms(o_r=RANK)
    assert _numbers(sort_issues(RANK_FIXTURE, ["rank"])) == [3, 7, 5, 6, 4, 2, 1]


def test_reversed_rank_puts_unranked_first():
    _install_norms(o_r=RANK)
    assert _numbers(sort_issues(RANK_FIXTURE, ["-rank"])) == [1, 2, 4, 5, 6, 3, 7]


def test_rank_ties_are_broken_by_the_next_keys():
    _install_norms(o_r=RANK)
    issues = [
        _ranked(10, "priority:high"),
        _ranked(11, "priority:high", blocking=3),
        _ranked(12, "priority:critical"),
        _ranked(13, "priority:high", blocking=3),
    ]
    assert _numbers(sort_issues(issues, ["rank", "blocking", "number"])) == [12, 11, 13, 10]
    assert _numbers(sort_issues(issues, ["rank", "-number"])) == [12, 13, 11, 10]


def test_each_repo_uses_its_own_rank():
    _install_norms(a_x=("p1", "p2"), b_x=("p2", "p1"))
    issues = [
        _ranked(1, "p1", repo="a/x"),
        _ranked(2, "p2", repo="a/x"),
        _ranked(3, "p1", repo="b/x"),
        _ranked(4, "p2", repo="b/x"),
    ]
    by_repo = [(i.repo, i.number) for i in sort_issues(issues, ["rank", "number"])]
    assert by_repo == [("a/x", 1), ("b/x", 4), ("a/x", 2), ("b/x", 3)]


def test_a_repo_without_rank_raises_and_names_it():
    _install_norms()
    with pytest.raises(MissingRankError, match=r"no \[labels\] rank in the norms of o/r"):
        sort_issues(RANK_FIXTURE, ["rank"])


def test_a_repo_with_norms_but_an_empty_rank_raises():
    _install_norms(o_r=())
    with pytest.raises(MissingRankError):
        sort_issues(RANK_FIXTURE, ["number", "-rank"])


def test_other_keys_do_not_need_a_rank():
    _install_norms()
    assert _numbers(sort_issues(RANK_FIXTURE, ["-number"])) == [7, 6, 5, 4, 3, 2, 1]


def test_require_rank_checks_every_repo_only_when_sorting_by_rank():
    _install_norms(a_x=RANK)
    require_rank(["number"], ["a/x", "b/x"])
    require_rank(["rank"], ["a/x"])
    with pytest.raises(MissingRankError, match="b/x"):
        require_rank(["created", "-rank"], ["a/x", "b/x"])


def test_sort_rank_with_a_repo_lacking_rank_exits_1_and_prints_no_rows(stub_client, capsys):  # noqa: ARG001
    _install_norms(a_x=RANK)
    argv = ["issue", "list", "--all-authors", "--repo", "a/x", "--repo", "b/x", "--sort", "rank"]
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert "no [labels] rank in the norms of b/x" in captured.err
    assert "#1" not in captured.out
    assert _Client.seen == []


def test_other_sort_keys_still_work_in_a_repo_lacking_rank(stub_client):  # noqa: ARG001
    _install_norms()
    assert main(["issue", "list", "--all-authors", "--repo", "a/x", "--sort", "number"]) == 0
    assert len(_Client.seen) == 1


def test_sort_rank_checks_the_repos_of_explicit_refs(stub_client, capsys):  # noqa: ARG001
    _install_norms(a_x=RANK, o_r=RANK)
    assert main(["issue", "list", "a/x#1", "b/x#2", "--sort", "rank"]) == 1
    assert "no [labels] rank in the norms of b/x" in capsys.readouterr().err
    assert main(["issue", "list", "a/x#1", "--sort", "rank"]) == 0
