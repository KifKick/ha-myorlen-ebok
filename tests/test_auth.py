"""Login helpers and the password login."""

from __future__ import annotations

import aiohttp
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import pytest
from yarl import URL

from custom_components.myorlen_ebok import auth
from custom_components.myorlen_ebok.auth import PasswordAuth
from custom_components.myorlen_ebok.const import BASE_URL
from custom_components.myorlen_ebok.errors import MyOrlenAuthError

LOGIN_PAGE = """
<form id="kc-form-login" action="/realms/orlen/login-actions/authenticate?code=a&amp;x=1" method="post">
  <input name="username" type="text"><input name="password" type="password">
  <input name="credentialId" type="hidden" value="">
</form>"""

SMS_PAGE = """
<p>Wpisz kod SMS</p>
<form action="https://login.example/login-actions/authenticate?code=b" method="post">
  <input type="hidden" name="session" value="s1">
  <input name="code" type="text">
  <input type="submit" name="login" value="Zaloguj">
</form>"""


def test_device_id_is_stable_per_login() -> None:
    assert auth.device_id("user@example.com") == auth.device_id("user@example.com")
    assert auth.device_id("user@example.com") != auth.device_id("other@example.com")
    assert len(auth.device_id("user@example.com")) == 32


def test_forms() -> None:
    (form,) = auth.parse_forms(LOGIN_PAGE, "https://login.example/start")
    assert form.action == "https://login.example/realms/orlen/login-actions/authenticate?code=a&x=1"
    assert set(form.fields) == {"username", "password", "credentialId"}
    assert auth.is_login_form(LOGIN_PAGE)
    assert auth.find_mfa_form(LOGIN_PAGE, "https://login.example/") is None


def test_mfa_form() -> None:
    found = auth.find_mfa_form(SMS_PAGE, "https://login.example/")
    assert found is not None
    form, field = found
    assert field == "code"
    assert form.fields == {"session": "s1", "login": "Zaloguj"}
    assert auth.mfa_payload(form, field, "123456") == {
        "session": "s1",
        "login": "Zaloguj",
        "code": "123456",
    }
    assert not auth.is_login_form(SMS_PAGE)


def test_urls() -> None:
    assert auth.is_keycloak_url("https://login.example/realms/orlen/login-actions/x")
    assert not auth.is_keycloak_url(f"{BASE_URL}/home")
    assert auth.is_ebok_home(f"{BASE_URL}/home?x=1")


async def test_cookies_round_trip() -> None:
    jar = aiohttp.CookieJar()
    jar.update_cookies({"KEYCLOAK_SESSION": "abc"}, URL("https://login.example/realms/"))
    jar.update_cookies({auth.DEVICE_COOKIE: "dev"}, URL(BASE_URL))
    stored = auth.export_cookies(jar)
    assert [c["name"] for c in stored] == ["KEYCLOAK_SESSION"]

    restored = aiohttp.CookieJar()
    auth.restore_cookies(restored, [*stored, {"broken": True}])
    cookies = restored.filter_cookies(URL("https://login.example/realms/x"))
    assert cookies["KEYCLOAK_SESSION"].value == "abc"


async def test_password_login(hass, aioclient_mock) -> None:
    aioclient_mock.get(BASE_URL, text="")
    aioclient_mock.post(f"{BASE_URL}/auth/login", json={"Token": "T1", "Code": 0})
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    login = PasswordAuth(session, "user@example.com", "secret")
    assert await login.async_login() == "T1"
    payload = aioclient_mock.mock_calls[-1][2]
    assert payload["identificator"] == "user@example.com"
    assert payload["DeviceName"] == "Home Assistant"
    assert payload["DeviceId"] == auth.device_id("user@example.com")


@pytest.mark.parametrize(("status", "body"), [(401, {}), (200, {"Code": 2})])
async def test_password_login_rejected(hass, aioclient_mock, status, body) -> None:
    aioclient_mock.get(BASE_URL, text="")
    aioclient_mock.post(f"{BASE_URL}/auth/login", status=status, json=body)
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    with pytest.raises(MyOrlenAuthError):
        await PasswordAuth(session, "user@example.com", "bad").async_login()
