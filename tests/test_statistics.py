"""Monthly usage statistic rows."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.util import dt as dt_util

from custom_components.myorlen_ebok.models import MonthlyUsage
from custom_components.myorlen_ebok.statistics import month_start, statistic_rows


def _month(day: datetime, reading: float) -> MonthlyUsage:
    return MonthlyUsage(reading_date=day, reading=reading, usage=0)


def test_month_start_is_the_closed_month() -> None:
    tz = dt_util.get_default_time_zone()
    october = dt_util.as_utc(datetime(2026, 10, 1, tzinfo=tz))
    # The last day of the month, and midnight on the 1st (closes the previous month).
    assert month_start(datetime(2026, 10, 31, 12, tzinfo=tz)) == october
    assert month_start(datetime(2026, 11, 1, tzinfo=tz)) == october


def test_previous_meter_left_out() -> None:
    rows = statistic_rows(
        [
            _month(datetime(2025, 11, 30, tzinfo=UTC), 51.0),
            _month(datetime(2026, 8, 31, tzinfo=UTC), 50.0),
            _month(datetime(2026, 9, 30, tzinfo=UTC), 53.0),
        ]
    )
    assert [(r["start"].month, r["sum"]) for r in rows] == [(8, 50.0), (9, 53.0)]
