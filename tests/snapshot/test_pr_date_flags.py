"""`tkt pr list` per-field date flags (--merged-since and friends)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest

from src.__main__ import main
from src.pr.github_api import PRClient
from src.pr.models import PRListResult
from src.snapshot import store
from src.snapshot.models import WindowScope

NEW_FLAGS = [
    f"--{field}-{kind}"
    for field in ("created", "updated", "closed", "merged")
    for kind in ("since", "after", "before")
]


@pytest.fixture
def queries(monkeypatch) -> list[str]:
    sent: list[str] = []

    def fake_search(_self, search_query: str, *_args, **_kw) -> PRListResult:
        sent.append(search_query)
        return PRListResult(prs=[])

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(PRClient, "_search_prs", fake_search)
    monkeypatch.setattr(PRClient, "get_current_user", lambda _self: "me")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    return sent


def _days_ago(days: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).date().isoformat()


def _run(capsys, *args: str) -> tuple[int, str, str]:
    code = main(["pr", "list", "--repo", "o/r", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestRegistration:
    def test_all_twelve_flags_are_accepted(self, queries, capsys):
        for flag in NEW_FLAGS:
            value = "3" if flag.endswith("since") else "2026-08-01"
            code, _, err = _run(capsys, "--all", flag, value)
            assert code == 0, (flag, err)
        assert len(queries) == len(NEW_FLAGS) == 12

    def test_non_integer_days_is_an_argparse_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["pr", "list", "--merged-since", "soon"])
        assert exc.value.code == 2
        assert "--merged-since" in capsys.readouterr().err

    def test_help_groups_the_flags_and_names_the_field(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["pr", "list", "--help"])
        assert exc.value.code == 0
        out = " ".join(capsys.readouterr().out.split())
        assert "Date filters by field" in out
        assert "Only PRs merged since the start of the UTC day" in out
        assert "Only PRs created on/after this UTC date" in out


class TestQuery:
    def test_merged_since_with_merged_flag(self, queries, capsys):
        code, _, _ = _run(capsys, "--merged", "--merged-since", "14")
        assert code == 0
        assert f"merged:>={_days_ago(14)}" in queries[0]
        assert "is:merged" in queries[0]

    def test_merged_since_with_all_flag(self, queries, capsys):
        assert _run(capsys, "--all", "--merged-since", "14")[0] == 0
        assert f"merged:>={_days_ago(14)}" in queries[0]

    def test_closed_since_with_closed_flag(self, queries, capsys):
        assert _run(capsys, "--closed", "--closed-since", "7")[0] == 0
        assert f"closed:>={_days_ago(7)}" in queries[0]

    def test_closed_since_with_merged_flag(self, queries, capsys):
        assert _run(capsys, "--merged", "--closed-since", "7")[0] == 0
        assert f"closed:>={_days_ago(7)}" in queries[0]

    def test_created_since_filters_on_created(self, queries, capsys):
        code, out, _ = _run(capsys, "--created-since", "7")
        assert code == 0
        assert f"created:>={_days_ago(7)}" in queries[0]
        assert "created" in out

    def test_updated_since_with_default_open_state(self, queries, capsys):
        assert _run(capsys, "--updated-since", "3")[0] == 0
        assert f"updated:>={_days_ago(3)}" in queries[0]

    def test_inclusive_absolute_bounds(self, queries, capsys):
        _run(capsys, "--created-after", "2026-11-01", "--created-before", "2026-11-07")
        assert "created:2026-11-01..2026-11-07" in queries[0]

    def test_merged_absolute_bounds(self, queries, capsys):
        _run(capsys, "--merged", "--merged-after", "2026-11-01", "--merged-before", "2026-11-07")
        assert "merged:2026-11-01..2026-11-07" in queries[0]

    def test_since_zero_means_today_utc(self, queries, capsys):
        assert _run(capsys, "--created-since", "0")[0] == 0
        assert f"created:>={_days_ago(0)}" in queries[0]

    def test_all_authors_combines(self, queries, capsys):
        code, _, _ = _run(capsys, "--all-authors", "--created-since", "14")
        assert code == 0
        assert f"created:>={_days_ago(14)}" in queries[0]
        assert "author:" not in queries[0]

    def test_graph_still_works_with_merged_window(self, queries, capsys):
        code, _, _ = _run(capsys, "--merged", "--merged-since", "30", "--graph")
        assert code == 0
        assert f"merged:>={_days_ago(30)}" in queries[0]

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            (["--merged", "--since", "14"], ["--merged", "--merged-since", "14"]),
            (
                ["--since", "14", "--date-field", "created"],
                ["--created-since", "14"],
            ),
            (
                ["--merged", "--after", "2026-11-01", "--before", "2026-11-07"],
                ["--merged", "--merged-after", "2026-11-01", "--merged-before", "2026-11-07"],
            ),
            (["--closed", "--since", "7"], ["--closed", "--closed-since", "7"]),
            (["--since", "5"], ["--updated-since", "5"]),
        ],
    )
    def test_old_flags_give_the_same_query(self, old, new, queries, capsys):
        assert _run(capsys, *old)[0] == 0
        assert _run(capsys, *new)[0] == 0
        assert queries[0] == queries[1]

    def test_empty_result_message_names_the_field(self, queries, capsys):  # noqa: ARG002
        _, out, _ = _run(capsys, "--merged", "--merged-since", "14")
        assert "No PRs" in out
        assert "merged" in out


class TestErrors:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["--merged-since", "14"], "--merged-since only matches merged items"),
            (["--merged-after", "2026-11-01"], "--merged-after only matches merged items"),
            (["--merged-before", "2026-11-01"], "--merged-before only matches merged items"),
            (["--closed-since", "7"], "--closed-since only matches closed items"),
            (["--closed-after", "2026-11-01"], "--closed-after only matches closed items"),
            (["--closed-before", "2026-11-01"], "--closed-before only matches closed items"),
            (["--created-since", "-1"], "--created-since must be a non-negative"),
            (["--created-after", "2026-13-40"], "for --created-after"),
            (["--merged", "--merged-before", "nope"], "for --merged-before"),
            (["--created-since", "3", "--created-after", "2026-11-01"], "--created-since"),
            (
                ["--merged", "--merged-since", "3", "--merged-before", "2026-11-01"],
                "--merged-before",
            ),
            (["--created-since", "3", "--updated-since", "3"], "--updated-since"),
            (["--merged", "--merged-since", "3", "--since", "3"], "--since"),
            (["--merged", "--merged-since", "3", "--date-field", "merged"], "--date-field"),
            (["--created-after", "2026-11-01", "--after", "2026-11-01"], "--after"),
            (["--merged", "--merged-since", "14", "o/r#1"], "--merged-since cannot narrow"),
            (["--created-after", "2026-11-01", "o/r#1"], "--created-after cannot narrow"),
        ],
    )
    def test_error_names_the_typed_flag_and_exits_1(self, args, expected, queries, capsys):
        code, _, err = _run(capsys, *args)
        assert code == 1
        assert expected in err
        assert queries == []

    def test_merged_message_says_which_state_flag_to_add(self, queries, capsys):  # noqa: ARG002
        _, _, err = _run(capsys, "--merged-since", "14")
        assert "state filter is open: add --merged (or --all)" in err

    def test_closed_message_says_which_state_flag_to_add(self, queries, capsys):  # noqa: ARG002
        _, _, err = _run(capsys, "--closed-since", "7")
        assert "state filter is open: add --closed, --merged or --all" in err

    def test_two_field_error_names_both_flags(self, queries, capsys):  # noqa: ARG002
        _, _, err = _run(capsys, "--created-since", "14", "--merged-since", "2")
        assert "--created-since" in err
        assert "--merged-since" in err

    def test_old_flag_errors_are_unchanged(self, queries, capsys):  # noqa: ARG002
        _, _, err = _run(capsys, "--date-field", "merged", "--since", "7")
        assert "--date-field merged only matches merged items" in err
        assert "add --merged" in err
        assert "(or --all)" not in err


class TestSnapshotScope:
    def test_since_form_scope_and_fingerprint_match(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--merged", "--since", "14", "--snapshot", "a")[0] == 0
        old_scope = store.load("pr", "a").scope
        assert _run(capsys, "--merged", "--merged-since", "14", "--snapshot", "b")[0] == 0
        new_scope = store.load("pr", "b").scope
        assert old_scope.window == WindowScope(field="merged", since_days=14)
        assert new_scope == old_scope
        assert new_scope.fingerprint() == old_scope.fingerprint()

    def test_absolute_form_scope_and_fingerprint_match(self, queries, tkt_home, capsys):  # noqa: ARG002
        old = ["--after", "2026-11-01", "--before", "2026-11-07", "--date-field", "merged", "--all"]
        new = ["--merged-after", "2026-11-01", "--merged-before", "2026-11-07", "--all"]
        assert _run(capsys, *old, "--snapshot", "a")[0] == 0
        assert _run(capsys, *new, "--snapshot", "b")[0] == 0
        a, b = store.load("pr", "a").scope, store.load("pr", "b").scope
        assert a.window == WindowScope(field="merged", after="2026-11-01", before="2026-11-07")
        assert a == b
        assert a.fingerprint() == b.fingerprint()

    def test_diff_across_spellings_has_no_scope_mismatch(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--merged", "--since", "14", "--snapshot", "a")[0] == 0
        code, out, err = _run(capsys, "--merged", "--merged-since", "14", "--diff", "a")
        assert code == 0
        assert "scope mismatch" not in out + err

    def test_watch_twice_has_no_scope_mismatch(self, queries, tkt_home, capsys):  # noqa: ARG002
        args = ("--merged", "--merged-since", "14", "--watch", "w")
        assert _run(capsys, *args)[0] == 0
        code, out, err = _run(capsys, *args)
        assert code == 0
        assert "scope mismatch" not in out + err

    def test_different_field_is_a_scope_change(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--all", "--created-since", "14", "--snapshot", "a")[0] == 0
        assert _run(capsys, "--all", "--merged-since", "14", "--snapshot", "b")[0] == 0
        a, b = store.load("pr", "a").scope, store.load("pr", "b").scope
        assert a.fingerprint() != b.fingerprint()
