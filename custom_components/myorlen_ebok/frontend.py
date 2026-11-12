"""Serve the bundled dashboard card and register it with Lovelace.

The card (`frontend/myorlen-ebok-card.js`, built from the repository's
`frontend/` folder) ships with the integration, so one install gives both and
their versions always match.

It is delivered by exactly one path. With Lovelace resources in storage (the
default), the integration keeps one resource for the bundle: Lovelace loads
its resources before it creates cards. With resources declared in YAML the
integration must not write them, so the bundle is added to the frontend's
extra modules instead; the same happens if the resource can't be written.

Nothing here may break the integration: the sensors work without the card.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .card_resource import plan_card_resource, resource_payload
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME: Final = "myorlen-ebok-card.js"
CARD_PATH: Final = Path(__file__).parent / "frontend" / CARD_FILENAME
CARD_URL: Final = f"/{DOMAIN}/{CARD_FILENAME}"

_REGISTERED: Final = f"{DOMAIN}_card_registered"
_STATIC_REGISTERED: Final = f"{DOMAIN}_card_static_registered"


def _bundle_digest(path: Path) -> str:
    """Return a short content hash, so a rebuilt bundle busts caches too."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def _storage_resources(hass: HomeAssistant) -> Any | None:
    """Return Lovelace's writable resource collection, or None.

    None when Lovelace isn't set up or its resources are declared in YAML,
    where the collection has no create, update or delete.
    """
    from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE

    if (data := hass.data.get(LOVELACE_DATA)) is None:
        return None
    # `resource_mode` replaced `mode` in Home Assistant 2026.2.
    mode = getattr(data, "resource_mode", getattr(data, "mode", None))
    return data.resources if mode == MODE_STORAGE else None


async def _async_sync_resource(resources: Any, versioned_url: str) -> None:
    """Leave Lovelace holding exactly one resource for the card."""
    # The collection loads lazily; without this every start looks like a
    # fresh install and adds a duplicate.
    await resources.async_get_info()
    plan = plan_card_resource(resources.async_items(), versioned_url)
    if plan.create:
        await resources.async_create_item(resource_payload(versioned_url))
        _LOGGER.info("Registered the myORLEN eBOK card resource (%s)", versioned_url)
    elif plan.update_id is not None:
        await resources.async_update_item(plan.update_id, resource_payload(versioned_url))
        _LOGGER.info("Updated the myORLEN eBOK card resource to %s", versioned_url)
    for duplicate in plan.delete_ids:
        await resources.async_delete_item(duplicate)


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card bundle and register it once per Home Assistant run."""
    if hass.data.get(_REGISTERED):
        return
    if not {"http", "frontend"} <= hass.config.components:
        _LOGGER.debug("http/frontend not loaded; the dashboard card isn't registered")
        return
    try:
        from homeassistant.components.http import StaticPathConfig

        if not await hass.async_add_executor_job(CARD_PATH.is_file):
            _LOGGER.warning("The dashboard card bundle is missing: %s", CARD_PATH)
            return
        if not hass.data.get(_STATIC_REGISTERED):
            # The URL carries a version, so the file can be cached for long.
            await hass.http.async_register_static_paths(
                [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=True)]
            )
            hass.data[_STATIC_REGISTERED] = True

        integration = await async_get_integration(hass, DOMAIN)
        digest = await hass.async_add_executor_job(_bundle_digest, CARD_PATH)
        versioned_url = f"{CARD_URL}?v={integration.version}-{digest}"

        resources = _storage_resources(hass)
        synced = False
        if resources is not None:
            try:
                await _async_sync_resource(resources, versioned_url)
                synced = True
            except Exception:
                _LOGGER.exception("Unable to register the myORLEN eBOK card as a Lovelace resource")
        if not synced:
            from homeassistant.components.frontend import add_extra_js_url

            add_extra_js_url(hass, versioned_url)
    except Exception:
        _LOGGER.exception("Unable to register the myORLEN eBOK dashboard card")
    else:
        hass.data[_REGISTERED] = True
