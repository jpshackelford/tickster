"""`tkt review` per-field date flags (--created-since and friends)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest

from src.__main__ import main
from src.date_window import DateWindowError, build_date_window, field_flag_names
from src.review.github_api import ReviewClient
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

    def fake_search(_self, search_query: str, _limit: int) -> list[dict]:
        sent.append(search_query)
        return []

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(ReviewClient, "_search_prs", fake_search)
    monkeypatch.setattr(ReviewClient, "get_current_user", lambda _self: "me")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    return sent


def _days_ago(days: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).date().isoformat()


def _run(capsys, *args: str) -> tuple[int, str, str]:
    code = main(["review", "--repo", "o/r", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestRegistration:
    def test_all_twelve_flags_are_accepted(self, queries, capsys):
        for flag in NEW_FLAGS:
            value = "3" if flag.endswith("since") else "2026-08-01"
            states = ["--merged"] if "merged" in flag else ["--closed"] if "closed" in flag else []
            code, _, err = _run(capsys, *states, flag, value)
            assert code == 0, (flag, err)
        assert len(NEW_FLAGS) == 12
        assert len(queries) >= len(NEW_FLAGS)

    def test_non_integer_days_is_an_argparse_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["review", "--created-since", "soon"])
        assert exc.value.code == 2
        assert "--created-since" in capsys.readouterr().err

    def test_help_groups_the_flags_and_names_the_field(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["review", "--help"])
        assert exc.value.code == 0
        out = " ".join(capsys.readouterr().out.split())
        assert "Date filters by field" in out
        assert "Only PRs merged since the start of the UTC day" in out
        assert "Only PRs created on/after this UTC date" in out


class TestQuery:
    def test_created_since_filters_requested_and_reviewed_on_created(self, queries, capsys):
        code, out, _ = _run(capsys, "--created-since", "14")
        assert code == 0
        assert queries
        assert all(f"created:>={_days_ago(14)}" in q for q in queries)
        assert "No PRs needing your review (created ≥" in out

    def test_updated_since_returns_on_updated(self, queries, capsys):
        assert _run(capsys, "--updated-since", "2")[0] == 0
        assert all(f"updated:>={_days_ago(2)}" in q for q in queries)

    def test_merged_since_with_merged_flag(self, queries, capsys):
        assert _run(capsys, "--merged", "--merged-since", "7")[0] == 0
        assert f"merged:>={_days_ago(7)}" in queries[0]
        assert "is:merged" in queries[0]

    def test_closed_since_with_closed_flag(self, queries, capsys):
        assert _run(capsys, "--closed", "--closed-since", "7")[0] == 0
        assert f"closed:>={_days_ago(7)}" in queries[0]
        assert "is:unmerged" in queries[0]

    def test_closed_since_with_merged_flag(self, queries, capsys):
        assert _run(capsys, "--merged", "--closed-since", "7")[0] == 0
        assert f"closed:>={_days_ago(7)}" in queries[0]

    def test_inclusive_absolute_bounds(self, queries, capsys):
        _run(capsys, "--created-after", "2026-11-01", "--created-before", "2026-11-07")
        assert all("created:2026-11-01..2026-11-07" in q for q in queries)

    def test_since_zero_means_today_utc(self, queries, capsys):
        assert _run(capsys, "--created-since", "0")[0] == 0
        assert f"created:>={_days_ago(0)}" in queries[0]

    def test_empty_result_message_names_the_field(self, queries, capsys):  # noqa: ARG002
        _, out, _ = _run(capsys, "--merged", "--merged-since", "14")
        assert "No historical PRs found" in out
        assert f"merged ≥ {_days_ago(14)}, UTC" in out

    def test_no_new_flags_adds_no_date_qualifier(self, queries, capsys):
        assert _run(capsys)[0] == 0
        assert all("created:" not in q and "updated:" not in q for q in queries)


class TestErrors:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["--created-since", "-1"], "--created-since must be a non-negative"),
            (["--created-after", "2026-13-40"], "for --created-after"),
            (["--merged", "--merged-before", "nope"], "for --merged-before"),
            (["--created-since", "3", "--created-after", "2026-11-01"], "--created-since"),
            (["--created-since", "3", "--updated-since", "3"], "--updated-since"),
        ],
    )
    def test_error_names_the_typed_flag_and_exits_1(self, args, expected, queries, capsys):
        code, _, err = _run(capsys, *args)
        assert code == 1
        assert expected in err
        assert queries == []

    @pytest.mark.parametrize("kind", ["since", "after", "before"])
    def test_merged_flag_without_merged_state(self, kind, queries, capsys):
        value = "7" if kind == "since" else "2026-11-01"
        code, _, err = _run(capsys, f"--merged-{kind}", value)
        assert code == 1
        assert f"--merged-{kind} only matches merged items" in err
        assert "the state filter is open: add --merged" in err
        assert "--all" not in err
        assert queries == []

    @pytest.mark.parametrize("kind", ["since", "after", "before"])
    def test_closed_flag_without_closed_or_merged_state(self, kind, queries, capsys):
        value = "7" if kind == "since" else "2026-11-01"
        code, _, err = _run(capsys, f"--closed-{kind}", value)
        assert code == 1
        assert f"--closed-{kind} only matches closed items" in err
        assert "the state filter is open: add --closed (or --merged)" in err
        assert "--all" not in err
        assert queries == []

    def test_all_flag_does_not_satisfy_the_merged_check(self, queries, capsys):
        code, _, err = _run(capsys, "--all", "--merged-since", "7")
        assert code == 1
        assert "--merged-since only matches merged items" in err
        assert queries == []

    def test_all_flag_does_not_satisfy_the_closed_check(self, queries, capsys):
        code, _, err = _run(capsys, "--all", "--closed-since", "7")
        assert code == 1
        assert "--closed-since only matches closed items" in err
        assert queries == []

    def test_merged_since_needs_merged_even_with_closed(self, queries, capsys):  # noqa: ARG002
        code, _, err = _run(capsys, "--closed", "--merged-since", "7")
        assert code == 1
        assert "state filter is closed: add --merged" in err


class TestBuildDateWindowAllFlag:
    NOW = datetime(2026, 11, 13, tzinfo=UTC)

    def test_default_still_suggests_all(self):
        with pytest.raises(DateWindowError, match=r"add --closed, --merged or --all"):
            build_date_window(
                ["open"], since_days=3, date_field="closed", flag_names=field_flag_names("closed")
            )

    def test_has_all_flag_false_drops_all_from_both_remedies(self):
        for field, remedy in (("merged", "add --merged"), ("closed", "add --closed (or --merged)")):
            with pytest.raises(DateWindowError) as exc:
                build_date_window(
                    ["open"],
                    since_days=3,
                    date_field=field,
                    flag_names=field_flag_names(field),
                    has_all_flag=False,
                )
            assert str(exc.value).endswith(remedy)

    def test_merged_state_satisfies_closed(self):
        window = build_date_window(
            ["merged"],
            since_days=7,
            date_field="closed",
            flag_names=field_flag_names("closed"),
            has_all_flag=False,
            now=self.NOW,
        )
        assert window is not None
        assert window.describe().startswith("closed")


class TestSnapshotScope:
    def test_scope_window_is_stored_as_field_and_days(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--merged", "--merged-since", "14", "--snapshot", "a")[0] == 0
        assert store.load("review", "a").scope.window == WindowScope(field="merged", since_days=14)

    def test_absolute_scope_window_is_stored_as_field_and_dates(self, queries, tkt_home, capsys):  # noqa: ARG002
        new = ["--merged", "--merged-after", "2026-11-01", "--merged-before", "2026-11-07"]
        assert _run(capsys, *new, "--snapshot", "a")[0] == 0
        window = store.load("review", "a").scope.window
        assert window == WindowScope(field="merged", after="2026-11-01", before="2026-11-07")

    def test_diff_against_own_snapshot_has_no_scope_mismatch(self, queries, tkt_home, capsys):  # noqa: ARG002
        assert _run(capsys, "--merged", "--merged-since", "14", "--snapshot", "a")[0] == 0
        code, out, err = _run(capsys, "--merged", "--merged-since", "14", "--diff", "a")
        assert code == 0
        assert "scope mismatch" not in out + err

    def test_watch_twice_has_no_scope_mismatch(self, queries, tkt_home, capsys):  # noqa: ARG002
        args = ("--created-since", "14", "--watch", "w")
        assert _run(capsys, *args)[0] == 0
        code, out, err = _run(capsys, *args)
        assert code == 0
        assert "scope mismatch" not in out + err
