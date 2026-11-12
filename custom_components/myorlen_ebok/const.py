"""Constants for the myORLEN eBOK integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "myorlen_ebok"

BASE_URL: Final = "https://ebok.myorlen.pl"
API_VERSION: Final = "3.0"

CONF_AUTH_METHOD: Final = "auth_method"
CONF_SESSION: Final = "session"
CONF_MFA_CODE: Final = "mfa_code"
CONF_UPDATE_INTERVAL: Final = "update_interval"  # hours

AUTH_PASSWORD: Final = "password"  # /auth/login, e-mail or customer number + password
AUTH_ORLEN_ID: Final = "orlen_id"  # OrlenID single sign-on, may ask for an SMS code

DEFAULT_UPDATE_INTERVAL: Final = 6
MIN_UPDATE_INTERVAL: Final = 1
MAX_UPDATE_INTERVAL: Final = 24

# eBOK drops an idle OrlenID session well before 30 minutes; every call resets
# the idle clock, so a short keep-alive saves an SMS code on the next poll.
ORLEN_ID_KEEPALIVE: Final = timedelta(minutes=10)

# Invoices and payments listed in attributes.
RECENT_INVOICES: Final = 6
RECENT_PAYMENTS: Final = 6

# A reading is billed from the value submitted; a larger jump over the last
# known reading must be confirmed explicitly.
MAX_READING_INCREASE_M3: Final = 500

SERVICE_ADD_READING: Final = "add_reading"
SERVICE_REFRESH: Final = "refresh"

ATTR_DEVICE_ID: Final = "device_id"
ATTR_VALUE: Final = "value"
ATTR_DATE: Final = "date"
ATTR_METER_RESET: Final = "meter_reset"
ATTR_CONFIRM_LARGE_INCREASE: Final = "confirm_large_increase"

EVENT_TYPE_NOTICE: Final = "notice"
