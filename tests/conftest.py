"""Fixtures: anonymised eBOK responses and a mocked client."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myorlen_ebok import models
from custom_components.myorlen_ebok.const import AUTH_PASSWORD, CONF_AUTH_METHOD, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
METER = "8018000000000000000001"
ID_LOCAL = "1000001"


def load(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="myORLEN user@example.com",
        unique_id="user@example.com",
        data={
            CONF_AUTH_METHOD: AUTH_PASSWORD,
            "username": "user@example.com",
            "password": "secret",
        },
    )


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """MyOrlenClient answering with the fixtures (as seen on 12.11.2026)."""
    with patch("custom_components.myorlen_ebok.MyOrlenClient", autospec=True) as cls:
        client = cls.return_value
        client.async_get_meters.return_value = models.parse_meters(load("ppg_list"))
        client.async_get_invoices.return_value = models.parse_invoices(load("invoices"))
        client.async_get_readings.return_value = models.parse_readings(load("readings"))
        client.async_get_agreements.return_value = models.parse_agreements(load("agreements"))
        client.async_get_payments.return_value = models.parse_payments(load("payments"))
        client.async_get_notices.return_value = models.parse_notices(load("alerts"))
        client.async_get_invoice_payment_dates.return_value = models.parse_invoice_payment_dates(
            load("account_history")
        )
        client.async_get_automatic_payment_date.return_value = models.parse_automatic_payment_date(
            load("invoice_details")
        )
        client.async_estimate_bill.return_value = models.parse_bill_estimate(
            load("simulate_wear"), 57.0
        )
        client.async_get_monthly_usage.return_value = models.parse_monthly_usage(
            load("monthly_wear")
        )
        yield client
