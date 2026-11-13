"""Tests for the shared date-window filtering helpers."""

from datetime import UTC, datetime

import pytest

from src.date_window import (
    ISSUE_DATE_FIELDS,
    DateWindowError,
    build_date_window,
    field_flag_names,
    resolve_field_flags,
)

# Fixed reference time for deterministic --<field>-since calculations.
NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)


def build(states, field="updated", **kwargs):
    """build_date_window with the flag names the per-field flags of ``field`` carry."""
    return build_date_window(states, date_field=field, flag_names=field_flag_names(field), **kwargs)


class TestBuildDateWindow:
    def test_no_options_returns_none(self):
        assert build(["open"]) is None

    def test_no_options_and_no_field_returns_none(self):
        assert build_date_window(["open"], date_field=None, flag_names=None) is None

    def test_a_window_without_a_field_is_a_programming_error(self):
        with pytest.raises(ValueError, match="needs date_field and flag_names"):
            build_date_window(["open"], date_field=None, flag_names=None, since_days=3)

    def test_since_days_relative(self):
        window = build(["merged"], "merged", since_days=14, now=NOW)
        assert window is not None
        assert window.field == "merged"
        assert window.after.isoformat() == "2026-08-25"
        assert window.before is None

    def test_since_zero_days(self):
        window = build(["open"], since_days=0, now=NOW)
        assert window.after.isoformat() == "2026-09-08"

    def test_after_only(self):
        window = build(["open"], "created", after="2026-08-01")
        assert window.field == "created"
        assert window.after.isoformat() == "2026-08-01"
        assert window.before is None

    def test_before_only(self):
        window = build(["closed"], "closed", before="2026-08-31")
        assert window.field == "closed"
        assert window.before.isoformat() == "2026-08-31"
        assert window.after is None

    def test_after_and_before_interval(self):
        window = build(["open"], after="2026-08-01", before="2026-08-31")
        assert window.after.isoformat() == "2026-08-01"
        assert window.before.isoformat() == "2026-08-31"

    def test_the_field_is_the_one_given_whatever_the_states(self):
        window = build(["merged"], "created", since_days=30, now=NOW)
        assert window.field == "created"

    def test_the_states_never_pick_the_field(self):
        assert build(["merged"], "updated", since_days=3, now=NOW).field == "updated"
        assert build(["closed"], "updated", since_days=3, now=NOW).field == "updated"


class TestToQualifier:
    def test_after_only_qualifier(self):
        window = build(["merged"], "merged", since_days=14, now=NOW)
        assert window.to_qualifier() == "merged:>=2026-08-25"

    def test_before_only_qualifier(self):
        window = build(["closed"], "closed", before="2026-08-31")
        assert window.to_qualifier() == "closed:<=2026-08-31"

    def test_interval_qualifier(self):
        window = build(["open"], after="2026-08-01", before="2026-08-31")
        assert window.to_qualifier() == "updated:2026-08-01..2026-08-31"


class TestWindowWithRefs:
    def test_since_with_refs_names_the_typed_flag(self):
        with pytest.raises(DateWindowError, match=r"^--updated-since cannot narrow explicit refs"):
            build(["open"], since_days=7, refs=["o/r#1"])

    def test_bounds_with_refs_name_both_typed_flags(self):
        with pytest.raises(
            DateWindowError, match=r"^--created-after/--created-before cannot narrow"
        ):
            build(["open"], "created", after="2026-08-01", before="2026-08-31", refs=["o/r#1"])

    def test_refs_without_window_is_fine(self):
        assert build(["open"], refs=["o/r#1"]) is None

    def test_message_offers_both_ways_out(self):
        with pytest.raises(DateWindowError, match="Drop the refs to search by date, or drop"):
            build(["open"], since_days=7, refs=["o/r#1"])

    def test_message_never_names_a_removed_flag(self):
        with pytest.raises(DateWindowError) as err:
            build(["open"], "closed", since_days=7, refs=["o/r#1"])
        assert "--since" not in str(err.value).replace("--closed-since", "")


class TestFieldMustBeMatchable:
    @pytest.mark.parametrize("kind", ["since", "after", "before"])
    def test_merged_flag_names_itself_and_the_state_flags(self, kind):
        with pytest.raises(DateWindowError) as err:
            build(
                ["open"],
                "merged",
                since_days=7 if kind == "since" else None,
                after="2026-08-01" if kind == "after" else None,
                before="2026-08-01" if kind == "before" else None,
            )
        assert str(err.value) == (
            f"--merged-{kind} only matches merged items, but the state filter is open: "
            "add --merged (or --all)"
        )

    def test_no_states_means_open(self):
        with pytest.raises(DateWindowError, match="state filter is open"):
            build(None, "merged", since_days=7)

    def test_merged_flag_ok_with_merged_or_all(self):
        for states in (["merged"], ["open", "merged", "closed"]):
            window = build(states, "merged", since_days=7, now=NOW)
            assert window is not None and window.field == "merged"

    def test_closed_flag_on_prs_offers_merged_too(self):
        with pytest.raises(DateWindowError) as err:
            build(["open"], "closed", since_days=7)
        assert str(err.value) == (
            "--closed-since only matches closed items, but the state filter is open: "
            "add --closed, --merged or --all"
        )

    def test_closed_flag_on_issues_does_not_offer_merged(self):
        with pytest.raises(DateWindowError) as err:
            build(["open"], "closed", since_days=7, merged_ok=False)
        assert str(err.value).endswith("add --closed (or --all)")

    def test_closed_flag_without_all_flag_offers_neither_all(self):
        with pytest.raises(DateWindowError) as err:
            build(["open"], "closed", since_days=7, has_all_flag=False)
        assert str(err.value).endswith("add --closed (or --merged)")

    def test_merged_flag_without_all_flag_offers_no_all(self):
        with pytest.raises(DateWindowError) as err:
            build(["open"], "merged", since_days=7, has_all_flag=False)
        assert str(err.value).endswith("add --merged")

    @pytest.mark.parametrize("states", [["closed"], ["merged"]])
    def test_closed_flag_ok_with_closed_or_merged_state(self, states):
        window = build(states, "closed", since_days=7, now=NOW)
        assert window is not None
        assert window.to_qualifier() == "closed:>=2026-09-01"

    def test_issues_have_no_merged_date(self):
        with pytest.raises(DateWindowError, match=r"^--merged-since cannot apply to issues"):
            build(["open", "closed"], "merged", since_days=7, merged_ok=False)

    def test_created_and_updated_fit_any_state(self):
        for field in ("created", "updated"):
            assert build(["open"], field, since_days=7, now=NOW)


class TestDescribeAndSinceDays:
    def test_since_days_kept_as_typed(self):
        window = build(["merged"], "merged", since_days=14, now=NOW)
        assert window is not None
        assert window.since_days == 14 and str(window.after) == "2026-08-25"

    def test_absolute_window_has_no_since_days(self):
        window = build(["merged"], "merged", after="2026-08-01")
        assert window is not None and window.since_days is None

    def test_describe_after_only(self):
        window = build(["merged"], "merged", since_days=14, now=NOW)
        assert window is not None and window.describe() == "merged ≥ 2026-08-25"

    def test_describe_before_only(self):
        window = build(["closed"], "closed", before="2026-08-31")
        assert window is not None and window.describe() == "closed ≤ 2026-08-31"

    def test_describe_interval(self):
        window = build(["open"], after="2026-08-01", before="2026-08-31")
        assert window is not None and window.describe() == "updated 2026-08-01..2026-08-31"


class TestFlagNames:
    def test_field_flag_names(self):
        assert field_flag_names("merged") == {
            "since": "--merged-since",
            "after": "--merged-after",
            "before": "--merged-before",
        }

    def test_since_with_bound_names_typed_flags(self):
        with pytest.raises(DateWindowError) as err:
            build(["open"], "created", since_days=3, after="2026-08-01")
        assert str(err.value) == "--created-since cannot be combined with --created-after"

    def test_since_with_both_bounds_names_both(self):
        with pytest.raises(DateWindowError, match=r"--created-after/--created-before"):
            build(["open"], "created", since_days=3, after="2026-08-01", before="2026-08-02")

    def test_negative_since_names_typed_flag(self):
        with pytest.raises(DateWindowError, match=r"^--created-since must be a non-negative"):
            build(["open"], "created", since_days=-1, now=NOW)

    def test_invalid_date_names_typed_flag(self):
        with pytest.raises(DateWindowError, match=r"'2026-13-40' for --created-after"):
            build(["open"], "created", after="2026-13-40")
        with pytest.raises(DateWindowError, match=r"'nope' for --created-before"):
            build(["open"], "created", before="nope")

    def test_wrong_date_format_is_rejected(self):
        with pytest.raises(DateWindowError, match="expected YYYY-MM-DD format"):
            build(["open"], after="08/01/2026")

    def test_reversed_bounds_name_both_typed_flags(self):
        with pytest.raises(
            DateWindowError, match=r"--updated-after date must not be later than --updated-before"
        ):
            build(["open"], "updated", after="2026-09-01", before="2026-08-01")

    def test_same_day_bounds_are_allowed(self):
        window = build(["open"], after="2026-08-01", before="2026-08-01")
        assert window is not None
        assert window.to_qualifier() == "updated:2026-08-01..2026-08-01"

    def test_closed_field_with_open_state_names_typed_flag(self):
        with pytest.raises(DateWindowError, match=r"^--closed-since only matches closed items"):
            build(["open"], "closed", since_days=7)
        with pytest.raises(DateWindowError, match=r"^--closed-before only matches closed items"):
            build(None, "closed", before="2026-08-01")


class TestResolveFieldFlags:
    def test_no_flags_resolves_to_nothing(self):
        resolved = resolve_field_flags(ISSUE_DATE_FIELDS, {})
        assert resolved.date_field is None
        assert resolved.flag_names is None
        assert (resolved.since_days, resolved.after, resolved.before) == (None, None, None)

    def test_none_values_count_as_unset(self):
        values = {"created_since": None, "closed_after": None}
        resolved = resolve_field_flags(ISSUE_DATE_FIELDS, values)
        assert resolved.flag_names is None
        assert resolved.date_field is None

    @pytest.mark.parametrize("field", ISSUE_DATE_FIELDS)
    def test_since_maps_to_its_own_field(self, field):
        resolved = resolve_field_flags(ISSUE_DATE_FIELDS, {f"{field}_since": 5})
        assert resolved.date_field == field
        assert resolved.since_days == 5
        assert resolved.after is None
        assert resolved.before is None
        assert resolved.flag_names == field_flag_names(field)

    @pytest.mark.parametrize("field", ISSUE_DATE_FIELDS)
    def test_bounds_map_to_their_own_field(self, field):
        values = {f"{field}_after": "2026-08-01", f"{field}_before": "2026-08-31"}
        resolved = resolve_field_flags(ISSUE_DATE_FIELDS, values)
        assert resolved.date_field == field
        assert (resolved.after, resolved.before) == ("2026-08-01", "2026-08-31")
        assert resolved.since_days is None

    def test_since_zero_is_a_typed_flag(self):
        resolved = resolve_field_flags(ISSUE_DATE_FIELDS, {"created_since": 0})
        assert resolved.since_days == 0
        assert resolved.date_field == "created"

    def test_two_fields_name_one_flag_per_field(self):
        values = {"created_since": 14, "updated_since": 2}
        with pytest.raises(
            DateWindowError, match=r"--created-since and --updated-since .*one date field"
        ):
            resolve_field_flags(ISSUE_DATE_FIELDS, values)

    def test_two_fields_with_several_flags_still_name_one_each(self):
        values = {
            "created_after": "2026-08-01",
            "created_before": "2026-08-02",
            "closed_before": "2026-08-03",
        }
        with pytest.raises(DateWindowError) as err:
            resolve_field_flags(ISSUE_DATE_FIELDS, values)
        assert str(err.value).startswith("--created-after and --closed-before ")

    def test_fields_without_flags_are_ignored(self):
        resolved = resolve_field_flags(("created",), {"updated_since": 3})
        assert resolved.flag_names is None

    def test_resolved_flags_feed_build_date_window(self):
        resolved = resolve_field_flags(ISSUE_DATE_FIELDS, {"closed_since": 7})
        window = build_date_window(
            ["closed"],
            date_field=resolved.date_field,
            flag_names=resolved.flag_names,
            since_days=resolved.since_days,
            now=NOW,
        )
        assert window is not None and window.to_qualifier() == "closed:>=2026-09-01"
