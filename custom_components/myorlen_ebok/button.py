"""Refresh button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MyOrlenConfigEntry, MyOrlenCoordinator
from .entity import MyOrlenEntity
from .models import Meter

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyOrlenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(MyOrlenRefresh(coordinator, meter) for meter in coordinator.data.meters)


class MyOrlenRefresh(MyOrlenEntity, ButtonEntity):
    """Fetch eBOK now instead of waiting for the next update."""

    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MyOrlenCoordinator, meter: Meter) -> None:
        super().__init__(coordinator, meter, "odswiez", Platform.BUTTON)

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
