"""`tkt issue list` per-field date flags (--created-since and friends)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest

from src.__main__ import main
from src.issue.github_api import IssueClient
from src.issue.models import IssueListResult
from src.snapshot import store
from src.snapshot.models import WindowScope

NEW_FLAGS = [
    f"--{field}-{kind}"
    for field in ("created", "updated", "closed")
    for kind in ("since", "after", "before")
]


@pytest.fixture
def queries(monkeypatch) -> list[str]:
    sent: list[str] = []

    def fake_search(_self, search_query: str, *_args, **_kw) -> IssueListResult:
        sent.append(search_query)
        return IssueListResult(issues=[], total_count=0)

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(IssueClient, "_search_issues", fake_search)
    monkeypatch.setattr(IssueClient, "get_current_user", lambda _self: "me")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    return sent


def _days_ago(days: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).date().isoformat()


def _run(capsys, *args: str) -> tuple[int, str, str]:
    code = main(["issue", "list", "--repo", "o/r", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestRegistration:
    def test_all_nine_flags_are_accepted(self, queries, capsys):
        for flag in NEW_FLAGS:
            value = "3" if flag.endswith("since") else "2026-08-01"
            code, _, err = _run(capsys, "--all", flag, value)
            assert code == 0, (flag, err)
        assert len(queries) == len(NEW_FLAGS)

    @pytest.mark.parametrize("kind", ["since", "after", "before"])
    def test_merged_flags_are_unrecognized_on_issue_list(self, kind, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["issue", "list", f"--merged-{kind}", "7"])
        assert exc.value.code == 2
        assert "unrecognized arguments" in capsys.readouterr().err

    @pytest.mark.parametrize("flag", NEW_FLAGS)
    def test_review_does_not_get_the_flags(self, flag):
        with pytest.raises(SystemExit) as exc:
            main(["review", flag, "7"])
        assert exc.value.code == 2

    def test_non_integer_days_is_an_argparse_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["issue", "list", "--created-since", "soon"])
        assert exc.value.code == 2
        assert "--created-since" in capsys.readouterr().err

    def test_help_groups_the_flags_and_names_the_field(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["issue", "list", "--help"])
        assert exc.value.code == 0
        out = " ".join(capsys.readouterr().out.split())
        assert "Date filters by field" in out
        assert "Only issues created since the start of the UTC day" in out
        assert "Only issues closed on/before this UTC date" in out
        assert "--merged-since" not in out


class TestQuery:
    def test_created_since_filters_on_created(self, queries, capsys):
        code, out, _ = _run(capsys, "--created-since", "14")
        assert code == 0
        assert f"created:>={_days_ago(14)}" in queries[0]
        assert "created" in out

    def test_updated_since_filters_on_updated(self, queries, capsys):
        _run(capsys, "--updated-since", "14")
        assert f"updated:>={_days_ago(14)}" in queries[0]
        assert "created:" not in queries[0]

    def test_closed_since_with_closed_flag(self, queries, capsys):
        code, _, _ = _run(capsys, "--closed", "--closed-since", "7")
        assert code == 0
        assert f"closed:>={_days_ago(7)}" in queries[0]
        assert "is:closed" in queries[0]

    def test_closed_since_with_all_flag(self, queries, capsys):
        code, _, _ = _run(capsys, "--all", "--closed-since", "7")
        assert code == 0
        assert f"closed:>={_days_ago(7)}" in queries[0]

    def test_inclusive_absolute_bounds(self, queries, capsys):
        _run(capsys, "--created-after", "2026-11-01", "--created-before", "2026-11-07")
        assert "created:2026-11-01..2026-11-07" in queries[0]

    def test_same_day_bounds_are_allowed(self, queries, capsys):
        code, _, _ = _run(capsys, "--created-after", "2026-11-01", "--created-before", "2026-11-01")
        assert code == 0
        assert "created:2026-11-01..2026-11-01" in queries[0]

    def test_since_zero_means_today_utc(self, queries, capsys):
        code, _, _ = _run(capsys, "--created-since", "0")
        assert code == 0
        assert f"created:>={_days_ago(0)}" in queries[0]

    def test_old_flags_give_the_same_query(self, queries, capsys):
        old_code, _, _ = _run(capsys, "--since", "14", "--date-field", "created")
        new_code, _, _ = _run(capsys, "--created-since", "14")
        assert old_code == new_code == 0
        assert queries[0] == queries[1]

    def test_empty_result_message_names_the_field(self, queries, capsys):  # noqa: ARG002
        _, out, _ = _run(capsys, "--created-since", "14")
        assert "created" in out
        assert "No issues" in out


class TestErrors:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["--created-since", "3", "--created-after", "2026-11-01"], "--created-since"),
            (["--created-since", "3", "--created-before", "2026-11-01"], "--created-before"),
            (["--created-since", "3", "--updated-since", "3"], "--updated-since"),
            (["--created-since", "3", "--since", "3"], "--since"),
            (["--created-after", "2026-11-01", "--after", "2026-11-01"], "--after"),
            (["--created-since", "3", "--date-field", "created"], "--date-field"),
            (["--created-since", "-1"], "--created-since must be a non-negative"),
            (["--created-after", "2026-13-40"], "for --created-after"),
            (["--updated-before", "nope"], "for --updated-before"),
            (
                ["--created-after", "2026-11-09", "--created-before", "2026-11-01"],
                "--created-before",
            ),
            (["--created-since", "14", "o/r#1"], "--created-since cannot narrow explicit refs"),
            (["--created-after", "2026-11-01", "o/r#1"], "--created-after cannot narrow"),
            (["--closed-since", "7"], "--closed-since only matches closed items"),
            (["--closed-after", "2026-11-01"], "--closed-after only matches closed items"),
            (["--closed-before", "2026-11-01"], "--closed-before only matches closed items"),
        ],
    )
    def test_error_names_the_typed_flag_and_exits_1(self, args, expected, queries, capsys):
        code, _, err = _run(capsys, *args)
        assert code == 1
        assert expected in err
        assert queries == []

    def test_two_field_error_names_both_flags(self, queries, capsys):  # noqa: ARG002
        _, _, err = _run(capsys, "--created-since", "14", "--updated-since", "2")
        assert "--created-since" in err
        assert "--updated-since" in err

    def test_old_flag_errors_are_unchanged(self, queries, capsys):  # noqa: ARG002
        _, _, err = _run(capsys, "--since", "3", "--after", "2026-11-01")
        assert "--since cannot be combined with --after/--before" in err


class TestSnapshotScope:
    def test_since_form_scope_and_fingerprint_match(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--since", "14", "--date-field", "created", "--snapshot", "a")[0] == 0
        old_scope = store.load("issue", "a").scope
        assert _run(capsys, "--created-since", "14", "--snapshot", "b")[0] == 0
        new_scope = store.load("issue", "b").scope
        assert old_scope.window == WindowScope(field="created", since_days=14)
        assert new_scope == old_scope
        assert new_scope.fingerprint() == old_scope.fingerprint()

    def test_absolute_form_scope_and_fingerprint_match(self, queries, tkt_home, capsys):  # noqa: ARG002
        old = ["--after", "2026-11-01", "--before", "2026-11-07", "--date-field", "closed", "--all"]
        new = ["--closed-after", "2026-11-01", "--closed-before", "2026-11-07", "--all"]
        assert _run(capsys, *old, "--snapshot", "a")[0] == 0
        assert _run(capsys, *new, "--snapshot", "b")[0] == 0
        a, b = store.load("issue", "a").scope, store.load("issue", "b").scope
        assert a.window == WindowScope(field="closed", after="2026-11-01", before="2026-11-07")
        assert a == b
        assert a.fingerprint() == b.fingerprint()

    def test_diff_across_spellings_has_no_scope_mismatch(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--since", "14", "--date-field", "created", "--snapshot", "a")[0] == 0
        code, out, err = _run(capsys, "--created-since", "14", "--diff", "a")
        assert code == 0
        assert "scope mismatch" not in out + err

    def test_watch_twice_has_no_scope_mismatch(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--created-since", "14", "--watch", "w")[0] == 0
        code, out, err = _run(capsys, "--created-since", "14", "--watch", "w")
        assert code == 0
        assert "scope mismatch" not in out + err

    def test_different_field_is_a_scope_change(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--created-since", "14", "--snapshot", "a")[0] == 0
        assert _run(capsys, "--updated-since", "14", "--snapshot", "b")[0] == 0
        a, b = store.load("issue", "a").scope, store.load("issue", "b").scope
        assert a.fingerprint() != b.fingerprint()
