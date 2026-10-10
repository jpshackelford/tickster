"""Tests for the shared date-window filtering helpers."""

from datetime import UTC, datetime

import pytest

from src.date_window import (
    DateWindowError,
    build_date_window,
    resolve_date_field,
)

# Fixed reference time for deterministic --since calculations.
NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)


class TestResolveDateField:
    def test_explicit_field_wins(self):
        assert resolve_date_field(["open"], "merged") == "merged"

    def test_merged_only_infers_merged(self):
        assert resolve_date_field(["merged"]) == "merged"

    def test_closed_only_infers_closed(self):
        assert resolve_date_field(["closed"]) == "closed"

    def test_open_infers_updated(self):
        assert resolve_date_field(["open"]) == "updated"

    def test_mixed_states_infer_updated(self):
        assert resolve_date_field(["merged", "closed"]) == "updated"

    def test_none_states_infer_updated(self):
        assert resolve_date_field(None) == "updated"

    def test_invalid_explicit_field_raises(self):
        with pytest.raises(DateWindowError):
            resolve_date_field(["open"], "bogus")


class TestBuildDateWindow:
    def test_no_options_returns_none(self):
        assert build_date_window(["open"]) is None

    def test_date_field_alone_raises(self):
        with pytest.raises(
            DateWindowError, match="--date-field needs --since, --after or --before"
        ):
            build_date_window(["merged"], date_field="created")

    def test_since_days_relative(self):
        window = build_date_window(["merged"], since_days=14, now=NOW)
        assert window is not None
        assert window.field == "merged"
        assert window.after.isoformat() == "2026-08-25"
        assert window.before is None

    def test_since_zero_days(self):
        window = build_date_window(["open"], since_days=0, now=NOW)
        assert window.after.isoformat() == "2026-09-08"

    def test_after_only(self):
        window = build_date_window(["open"], after="2026-08-01")
        assert window.field == "updated"
        assert window.after.isoformat() == "2026-08-01"
        assert window.before is None

    def test_before_only(self):
        window = build_date_window(["closed"], before="2026-08-31")
        assert window.field == "closed"
        assert window.before.isoformat() == "2026-08-31"
        assert window.after is None

    def test_after_and_before_interval(self):
        window = build_date_window(["open"], after="2026-08-01", before="2026-08-31")
        assert window.after.isoformat() == "2026-08-01"
        assert window.before.isoformat() == "2026-08-31"

    def test_explicit_date_field_override(self):
        window = build_date_window(["merged"], since_days=30, date_field="created", now=NOW)
        assert window.field == "created"

    def test_since_with_after_raises(self):
        with pytest.raises(DateWindowError):
            build_date_window(["open"], since_days=7, after="2026-08-01")

    def test_negative_since_raises(self):
        with pytest.raises(DateWindowError):
            build_date_window(["open"], since_days=-1, now=NOW)

    def test_after_later_than_before_raises(self):
        with pytest.raises(DateWindowError):
            build_date_window(["open"], after="2026-09-01", before="2026-08-01")

    def test_invalid_date_format_raises(self):
        with pytest.raises(DateWindowError):
            build_date_window(["open"], after="08/01/2026")


class TestToQualifier:
    def test_after_only_qualifier(self):
        window = build_date_window(["merged"], since_days=14, now=NOW)
        assert window.to_qualifier() == "merged:>=2026-08-25"

    def test_before_only_qualifier(self):
        window = build_date_window(["closed"], before="2026-08-31")
        assert window.to_qualifier() == "closed:<=2026-08-31"

    def test_interval_qualifier(self):
        window = build_date_window(["open"], after="2026-08-01", before="2026-08-31")
        assert window.to_qualifier() == "updated:2026-08-01..2026-08-31"


class TestWindowWithRefs:
    def test_since_with_refs_raises(self):
        with pytest.raises(DateWindowError, match=r"--since cannot narrow explicit refs"):
            build_date_window(["open"], since_days=7, refs=["o/r#1"])

    def test_after_before_with_refs_names_both_flags(self):
        with pytest.raises(DateWindowError, match=r"--after/--before cannot narrow"):
            build_date_window(["open"], after="2026-08-01", before="2026-08-31", refs=["o/r#1"])

    def test_refs_without_window_is_fine(self):
        assert build_date_window(["open"], refs=["o/r#1"]) is None

    def test_message_offers_both_ways_out(self):
        with pytest.raises(DateWindowError, match="Drop the refs to search by date, or drop"):
            build_date_window(["open"], since_days=7, refs=["o/r#1"])


class TestExplicitFieldMustBeMatchable:
    def test_merged_field_with_open_only_raises(self):
        with pytest.raises(DateWindowError, match="add --merged"):
            build_date_window(["open"], since_days=7, date_field="merged")

    def test_merged_field_with_no_states_means_open_and_raises(self):
        with pytest.raises(DateWindowError, match="state filter is open"):
            build_date_window(None, since_days=7, date_field="merged")

    def test_merged_field_with_merged_state_ok(self):
        window = build_date_window(["merged"], since_days=7, date_field="merged", now=NOW)
        assert window is not None and window.field == "merged"

    def test_merged_field_with_all_states_ok(self):
        states = ["open", "merged", "closed"]
        assert build_date_window(states, since_days=7, date_field="merged", now=NOW) is not None

    def test_closed_field_with_open_only_raises(self):
        with pytest.raises(DateWindowError, match="add --closed"):
            build_date_window(["open"], since_days=7, date_field="closed")

    def test_closed_field_with_merged_state_ok(self):
        assert build_date_window(["merged"], since_days=7, date_field="closed", now=NOW)

    def test_issues_have_no_merged_date(self):
        with pytest.raises(DateWindowError, match="Issues have no merged date"):
            build_date_window(
                ["open", "closed"], since_days=7, date_field="merged", merged_ok=False
            )

    def test_created_and_updated_fit_any_state(self):
        for field in ("created", "updated"):
            assert build_date_window(["open"], since_days=7, date_field=field, now=NOW)

    def test_inferred_field_is_not_validated(self):
        window = build_date_window(["merged"], since_days=7, now=NOW)
        assert window is not None and window.field == "merged"


class TestDescribeAndSinceDays:
    def test_since_days_kept_as_typed(self):
        window = build_date_window(["merged"], since_days=14, now=NOW)
        assert window is not None
        assert window.since_days == 14 and str(window.after) == "2026-08-25"

    def test_absolute_window_has_no_since_days(self):
        window = build_date_window(["merged"], after="2026-08-01")
        assert window is not None and window.since_days is None

    def test_describe_after_only(self):
        window = build_date_window(["merged"], since_days=14, now=NOW)
        assert window is not None and window.describe() == "merged ≥ 2026-08-25"

    def test_describe_before_only(self):
        window = build_date_window(["closed"], before="2026-08-31")
        assert window is not None and window.describe() == "closed ≤ 2026-08-31"

    def test_describe_interval(self):
        window = build_date_window(["open"], after="2026-08-01", before="2026-08-31")
        assert window is not None and window.describe() == "updated 2026-08-01..2026-08-31"
