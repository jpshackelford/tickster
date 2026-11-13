"""Tests for the shared date-window filtering helpers."""

from datetime import UTC, datetime

import pytest

from src.date_window import (
    ISSUE_DATE_FIELDS,
    DateWindowError,
    build_date_window,
    field_flag,
    resolve_date_field,
    resolve_field_flags,
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

    @pytest.mark.parametrize("kind", ["since", "after", "before"])
    def test_typed_merged_flag_names_itself_and_the_state_flags(self, kind):
        names = _typed_names("merged")
        with pytest.raises(DateWindowError) as err:
            build_date_window(
                ["open"],
                since_days=7 if kind == "since" else None,
                after="2026-08-01" if kind == "after" else None,
                before="2026-08-01" if kind == "before" else None,
                date_field="merged",
                flag_names=names,
            )
        assert str(err.value) == (
            f"{names[kind]} only matches merged items, but the state filter is open: "
            "add --merged (or --all)"
        )

    def test_typed_merged_flag_ok_with_merged_or_all(self):
        names = _typed_names("merged")
        for states in (["merged"], ["open", "merged", "closed"]):
            window = build_date_window(
                states, since_days=7, date_field="merged", flag_names=names, now=NOW
            )
            assert window is not None and window.field == "merged"

    def test_typed_closed_flag_on_prs_offers_merged_too(self):
        with pytest.raises(DateWindowError) as err:
            build_date_window(
                ["open"], since_days=7, date_field="closed", flag_names=_typed_names("closed")
            )
        assert str(err.value) == (
            "--closed-since only matches closed items, but the state filter is open: "
            "add --closed, --merged or --all"
        )

    def test_typed_closed_flag_on_issues_does_not_offer_merged(self):
        with pytest.raises(DateWindowError) as err:
            build_date_window(
                ["open"],
                since_days=7,
                date_field="closed",
                merged_ok=False,
                flag_names=_typed_names("closed"),
            )
        assert str(err.value).endswith("add --closed (or --all)")

    def test_typed_closed_flag_ok_with_merged_state_on_prs(self):
        window = build_date_window(
            ["merged"],
            since_days=7,
            date_field="closed",
            flag_names=_typed_names("closed"),
            now=NOW,
        )
        assert window is not None and window.field == "closed"

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


def _typed_names(field: str) -> dict[str, str]:
    return {kind: field_flag(field, kind) for kind in ("since", "after", "before")}


class TestFlagNames:
    def test_old_messages_are_unchanged(self):
        with pytest.raises(DateWindowError) as since_after:
            build_date_window(["open"], since_days=7, after="2026-08-01")
        assert str(since_after.value) == "--since cannot be combined with --after/--before"
        with pytest.raises(DateWindowError) as negative:
            build_date_window(["open"], since_days=-1, now=NOW)
        assert str(negative.value) == "--since must be a non-negative number of days"
        with pytest.raises(DateWindowError) as reversed_bounds:
            build_date_window(["open"], after="2026-09-01", before="2026-08-01")
        assert str(reversed_bounds.value) == "--after date must not be later than --before date"
        with pytest.raises(DateWindowError) as bad_date:
            build_date_window(["open"], after="08/01/2026")
        assert str(bad_date.value) == "Invalid date '08/01/2026': expected YYYY-MM-DD format"

    def test_since_with_bound_names_typed_flags(self):
        with pytest.raises(DateWindowError) as err:
            build_date_window(
                ["open"],
                since_days=3,
                after="2026-08-01",
                date_field="created",
                flag_names=_typed_names("created"),
            )
        assert str(err.value) == "--created-since cannot be combined with --created-after"

    def test_since_with_both_bounds_names_both(self):
        with pytest.raises(DateWindowError, match=r"--created-after/--created-before"):
            build_date_window(
                ["open"],
                since_days=3,
                after="2026-08-01",
                before="2026-08-02",
                date_field="created",
                flag_names=_typed_names("created"),
            )

    def test_negative_since_names_typed_flag(self):
        with pytest.raises(DateWindowError, match=r"^--created-since must be a non-negative"):
            build_date_window(
                ["open"],
                since_days=-1,
                date_field="created",
                flag_names=_typed_names("created"),
            )

    def test_invalid_date_names_typed_flag(self):
        with pytest.raises(DateWindowError, match=r"'2026-13-40' for --created-after"):
            build_date_window(
                ["open"],
                after="2026-13-40",
                date_field="created",
                flag_names=_typed_names("created"),
            )
        with pytest.raises(DateWindowError, match=r"'nope' for --created-before"):
            build_date_window(
                ["open"],
                before="nope",
                date_field="created",
                flag_names=_typed_names("created"),
            )

    def test_reversed_bounds_name_both_typed_flags(self):
        with pytest.raises(
            DateWindowError, match=r"--updated-after date must not be later than --updated-before"
        ):
            build_date_window(
                ["open"],
                after="2026-09-01",
                before="2026-08-01",
                date_field="updated",
                flag_names=_typed_names("updated"),
            )

    def test_refs_error_names_only_typed_flags(self):
        with pytest.raises(DateWindowError, match=r"^--created-since cannot narrow explicit refs"):
            build_date_window(
                ["open"],
                since_days=14,
                date_field="created",
                refs=["o/r#1"],
                flag_names=_typed_names("created"),
            )

    def test_closed_field_with_open_state_names_typed_flag(self):
        with pytest.raises(DateWindowError, match=r"^--closed-since only matches closed items"):
            build_date_window(
                ["open"],
                since_days=7,
                date_field="closed",
                flag_names=_typed_names("closed"),
            )
        with pytest.raises(DateWindowError, match=r"^--closed-before only matches closed items"):
            build_date_window(
                None,
                before="2026-08-01",
                date_field="closed",
                flag_names=_typed_names("closed"),
            )

    def test_closed_field_with_closed_state_ok(self):
        window = build_date_window(
            ["closed"],
            since_days=7,
            date_field="closed",
            now=NOW,
            flag_names=_typed_names("closed"),
        )
        assert window is not None
        assert window.to_qualifier() == "closed:>=2026-09-01"


class TestResolveFieldFlags:
    def test_no_new_flags_returns_old_values_untouched(self):
        resolved = resolve_field_flags(
            ISSUE_DATE_FIELDS, {}, since_days=14, after="2026-08-01", date_field="created"
        )
        assert (resolved.since_days, resolved.after, resolved.before) == (14, "2026-08-01", None)
        assert resolved.date_field == "created"
        assert resolved.flag_names is None

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
        assert resolved.flag_names == _typed_names(field)

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

    def test_mixing_with_old_flag_names_both(self):
        with pytest.raises(
            DateWindowError, match=r"--created-since cannot be combined with --since"
        ):
            resolve_field_flags(ISSUE_DATE_FIELDS, {"created_since": 3}, since_days=3)

    @pytest.mark.parametrize(
        ("old", "flag"),
        [
            ({"after": "2026-08-01"}, "--after"),
            ({"before": "2026-08-01"}, "--before"),
            ({"date_field": "created"}, "--date-field"),
        ],
    )
    def test_mixing_with_each_old_flag(self, old, flag):
        with pytest.raises(DateWindowError, match=rf"--closed-after .*{flag}"):
            resolve_field_flags(ISSUE_DATE_FIELDS, {"closed_after": "2026-08-01"}, **old)

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
