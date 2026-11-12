"""Diagnostics: the last update, without credentials or personal data."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_SESSION
from .coordinator import MyOrlenConfigEntry

# Invoice numbers carry the customer number; meter and agreement numbers identify
# the address.
TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SESSION,
    "agreement_number",
    "bank_account",
    "document",
    "meter_number",
    "number",
}

# Mappings keyed by a meter or invoice number.
KEYED = ("readings", "invoice_paid_at", "automatic_payment", "bill_estimates", "monthly_usage")


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MyOrlenConfigEntry
) -> dict[str, Any]:
    data = asdict(entry.runtime_data.data)
    for key in KEYED:
        data[key] = list(data[key].values())
    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT
        ),
        "data": async_redact_data(data, TO_REDACT),
    }
