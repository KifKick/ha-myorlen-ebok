"""API client: token handling and error mapping."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import aiohttp
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import pytest

from custom_components.myorlen_ebok.api import MyOrlenClient
from custom_components.myorlen_ebok.auth import PasswordAuth
from custom_components.myorlen_ebok.const import BASE_URL
from custom_components.myorlen_ebok.errors import (
    MyOrlenAuthError,
    MyOrlenConnectionError,
    MyOrlenReadingRejected,
)

from .conftest import load


def _client(hass, tokens: list[str]) -> tuple[MyOrlenClient, AsyncMock]:
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    login = PasswordAuth(session, "user@example.com", "secret")
    login.async_login = AsyncMock(side_effect=tokens)
    return MyOrlenClient(login), login.async_login


async def test_token_sent_and_reused(hass, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE_URL}/crm/get-invoices-v2", json=load("invoices"))
    client, login = _client(hass, ["T1"])
    assert len(await client.async_get_invoices()) == 6
    assert len(await client.async_get_invoices()) == 6
    assert login.await_count == 1
    assert aioclient_mock.mock_calls[0][3]["AuthToken"] == "T1"


async def test_relogin_after_401(hass, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE_URL}/crm/get-ppg-list", status=401)
    client, login = _client(hass, ["OLD", "NEW"])
    with pytest.raises(MyOrlenAuthError):
        await client.async_get_meters()
    assert login.await_count == 2


async def test_http_error(hass, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE_URL}/crm/get-agreements", status=500)
    client, _ = _client(hass, ["T1"])
    with pytest.raises(MyOrlenConnectionError):
        await client.async_get_agreements()


async def test_add_reading(hass, aioclient_mock) -> None:
    aioclient_mock.post(
        f"{BASE_URL}/crm/add-ppg-reading-v2",
        json={"Code": 0, "Reading": {"Value": 57.0, "CanBeCancelled": True}},
    )
    client, _ = _client(hass, ["T1"])
    result = await client.async_add_reading("M1", 57.0, date(2026, 11, 12))
    assert result.value == 57.0
    payload = aioclient_mock.mock_calls[0][2]
    assert payload["OsdNumber"] == "M1"
    assert payload["DateReading"] == "2026-11-12"
    assert payload["ConsentMeterReset"] is False


async def test_add_reading_rejected(hass, aioclient_mock) -> None:
    aioclient_mock.post(f"{BASE_URL}/crm/add-ppg-reading-v2", json={"Code": 1032})
    client, _ = _client(hass, ["T1"])
    with pytest.raises(MyOrlenReadingRejected) as err:
        await client.async_add_reading("M1", 57.0, date(2026, 11, 12))
    assert err.value.code == 1032
