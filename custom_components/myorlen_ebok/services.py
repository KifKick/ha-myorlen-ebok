"""Services: submit a meter reading, refresh now."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    ATTR_CONFIRM_LARGE_INCREASE,
    ATTR_DATE,
    ATTR_DEVICE_ID,
    ATTR_METER_RESET,
    ATTR_VALUE,
    DOMAIN,
    MAX_READING_INCREASE_M3,
    SERVICE_ADD_READING,
    SERVICE_REFRESH,
)
from .coordinator import MyOrlenConfigEntry, MyOrlenCoordinator
from .errors import MyOrlenAuthError, MyOrlenError, MyOrlenReadingRejected
from .models import Meter

ADD_READING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_VALUE): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_METER_RESET, default=False): cv.boolean,
        vol.Optional(ATTR_CONFIRM_LARGE_INCREASE, default=False): cv.boolean,
    }
)


def _meter_of(hass: HomeAssistant, device_id: str) -> tuple[MyOrlenCoordinator, Meter]:
    device = dr.async_get(hass).async_get(device_id)
    number = (
        next((ident for domain, ident in device.identifiers if domain == DOMAIN), None)
        if device
        else None
    )
    if device is None or number is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_a_meter")
    for entry_id in device.config_entries:
        entry: MyOrlenConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
            coordinator = entry.runtime_data
            meter = next((m for m in coordinator.data.meters if m.number == number), None)
            if meter:
                return coordinator, meter
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


def _check_plausible(
    coordinator: MyOrlenCoordinator, meter: Meter, value: float, call: ServiceCall
) -> None:
    """Refuse a reading that cannot be right: Orlen bills from the value sent."""
    last = coordinator.data.latest_reading(meter)
    if last is None:
        return
    if value < last.value and not call.data[ATTR_METER_RESET]:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="reading_lower",
            translation_placeholders={"value": f"{value:g}", "last": f"{last.value:g}"},
        )
    if value - last.value > MAX_READING_INCREASE_M3 and not call.data[ATTR_CONFIRM_LARGE_INCREASE]:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="reading_too_high",
            translation_placeholders={
                "value": f"{value:g}",
                "last": f"{last.value:g}",
                "limit": str(MAX_READING_INCREASE_M3),
            },
        )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def add_reading(call: ServiceCall) -> dict[str, Any]:
        coordinator, meter = _meter_of(hass, call.data[ATTR_DEVICE_ID])
        value = call.data[ATTR_VALUE]
        _check_plausible(coordinator, meter, value, call)
        try:
            result = await coordinator.client.async_add_reading(
                meter.number,
                value,
                call.data.get(ATTR_DATE) or dt_util.now().date(),
                meter_reset=call.data[ATTR_METER_RESET],
            )
        except MyOrlenReadingRejected as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="reading_rejected",
                translation_placeholders={"message": str(err)},
            ) from err
        except MyOrlenAuthError as err:
            coordinator.config_entry.async_start_reauth(hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except MyOrlenError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="request_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await coordinator.async_request_refresh()
        return {
            "value": result.value,
            "added_at": result.added_at.isoformat() if result.added_at else None,
            "can_be_cancelled": result.can_be_cancelled,
        }

    async def refresh(call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_READING,
        add_reading,
        schema=ADD_READING_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=vol.Schema({}))
