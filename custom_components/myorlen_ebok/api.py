"""eBOK API client (https://ebok.myorlen.pl)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
import logging
from typing import Any

import aiohttp
from yarl import URL

from .auth import BROWSER_HEADERS, TIMEOUT, EbokAuth
from .const import API_VERSION, BASE_URL
from .errors import MyOrlenAuthError, MyOrlenConnectionError, MyOrlenReadingRejected
from .models import (
    READING_ERRORS,
    Agreement,
    BillEstimate,
    Invoice,
    Meter,
    MonthlyUsage,
    Notice,
    Payment,
    Reading,
    ReadingResult,
    parse_agreements,
    parse_automatic_payment_date,
    parse_bill_estimate,
    parse_invoice_payment_dates,
    parse_invoices,
    parse_meters,
    parse_monthly_usage,
    parse_notices,
    parse_payments,
    parse_reading_result,
    parse_readings,
)

_LOGGER = logging.getLogger(__name__)

# Screen whose notices are shown; 23 is the eBOK dashboard.
NOTICES_PAGE = 23


class MyOrlenClient:
    """Calls the eBOK API with a token from the account's login method.

    The token is fetched on first use and again after a 401; a login that
    would need the user (OrlenID SMS code) surfaces as MyOrlenAuthError.
    """

    def __init__(self, auth: EbokAuth, token: str | None = None) -> None:
        self.auth = auth
        self._token = token
        self._lock = asyncio.Lock()

    @property
    def session(self) -> aiohttp.ClientSession:
        return self.auth.session

    async def async_login(self, *, interactive: bool = False) -> None:
        """Get a fresh token now (setup, re-authentication, keep-alive)."""
        async with self._lock:
            self._token = await self.auth.async_login(interactive=interactive)

    async def _token_for(self, rejected: str | None) -> str:
        async with self._lock:
            if self._token is None or self._token == rejected:
                self._token = await self.auth.async_login()
            return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = URL(BASE_URL + path).with_query({**(params or {}), "api-version": API_VERSION})
        rejected: str | None = None
        for _attempt in range(2):
            token = await self._token_for(rejected)
            try:
                async with self.session.request(
                    method,
                    url,
                    json=json,
                    headers={**BROWSER_HEADERS, "AuthToken": token},
                    timeout=TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        rejected = token
                        continue
                    if resp.status != 200:
                        raise MyOrlenConnectionError(f"{path}: HTTP {resp.status}")
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise MyOrlenConnectionError(f"{path}: {err}") from err
        raise MyOrlenAuthError(f"{path}: token rejected after a fresh login")

    # --- reads -----------------------------------------------------------------

    async def async_get_meters(self) -> list[Meter]:
        return parse_meters(await self._request("GET", "/crm/get-ppg-list"))

    async def async_get_readings(self, meter: str) -> list[Reading]:
        return parse_readings(
            await self._request(
                "GET",
                "/crm/get-all-ppg-readings-for-meter",
                params={"idPpg": meter, "pageNumber": 1, "pageSize": 10},
            )
        )

    async def async_get_invoices(self) -> list[Invoice]:
        return parse_invoices(
            await self._request(
                "GET", "/crm/get-invoices-v2", params={"pageNumber": 1, "pageSize": 12}
            )
        )

    async def async_get_automatic_payment_date(self, invoice: str) -> date | None:
        return parse_automatic_payment_date(
            await self._request(
                "GET",
                "/crm/get-invoice-details",
                params={"invoiceNumber": invoice, "excludePdfCheck": "true"},
            )
        )

    async def async_get_agreements(self) -> list[Agreement]:
        return parse_agreements(await self._request("GET", "/crm/get-agreements"))

    async def async_get_payments(self) -> list[Payment]:
        return parse_payments(await self._request("GET", "/crm/get-client-payments"))

    async def async_get_invoice_payment_dates(self) -> dict[str, datetime]:
        return parse_invoice_payment_dates(
            await self._request(
                "GET", "/crm/get-account-history", params={"pageNumber": 1, "pageSize": 20}
            )
        )

    async def async_get_notices(self) -> list[Notice]:
        return parse_notices(
            await self._request("GET", "/cms/get-alert-list", params={"page": NOTICES_PAGE})
        )

    async def async_estimate_bill(self, meter: str, reading: float) -> BillEstimate | None:
        """eBOK's bill calculator; computes only, nothing is submitted."""
        return parse_bill_estimate(
            await self._request(
                "POST",
                "/crm/simulate-wear",
                json={
                    "Value": f"{reading:g}",
                    "Date": datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "PpId": meter,
                },
            ),
            reading,
        )

    async def async_get_monthly_usage(self, meter: str) -> list[MonthlyUsage]:
        return parse_monthly_usage(
            await self._request(
                "GET",
                "/crm/get-monthly-wear-chart-data",
                params={
                    "ppgIds": meter,
                    "hasReachedEnd": "false",
                    "pageNumber": 1,
                    "pageSize": 14,
                    "totalEntries": 0,
                },
            )
        )

    # --- writes ----------------------------------------------------------------

    async def async_add_reading(
        self, meter: str, value: float, when: date, *, meter_reset: bool = False
    ) -> ReadingResult:
        """Submit a meter reading. Billable: Orlen invoices from this value."""
        data = await self._request(
            "POST",
            "/crm/add-ppg-reading-v2",
            json={
                "DateReading": when.isoformat(),
                "OsdNumber": meter,
                "Value": value,
                "ConsentMeterReset": meter_reset,
                "UseDate": True,
                "SourceFromWWW": True,
            },
        )
        code = data.get("Code") if isinstance(data, dict) else None
        if code != 0:
            code = code if isinstance(code, int) else -1
            raise MyOrlenReadingRejected(
                code, READING_ERRORS.get(code, f"eBOK odrzucił odczyt (kod {code})")
            )
        _LOGGER.info("Reading %s accepted for meter %s", value, meter)
        return parse_reading_result(data)
