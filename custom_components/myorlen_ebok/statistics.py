"""Monthly gas consumption as a long-term statistic.

eBOK reports consumption per month, each month closed by a meter reading. The
statistic's sum is that reading rather than a running total of the months: the
API returns only the last 14 months, and a running total would restart from a
different month whenever the window moves.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
import logging

from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .models import MonthlyUsage

_LOGGER = logging.getLogger(__name__)


def statistic_id(meter: str) -> str:
    return f"{DOMAIN}:monthly_usage_{meter}".lower()


def month_start(reading_date: datetime) -> datetime:
    """Local start of the month a reading closes, as hour-aligned UTC."""
    local = dt_util.as_local(reading_date)
    if local.day == 1 and local.hour == 0:
        # A reading at midnight on the 1st closes the previous month.
        local -= timedelta(minutes=1)
    return dt_util.as_utc(local.replace(day=1, hour=0, minute=0, second=0, microsecond=0))


def current_meter_months(months: Sequence[MonthlyUsage]) -> list[MonthlyUsage]:
    """Months since the reading last went down (a new meter or agreement).

    With the reading as the sum, months of a previous meter would show up as
    negative consumption.
    """
    ordered = sorted(months, key=lambda m: m.reading_date)
    start = 0
    for index in range(1, len(ordered)):
        if ordered[index].reading < ordered[index - 1].reading:
            start = index
    return ordered[start:]


def statistic_rows(months: Sequence[MonthlyUsage]) -> list[dict]:
    """One row per month; the latest reading of a month wins."""
    rows: dict[datetime, dict] = {}
    for month in current_meter_months(months):
        start = month_start(month.reading_date)
        rows[start] = {"start": start, "state": month.reading, "sum": month.reading}
    return list(rows.values())


@callback
def async_import_monthly_usage(
    hass: HomeAssistant, meter: str, months: Sequence[MonthlyUsage]
) -> None:
    """Upsert the months; nothing without the recorder or data."""
    if not months or "recorder" not in hass.config.components:
        return
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    metadata = {
        "has_sum": True,
        "mean_type": StatisticMeanType.NONE,
        "name": f"myORLEN {meter} - zużycie miesięczne",
        "source": DOMAIN,
        "statistic_id": statistic_id(meter),
        "unit_class": "volume",
        "unit_of_measurement": UnitOfVolume.CUBIC_METERS,
    }
    try:
        async_add_external_statistics(hass, metadata, statistic_rows(months))
    except Exception as err:
        _LOGGER.warning("Could not import monthly usage of %s: %s", meter, err)
