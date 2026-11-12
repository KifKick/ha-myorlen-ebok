"""Setup with the fixture data: entities, calendar, services."""

from __future__ import annotations

from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myorlen_ebok.const import DOMAIN
from custom_components.myorlen_ebok.errors import MyOrlenAuthError, MyOrlenConnectionError

from .conftest import METER

PREFIX = "myorlen_1000001"


@pytest.fixture(autouse=True)
def _today(freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-12T12:00:00+01:00")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    def state(entity: str) -> str:
        return hass.states.get(entity).state

    assert state(f"sensor.{PREFIX}_odczyt") == "56.0"
    # Paid online, awaiting booking: nothing to pay, no due date.
    assert state(f"sensor.{PREFIX}_do_zaplaty") == "0.0"
    assert hass.states.get(f"sensor.{PREFIX}_do_zaplaty").attributes["awaiting_booking"] == 27.4
    assert state(f"sensor.{PREFIX}_termin_platnosci") == "unknown"
    last = hass.states.get(f"sensor.{PREFIX}_ostatnia_faktura")
    assert last.state == "27.4"
    assert last.attributes["state"] == "awaiting_booking"
    assert str(last.attributes["automatic_payment_date"]) == "2026-11-15"
    assert state(f"sensor.{PREFIX}_saldo") == "0.0"
    assert state(f"sensor.{PREFIX}_ostatnia_wplata") == "27.4"
    assert state(f"sensor.{PREFIX}_szacowany_rachunek") == "19.73"
    assert state(f"binary_sensor.{PREFIX}_zalegla_platnosc") == "off"
    assert hass.states.get(f"event.{PREFIX}_komunikaty") is not None
    assert hass.states.get(f"button.{PREFIX}_odswiez") is not None

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_calendar(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"start_date_time": "2026-10-01T00:00:00", "end_date_time": "2026-12-01T00:00:00"},
        target={"entity_id": f"calendar.{PREFIX}_faktury"},
        blocking=True,
        return_response=True,
    )
    events = {e["start"]: e for e in response[f"calendar.{PREFIX}_faktury"]["events"]}
    assert (
        events["2026-11-16"]["summary"] == "Orlen gaz: 27,40 zł zapłacone, czeka na zaksięgowanie"
    )
    assert "Płatność automatyczna: 15.11.2026" in events["2026-11-16"]["description"]
    assert "Zapłacono w eBOK: 10.11.2026" in events["2026-11-16"]["description"]
    assert events["2026-10-16"]["summary"] == "Orlen gaz: faktura 27,40 zł opłacona"


async def test_optional_failure_keeps_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.async_get_agreements.side_effect = MyOrlenConnectionError
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(f"sensor.{PREFIX}_saldo").state == "unknown"


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.async_get_meters.side_effect = MyOrlenAuthError
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_add_reading(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    await _setup(hass, config_entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, METER)})

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_reading", {"device_id": device.id, "value": 50}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_reading", {"device_id": device.id, "value": 900}, blocking=True
        )
    mock_client.async_add_reading.assert_not_called()

    mock_client.async_add_reading.return_value = MagicMock(
        value=57.0, added_at=None, can_be_cancelled=True
    )
    response = await hass.services.async_call(
        DOMAIN,
        "add_reading",
        {"device_id": device.id, "value": 57},
        blocking=True,
        return_response=True,
    )
    assert response == {"value": 57.0, "added_at": None, "can_be_cancelled": True}
    assert mock_client.async_add_reading.await_args.args[:2] == (METER, 57.0)
