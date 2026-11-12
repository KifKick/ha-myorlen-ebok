"""Config, re-authentication and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myorlen_ebok import models
from custom_components.myorlen_ebok.auth import Form, OrlenIdAuth
from custom_components.myorlen_ebok.const import (
    AUTH_ORLEN_ID,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_SESSION,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.myorlen_ebok.errors import (
    MyOrlenAuthError,
    MyOrlenConnectionError,
    MyOrlenMfaInvalid,
    MyOrlenMfaRequired,
)

from .conftest import load

FLOW = "custom_components.myorlen_ebok.config_flow"
USER = {CONF_AUTH_METHOD: AUTH_PASSWORD, "username": "user@example.com", "password": "secret"}


def _meters():
    return patch(
        f"{FLOW}.MyOrlenClient.async_get_meters",
        AsyncMock(return_value=models.parse_meters(load("ppg_list"))),
    )


def _no_setup():
    return patch("custom_components.myorlen_ebok.async_setup_entry", return_value=True)


async def test_password_login(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with (
        patch(f"{FLOW}.PasswordAuth.async_login", AsyncMock(return_value="T1")),
        _meters(),
        _no_setup(),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "myORLEN user@example.com"
    assert result["data"] == USER
    assert result["result"].unique_id == "user@example.com"


async def test_errors_then_success(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    for error, code in (
        (MyOrlenAuthError(), "invalid_auth"),
        (MyOrlenConnectionError(), "cannot_connect"),
    ):
        with patch(f"{FLOW}.PasswordAuth.async_login", AsyncMock(side_effect=error)):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
        assert result["errors"] == {"base": code}
    with (
        patch(f"{FLOW}.PasswordAuth.async_login", AsyncMock(return_value="T1")),
        _meters(),
        _no_setup(),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_no_meters(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(f"{FLOW}.PasswordAuth.async_login", AsyncMock(return_value="T1")),
        patch(f"{FLOW}.MyOrlenClient.async_get_meters", AsyncMock(return_value=[])),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_meters"


async def test_orlen_id_with_sms_code(hass: HomeAssistant) -> None:
    async def ask_for_code(self: OrlenIdAuth, *, interactive: bool = False) -> str:
        self._mfa = (Form("https://login.example/sms", {}), "code", "https://login.example")
        raise MyOrlenMfaRequired

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch.object(OrlenIdAuth, "async_login", ask_for_code):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER, CONF_AUTH_METHOD: AUTH_ORLEN_ID}
        )
    assert result["step_id"] == "mfa"

    with patch.object(OrlenIdAuth, "async_complete_mfa", AsyncMock(side_effect=MyOrlenMfaInvalid)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"mfa_code": "000000"}
        )
    assert result["errors"] == {"base": "mfa_invalid"}

    with (
        patch.object(OrlenIdAuth, "async_complete_mfa", AsyncMock(return_value="T1")),
        _meters(),
        _no_setup(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"mfa_code": "123 456"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AUTH_METHOD] == AUTH_ORLEN_ID
    assert CONF_SESSION in result["data"]


async def test_already_configured(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(f"{FLOW}.PasswordAuth.async_login", AsyncMock(return_value="T1")), _meters():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER, "username": "USER@example.com"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with (
        patch(f"{FLOW}.PasswordAuth.async_login", AsyncMock(return_value="T1")),
        _meters(),
        _no_setup(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new-secret"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "new-secret"


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    with _no_setup():
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_UPDATE_INTERVAL: 3}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_UPDATE_INTERVAL: 3}
