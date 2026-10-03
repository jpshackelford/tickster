"""Live-model -> ItemSnapshot conversion tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.snapshot.convert import _iso_utc


def test_iso_utc_rejects_naive_datetime():
    with pytest.raises(ValueError, match="aware datetime"):
        _iso_utc(datetime(2026, 1, 2, 3, 4, 5))  # naive


def test_iso_utc_normalizes_aware_datetime_to_z():
    from datetime import UTC, timedelta, timezone

    plus5 = timezone(timedelta(hours=5))
    assert _iso_utc(datetime(2026, 1, 2, 10, 0, 0, tzinfo=plus5)) == "2026-01-02T05:00:00Z"
    assert _iso_utc(datetime(2026, 1, 2, 5, 0, 0, tzinfo=UTC)) == "2026-01-02T05:00:00Z"
