"""Config flow for myORLEN eBOK."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import MyOrlenClient
from .auth import EbokAuth, OrlenIdAuth, PasswordAuth
from .const import (
    AUTH_ORLEN_ID,
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_MFA_CODE,
    CONF_SESSION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)
from .errors import (
    MyOrlenAuthError,
    MyOrlenError,
    MyOrlenMfaExpired,
    MyOrlenMfaInvalid,
    MyOrlenMfaRequired,
)

_LOGGER = logging.getLogger(__name__)

METHOD_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[AUTH_PASSWORD, AUTH_ORLEN_ID],
        translation_key=CONF_AUTH_METHOD,
        mode=SelectSelectorMode.LIST,
    )
)
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def create_auth(
    hass: HomeAssistant,
    method: str,
    username: str,
    password: str,
    stored: Mapping[str, Any] | None = None,
) -> EbokAuth:
    """Login method with its own cookie jar (OrlenID lives in cookies).

    HA closes the session on shutdown; closing it ourselves is not allowed.
    """
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    if method == AUTH_ORLEN_ID:
        return OrlenIdAuth(session, username, password, dict(stored or {}))
    return PasswordAuth(session, username, password)


def entry_data(auth: EbokAuth, method: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        CONF_AUTH_METHOD: method,
        CONF_USERNAME: auth.username,
        CONF_PASSWORD: auth.password,
    }
    if session := auth.export_session():
        data[CONF_SESSION] = session
    return data


class MyOrlenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in (with an SMS code for OrlenID when asked) and find the meters."""

    VERSION = 1

    def __init__(self) -> None:
        self._auth: EbokAuth | None = None
        self._token: str | None = None
        self._method = AUTH_PASSWORD
        self._step = "user"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MyOrlenOptionsFlow:
        return MyOrlenOptionsFlow()

    # --- login ---------------------------------------------------------------

    async def _login(
        self, method: str, username: str, password: str, stored: Mapping[str, Any] | None
    ) -> dict[str, str] | None:
        """Log in; errors for the form, None when done or an SMS code is needed."""
        self._method = method
        self._auth = create_auth(self.hass, method, username.strip(), password, stored)
        try:
            self._token = await self._auth.async_login(interactive=True)
        except MyOrlenMfaRequired:
            return None
        except MyOrlenAuthError:
            return {"base": "invalid_auth"}
        except MyOrlenError:
            _LOGGER.debug("eBOK login failed", exc_info=True)
            return {"base": "cannot_connect"}
        return None

    @property
    def _needs_mfa(self) -> bool:
        return isinstance(self._auth, OrlenIdAuth) and self._auth.mfa_pending

    async def _finish(self) -> ConfigFlowResult:
        """Logged in: check the account has a meter, then create or update the entry."""
        assert self._auth is not None
        client = MyOrlenClient(self._auth, self._token)
        try:
            meters = await client.async_get_meters()
        except MyOrlenAuthError:
            return self._show_credentials({"base": "invalid_auth"})
        except MyOrlenError:
            return self._show_credentials({"base": "cannot_connect"})
        if not meters:
            return self.async_abort(reason="no_meters")

        data = entry_data(self._auth, self._method)
        await self.async_set_unique_id(self._auth.username.casefold())
        if self._step == "reauth_confirm":
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        if self._step == "reconfigure":
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=f"myORLEN {self._auth.username}", data=data)

    async def _credentials_step(
        self, step: str, user_input: dict[str, Any] | None, stored: Mapping[str, Any] | None
    ) -> ConfigFlowResult:
        self._step = step
        if user_input is None:
            return self._show_credentials({})
        method = user_input.get(CONF_AUTH_METHOD, self._method)
        errors = await self._login(
            method, user_input[CONF_USERNAME], user_input[CONF_PASSWORD], stored
        )
        if errors:
            return self._show_credentials(errors, user_input)
        if self._needs_mfa:
            return await self.async_step_mfa()
        return await self._finish()

    def _show_credentials(
        self, errors: dict[str, str], user_input: Mapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        defaults = dict(user_input or {})
        if self._step == "reauth_confirm":
            entry = self._get_reauth_entry()
            defaults.setdefault(CONF_USERNAME, entry.data[CONF_USERNAME])
        elif self._step == "reconfigure":
            entry = self._get_reconfigure_entry()
            defaults.setdefault(CONF_USERNAME, entry.data[CONF_USERNAME])
            defaults.setdefault(CONF_AUTH_METHOD, entry.data[CONF_AUTH_METHOD])
        schema: dict[Any, Any] = {}
        if self._step != "reauth_confirm":
            schema[
                vol.Required(
                    CONF_AUTH_METHOD, default=defaults.get(CONF_AUTH_METHOD, AUTH_PASSWORD)
                )
            ] = METHOD_SELECTOR
        if self._step != "reauth_confirm":
            schema[vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, ""))] = str
        schema[vol.Required(CONF_PASSWORD)] = PASSWORD_SELECTOR
        return self.async_show_form(
            step_id=self._step, data_schema=vol.Schema(schema), errors=errors
        )

    # --- steps ---------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._credentials_step("user", user_input, None)

    async def async_step_mfa(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The SMS code OrlenID sent."""
        errors: dict[str, str] = {}
        if user_input is not None and isinstance(self._auth, OrlenIdAuth):
            try:
                self._token = await self._auth.async_complete_mfa(user_input[CONF_MFA_CODE])
            except MyOrlenMfaInvalid:
                errors["base"] = "mfa_invalid"
            except MyOrlenMfaExpired:
                return self._show_credentials({"base": "mfa_expired"})
            except MyOrlenAuthError:
                return self._show_credentials({"base": "invalid_auth"})
            except MyOrlenError:
                errors["base"] = "cannot_connect"
            else:
                return await self._finish()
        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({vol.Required(CONF_MFA_CODE): str}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._method = entry_data[CONF_AUTH_METHOD]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in again; OrlenID reuses the stored session (no new SMS if it is valid)."""
        entry = self._get_reauth_entry()
        if user_input is not None:
            user_input = {**user_input, CONF_USERNAME: entry.data[CONF_USERNAME]}
        return await self._credentials_step(
            "reauth_confirm", user_input, entry.data.get(CONF_SESSION)
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        self._method = entry.data[CONF_AUTH_METHOD]
        return await self._credentials_step("reconfigure", user_input, entry.data.get(CONF_SESSION))


class MyOrlenOptionsFlow(OptionsFlowWithReload):
    """Update interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                            unit_of_measurement="h",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    )
                }
            ),
        )
