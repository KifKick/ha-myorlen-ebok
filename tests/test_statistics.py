"""Monthly usage statistic rows."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.myorlen_ebok.models import MonthlyUsage
from custom_components.myorlen_ebok.statistics import month_start, statistic_rows


def _month(day: datetime, reading: float) -> MonthlyUsage:
    return MonthlyUsage(reading_date=day, reading=reading, usage=0)


def test_month_start_is_the_closed_month() -> None:
    assert month_start(datetime(2026, 10, 31, tzinfo=UTC)) == datetime(2026, 10, 1, tzinfo=UTC)
    assert month_start(datetime(2026, 11, 1, tzinfo=UTC)) == datetime(2026, 10, 1, tzinfo=UTC)


def test_previous_meter_left_out() -> None:
    rows = statistic_rows(
        [
            _month(datetime(2025, 11, 30, tzinfo=UTC), 51.0),
            _month(datetime(2026, 8, 31, tzinfo=UTC), 50.0),
            _month(datetime(2026, 9, 30, tzinfo=UTC), 53.0),
        ]
    )
    assert [(r["start"].month, r["sum"]) for r in rows] == [(8, 50.0), (9, 53.0)]
