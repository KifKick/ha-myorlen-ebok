"""myORLEN eBOK - gas meter, invoices and payments from ebok.myorlen.pl."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .api import MyOrlenClient
from .auth import OrlenIdAuth
from .config_flow import create_auth
from .const import CONF_AUTH_METHOD, CONF_SESSION, DOMAIN, ORLEN_ID_KEEPALIVE
from .coordinator import MyOrlenConfigEntry, MyOrlenCoordinator
from .errors import MyOrlenAuthError, MyOrlenError
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MyOrlenConfigEntry) -> bool:
    auth = create_auth(
        hass,
        entry.data[CONF_AUTH_METHOD],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_SESSION),
    )
    coordinator = MyOrlenCoordinator(hass, entry, MyOrlenClient(auth))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    if isinstance(auth, OrlenIdAuth):
        _store_session(hass, entry, auth)
        entry.async_on_unload(_keep_orlen_id_alive(hass, entry, coordinator, auth))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MyOrlenConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _store_session(hass: HomeAssistant, entry: MyOrlenConfigEntry, auth: OrlenIdAuth) -> None:
    """Keep the OrlenID cookies, so a restart does not cost an SMS code."""
    session = auth.export_session()
    if session != entry.data.get(CONF_SESSION):
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_SESSION: session})


@callback
def _keep_orlen_id_alive(
    hass: HomeAssistant,
    entry: MyOrlenConfigEntry,
    coordinator: MyOrlenCoordinator,
    auth: OrlenIdAuth,
):
    """Touch the OrlenID session before eBOK drops it as idle.

    A failure is left to the next update: a session that really expired makes
    it raise ConfigEntryAuthFailed, which starts re-authentication.
    """

    async def _keepalive(_now: datetime) -> None:
        try:
            await coordinator.client.async_login()
        except MyOrlenAuthError as err:
            _LOGGER.debug("OrlenID keep-alive: session expired (%s)", err)
            return
        except MyOrlenError as err:
            _LOGGER.debug("OrlenID keep-alive failed: %s", err)
            return
        _store_session(hass, entry, auth)

    return async_track_time_interval(
        hass, _keepalive, ORLEN_ID_KEEPALIVE, name="myORLEN OrlenID keep-alive"
    )
