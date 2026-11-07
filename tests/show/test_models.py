"""Tests for the show helpers: body trimming and time parsing."""

from datetime import UTC, datetime

import pytest

from src.show.models import parse_time, trim_body


class TestTrimBody:
    def test_short_body_is_unchanged(self):
        assert trim_body("hello", 600) == ("hello", 0)

    def test_body_at_the_limit_is_unchanged(self):
        assert trim_body("x" * 10, 10) == ("x" * 10, 0)

    def test_long_body_is_cut_and_counted(self):
        assert trim_body("x" * 15, 10) == ("x" * 10 + "…(5 more chars)", 5)

    def test_zero_means_no_limit(self):
        assert trim_body("x" * 5000, 0) == ("x" * 5000, 0)

    @pytest.mark.parametrize("body", [None, "", "  \n\t "])
    def test_empty_body_is_none(self, body):
        assert trim_body(body, 600) == (None, 0)

    def test_surrounding_whitespace_is_dropped_before_counting(self):
        assert trim_body("\n  abc  \n", 2) == ("ab…(1 more chars)", 1)


class TestParseTime:
    def test_z_suffix_is_utc(self):
        assert parse_time("2026-11-05T10:00:00Z") == datetime(2026, 11, 5, 10, tzinfo=UTC)

    def test_date_only_is_midnight_utc(self):
        assert parse_time("2026-11-05") == datetime(2026, 11, 5, tzinfo=UTC)

    def test_time_without_a_zone_is_utc(self):
        assert parse_time("2026-11-05T10:30:00") == datetime(2026, 11, 5, 10, 30, tzinfo=UTC)

    def test_offset_is_respected(self):
        assert parse_time("2026-11-05T12:00:00+02:00") == datetime(2026, 11, 5, 10, tzinfo=UTC)

    def test_garbage_is_an_error(self):
        with pytest.raises(ValueError, match="invalid time 'soon'"):
            parse_time("soon")
