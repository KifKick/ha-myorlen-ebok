"""Errors raised by the eBOK client."""

from __future__ import annotations


class MyOrlenError(Exception):
    """Base error."""


class MyOrlenConnectionError(MyOrlenError):
    """eBOK unreachable or answered unexpectedly."""


class MyOrlenAuthError(MyOrlenError):
    """Credentials rejected, or the session expired and needs the user."""


class MyOrlenMfaRequired(MyOrlenAuthError):
    """OrlenID sent an SMS code; finish with OrlenIdAuth.async_complete_mfa()."""


class MyOrlenMfaInvalid(MyOrlenAuthError):
    """The SMS code was wrong; OrlenID accepts another attempt."""


class MyOrlenMfaExpired(MyOrlenAuthError):
    """The SMS step timed out; the login has to start again."""


class MyOrlenReadingRejected(MyOrlenError):
    """eBOK refused a meter reading."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
