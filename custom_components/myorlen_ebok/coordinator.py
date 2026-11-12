"""Data update coordinator for myORLEN eBOK."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MyOrlenClient
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .errors import MyOrlenAuthError, MyOrlenError
from .models import (
    Agreement,
    BillEstimate,
    Invoice,
    Meter,
    MonthlyUsage,
    Notice,
    Payment,
    PaymentState,
    Reading,
)
from .statistics import async_import_monthly_usage

_LOGGER = logging.getLogger(__name__)

type MyOrlenConfigEntry = ConfigEntry[MyOrlenCoordinator]


@dataclass(slots=True)
class MyOrlenData:
    """Everything fetched in one update."""

    meters: list[Meter]
    invoices: list[Invoice]
    readings: dict[str, list[Reading]] = field(default_factory=dict)
    agreements: list[Agreement] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    invoice_paid_at: dict[str, datetime] = field(default_factory=dict)
    automatic_payment: dict[str, date] = field(default_factory=dict)
    bill_estimates: dict[str, BillEstimate | None] = field(default_factory=dict)
    monthly_usage: dict[str, list[MonthlyUsage]] = field(default_factory=dict)

    def meter_invoices(self, meter: Meter) -> list[Invoice]:
        """The meter's invoices, credit notes excluded, newest first."""
        return [
            i for i in self.invoices if i.meter_id_local == meter.id_local and not i.is_credit_note
        ]

    def latest_reading(self, meter: Meter) -> Reading | None:
        readings = self.readings.get(meter.number)
        return readings[0] if readings else None

    def agreement(self, meter: Meter) -> Agreement | None:
        """The meter's agreement, an active one first."""
        matching = [a for a in self.agreements if a.meter_number == meter.number]
        return next((a for a in matching if a.active), matching[0] if matching else None)


class MyOrlenCoordinator(DataUpdateCoordinator[MyOrlenData]):
    """Polls eBOK; optional parts keep their last value when they fail."""

    config_entry: MyOrlenConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MyOrlenConfigEntry, client: MyOrlenClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                hours=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        self.client = client

    async def _async_update_data(self) -> MyOrlenData:
        try:
            data = MyOrlenData(
                meters=await self.client.async_get_meters(),
                invoices=await self.client.async_get_invoices(),
            )
            await self._fetch_optional(data)
        except MyOrlenAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MyOrlenError as err:
            raise UpdateFailed(str(err)) from err

        for meter, months in data.monthly_usage.items():
            async_import_monthly_usage(self.hass, meter, months)
        return data

    async def _optional[T](self, name: str, fetch: Callable[[], Awaitable[T]], previous: T) -> T:
        """Extra data: on failure keep what the last update had."""
        try:
            return await fetch()
        except MyOrlenAuthError:
            raise
        except MyOrlenError as err:
            _LOGGER.debug("Keeping previous %s: %s", name, err)
            return previous

    async def _fetch_optional(self, data: MyOrlenData) -> None:
        old = self.data
        client = self.client

        def prev(attr: str, empty: Any) -> Any:
            return getattr(old, attr) if old is not None else empty

        for meter in data.meters:
            data.readings[meter.number] = await self._optional(
                "readings",
                lambda m=meter.number: client.async_get_readings(m),
                prev("readings", {}).get(meter.number, []),
            )
            data.monthly_usage[meter.number] = await self._optional(
                "monthly usage",
                lambda m=meter.number: client.async_get_monthly_usage(m),
                prev("monthly_usage", {}).get(meter.number, []),
            )
            reading = data.latest_reading(meter)
            data.bill_estimates[meter.number] = (
                await self._optional(
                    "bill estimate",
                    lambda m=meter.number, v=reading.value: client.async_estimate_bill(m, v),
                    prev("bill_estimates", {}).get(meter.number),
                )
                if reading
                else None
            )

        data.agreements = await self._optional(
            "agreements", client.async_get_agreements, prev("agreements", [])
        )
        data.payments = await self._optional(
            "payments", client.async_get_payments, prev("payments", [])
        )
        data.notices = await self._optional(
            "notices", client.async_get_notices, prev("notices", [])
        )
        data.invoice_paid_at = await self._optional(
            "payment history",
            client.async_get_invoice_payment_dates,
            prev("invoice_paid_at", {}),
        )
        # One call per invoice not paid yet - usually none or one.
        for invoice in data.invoices:
            if invoice.state is PaymentState.PAID or invoice.is_credit_note:
                continue
            when = await self._optional(
                "automatic payment date",
                lambda n=invoice.number: client.async_get_automatic_payment_date(n),
                prev("automatic_payment", {}).get(invoice.number),
            )
            if when:
                data.automatic_payment[invoice.number] = when

    @property
    def today(self) -> date:
        return dt_util.now().date()
