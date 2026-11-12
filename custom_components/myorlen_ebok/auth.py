"""Login to eBOK: password (/auth/login) or OrlenID single sign-on.

Both end with an eBOK API token sent as the AuthToken header. OrlenID is a
Keycloak login reached through HTML forms; it may ask for an SMS code, and its
session lives in cookies, which are stored so a restart does not cost a code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import hashlib
from html import unescape
from http.cookies import SimpleCookie
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import aiohttp
from aiohttp.abc import AbstractCookieJar
from yarl import URL

from .const import API_VERSION, BASE_URL
from .errors import (
    MyOrlenAuthError,
    MyOrlenConnectionError,
    MyOrlenMfaExpired,
    MyOrlenMfaInvalid,
    MyOrlenMfaRequired,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=30)
DEVICE_COOKIE = "pgnig-ebok-device-token"
DEVICE_NAME = "Home Assistant"

BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Chromium";v="153", "Google Chrome";v="153", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
FORM_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
}

# Keycloak SMS authenticators name the field "code"; OTP forms "otp"/"totp".
MFA_FIELDS = ("code", "otp", "totp", "smsCode", "mfa_code", "verificationCode")
MFA_HINTS = ("otp", "totp", "sms", "kod", "weryfik", "uwierzyteln", "mfa", "jednoraz")
LOGIN_FIELDS = {"username", "password", "credentialId"}

FORM_RE = re.compile(r'<form\b[^>]*action="([^"]+)"[^>]*>(.*?)</form>', re.I | re.S)
INPUT_RE = re.compile(r'<input[^>]+name="([^"]+)"[^>]*>', re.I)
VALUE_RE = re.compile(r'value="([^"]*)"', re.I)
TYPE_RE = re.compile(r'type="([^"]+)"', re.I)


def device_id(username: str) -> str:
    """Stable device id per account.

    eBOK remembers a device by its cookie and only challenges an unknown one
    with an SMS code. Derived from the login, so it survives re-authentication
    and reinstalls; hashed so the login itself is not sent. The prefix must not
    change: a different id is a new device to eBOK.
    """
    return hashlib.sha256(f"pgnig-ebok:{username}".encode()).hexdigest()[:32]


# --- HTML forms (OrlenID / Keycloak) ---------------------------------------------


@dataclass(frozen=True, slots=True)
class Form:
    action: str
    fields: dict[str, str]


def parse_forms(html: str, base_url: str) -> list[Form]:
    """Forms with their inputs; submit buttons keep their value."""
    forms = []
    for match in FORM_RE.finditer(html):
        action = unescape(match.group(1))
        fields: dict[str, str] = {}
        for tag_match in INPUT_RE.finditer(match.group(2)):
            tag, name = tag_match.group(0), tag_match.group(1)
            value = VALUE_RE.search(tag)
            fields[name] = unescape(value.group(1)) if value else ""
        forms.append(Form(urljoin(base_url, action), fields))
    return forms


def find_mfa_form(html: str, base_url: str) -> tuple[Form, str] | None:
    """The SMS / OTP form and the name of its code field."""
    lowered = html.lower()
    if not any(hint in lowered for hint in MFA_HINTS):
        return None
    for form in parse_forms(html, base_url):
        for name in MFA_FIELDS:
            if name in form.fields:
                hidden = {
                    k: v for k, v in form.fields.items() if k not in LOGIN_FIELDS and k != name
                }
                return Form(form.action, hidden), name
    return None


def is_login_form(html: str) -> bool:
    """The username/password page (and not an MFA step)."""
    return (
        any(
            "username" in form.fields and "password" in form.fields
            for form in parse_forms(html, "")
        )
        and find_mfa_form(html, "") is None
    )


def is_keycloak_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        part in lowered
        for part in ("login-actions", "openid-connect", "orlenid", "keycloak", "/realms/")
    )


def is_ebok_home(url: str) -> bool:
    return url.startswith(f"{BASE_URL}/home")


def mfa_payload(form: Form, field: str, code: str) -> dict[str, str]:
    payload = {**form.fields, field: code}
    # Standard Keycloak OTP forms also expect their "login" submit input.
    if field in {"otp", "totp"} and "login" not in payload:
        payload["login"] = "Log In"
    return payload


# --- login methods -------------------------------------------------------------


@dataclass(slots=True)
class Page:
    """A fetched page: final URL after redirects and its body."""

    url: str
    status: int
    text: str


class EbokAuth(ABC):
    """Gets an eBOK API token for one account."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self.session = session
        self.username = username
        self.password = password
        self.device_id = device_id(username)
        self._set_device_cookie()

    def _set_device_cookie(self) -> None:
        self.session.cookie_jar.update_cookies({DEVICE_COOKIE: self.device_id}, URL(BASE_URL))

    async def _fetch(self, method: str, url: str, **kwargs: Any) -> Page:
        headers = {**BROWSER_HEADERS, **kwargs.pop("headers", {})}
        try:
            async with self.session.request(
                method, url, headers=headers, timeout=TIMEOUT, **kwargs
            ) as resp:
                return Page(str(resp.url), resp.status, await resp.text())
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MyOrlenConnectionError(f"{method} {URL(url).path}: {err}") from err

    @abstractmethod
    async def async_login(self, *, interactive: bool = False) -> str:
        """A fresh API token.

        interactive=False is the background case: an OrlenID login that would
        need an SMS code raises MyOrlenAuthError instead of starting one.
        """

    def export_session(self) -> dict[str, Any] | None:
        """State worth storing in the config entry, if any."""
        return None


class PasswordAuth(EbokAuth):
    """E-mail / customer number and password, eBOK's own login form."""

    async def async_login(self, *, interactive: bool = False) -> str:
        await self._fetch("GET", BASE_URL)  # session cookies
        page = await self._fetch(
            "POST",
            f"{BASE_URL}/auth/login?api-version={API_VERSION}",
            json={
                "identificator": self.username,
                "accessPin": self.password,
                "rememberLogin": False,
                "DeviceId": self.device_id,
                "DeviceName": DEVICE_NAME,
                "DeviceType": "Web",
            },
        )
        if page.status in (400, 401, 403):
            raise MyOrlenAuthError("eBOK rejected the login or password")
        if page.status != 200:
            raise MyOrlenConnectionError(f"Login failed with HTTP {page.status}")
        token = _json_token(page.text)
        if not token:
            raise MyOrlenAuthError("eBOK rejected the login or password")
        return token


class OrlenIdAuth(EbokAuth):
    """OrlenID (Keycloak) single sign-on, optionally with an SMS code."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        stored: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(session, username, password)
        if stored:
            restore_cookies(session.cookie_jar, stored.get("cookies") or [])
            self._set_device_cookie()
        self._mfa: tuple[Form, str, str] | None = None  # form, field, referer

    @property
    def mfa_pending(self) -> bool:
        """An SMS code was requested and not entered yet."""
        return self._mfa is not None

    def export_session(self) -> dict[str, Any]:
        return {"cookies": export_cookies(self.session.cookie_jar)}

    async def _api_token(self) -> str | None:
        """Token for the current OrlenID session, None when it has expired."""
        page = await self._fetch(
            "GET",
            f"{BASE_URL}/auth/get-auth-token?deviceId={self.device_id}&api-version={API_VERSION}",
            headers={"Referer": f"{BASE_URL}/home"},
        )
        return _json_token(page.text) if page.status == 200 else None

    async def _start_sso(self) -> Page:
        """eBOK's OIDC entry point; follows the redirect to OrlenID."""
        page = await self._fetch(
            "POST",
            f"{BASE_URL}/auth/oid/init-login?api-version={API_VERSION}",
            json={
                "DeviceId": self.device_id,
                "DeviceType": "Web",
                "DeviceName": DEVICE_NAME,
                "LightweightRedirectUrl": f"{BASE_URL}/?show=modal",
                "FinalizeRegistrationRedirectUrl": f"{BASE_URL}/aktywuj-oid/",
            },
        )
        redirect = _json_field(page.text, "RedirectUrl") if page.status == 200 else None
        if not redirect:
            raise MyOrlenConnectionError(f"OrlenID init-login failed with HTTP {page.status}")
        return await self._fetch("GET", redirect)

    async def async_login(self, *, interactive: bool = False) -> str:
        # 1. The stored session may still be valid.
        if token := await self._api_token():
            return token
        # 2. Silent SSO: OrlenID may still know us and redirect straight back.
        sso = await self._start_sso()
        if is_ebok_home(sso.url) and (token := await self._api_token()):
            return token
        if not interactive:
            raise MyOrlenAuthError("OrlenID session expired")
        # 3. Full login with the password, possibly followed by an SMS code.
        return await self._login_with_password(sso)

    async def _login_with_password(self, page: Page) -> str:
        form = next((f for f in parse_forms(page.text, page.url) if "password" in f.fields), None)
        if form is None:
            raise MyOrlenConnectionError("OrlenID login form not found")
        page = await self._fetch(
            "POST",
            form.action,
            data={"username": self.username, "password": self.password, "credentialId": ""},
            headers={**FORM_HEADERS, "Referer": page.url},
        )
        if "CANCEL_2FA" in page.text:
            # Offer to enrol in 2FA: skip it, as the website's "Pomiń" does.
            forms = parse_forms(page.text, page.url)
            if forms:
                page = await self._fetch(
                    "POST",
                    forms[0].action,
                    data={"CANCEL_2FA": "Pomiń"},
                    headers={**FORM_HEADERS, "Referer": page.url},
                )
        if mfa := find_mfa_form(page.text, page.url):
            self._mfa = (mfa[0], mfa[1], page.url)
            raise MyOrlenMfaRequired("OrlenID sent an SMS code")
        if is_keycloak_url(page.url):
            raise MyOrlenAuthError("OrlenID rejected the login or password")
        return await self._finish(page)

    async def async_complete_mfa(self, code: str) -> str:
        """Submit the SMS code of the login async_login(interactive=True) started."""
        if self._mfa is None:
            raise MyOrlenMfaExpired("No SMS code was requested")
        digits = re.sub(r"\D", "", code)
        if not digits:
            raise MyOrlenMfaInvalid("Empty code")
        form, field, referer = self._mfa
        page = await self._fetch(
            "POST",
            form.action,
            data=mfa_payload(form, field, digits),
            headers={**FORM_HEADERS, "Referer": referer},
        )
        if mfa := find_mfa_form(page.text, page.url):
            self._mfa = (mfa[0], mfa[1], page.url)
            raise MyOrlenMfaInvalid("Wrong SMS code")
        self._mfa = None
        if is_keycloak_url(page.url) and is_login_form(page.text):
            raise MyOrlenMfaExpired("The SMS step expired")
        return await self._finish(page)

    async def _finish(self, page: Page) -> str:
        """After OrlenID: land on eBOK and fetch the API token."""
        if not is_ebok_home(page.url):
            page = await self._fetch("GET", f"{BASE_URL}/home", headers={"Referer": page.url})
        if is_keycloak_url(page.url):
            raise MyOrlenAuthError("OrlenID did not complete the login")
        if token := await self._api_token():
            return token
        raise MyOrlenAuthError("eBOK gave no token after OrlenID login")


# --- helpers ---------------------------------------------------------------------


def _json_field(text: str, field: str) -> Any:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data.get(field) if isinstance(data, dict) else None


def _json_token(text: str) -> str | None:
    token = _json_field(text, "Token")
    return token if isinstance(token, str) and token else None


def export_cookies(jar: AbstractCookieJar) -> list[dict[str, str]]:
    """Cookies with their domain and path, for the config entry."""
    return [
        {
            "name": morsel.key,
            "value": morsel.value,
            "domain": morsel["domain"],
            "path": morsel["path"] or "/",
        }
        for morsel in jar
        if morsel.key != DEVICE_COOKIE and morsel["domain"]
    ]


def restore_cookies(jar: AbstractCookieJar, cookies: list[dict[str, str]]) -> None:
    for cookie in cookies:
        try:
            name, domain = cookie["name"], cookie["domain"].lstrip(".")
        except (KeyError, TypeError, AttributeError):
            continue
        morsel = SimpleCookie()
        morsel[name] = cookie.get("value", "")
        morsel[name]["domain"] = cookie["domain"]
        morsel[name]["path"] = cookie.get("path") or "/"
        jar.update_cookies(morsel, URL(f"https://{domain}/"))
