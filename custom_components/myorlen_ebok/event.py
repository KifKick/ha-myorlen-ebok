"""eBOK notices (outages, phishing warnings, ...) as an event entity."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPE_NOTICE
from .coordinator import MyOrlenConfigEntry, MyOrlenCoordinator
from .entity import MyOrlenEntity
from .models import Meter

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyOrlenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Notices are account-wide: one entity, on the first meter's device."""
    coordinator = entry.runtime_data
    if coordinator.data.meters:
        async_add_entities([MyOrlenNotices(coordinator, coordinator.data.meters[0])])


class MyOrlenNotices(MyOrlenEntity, EventEntity):
    """Fires once for each notice eBOK starts showing.

    Notices already shown when Home Assistant starts count as seen, so a
    restart does not repeat them.
    """

    _attr_translation_key = "notices"
    _attr_event_types = [EVENT_TYPE_NOTICE]

    def __init__(self, coordinator: MyOrlenCoordinator, meter: Meter) -> None:
        super().__init__(coordinator, meter, "komunikaty", Platform.EVENT)
        self._seen = {notice.id for notice in coordinator.data.notices}

    @callback
    def _handle_coordinator_update(self) -> None:
        for notice in self.coordinator.data.notices:
            if notice.id in self._seen:
                continue
            self._seen.add(notice.id)
            self._trigger_event(
                EVENT_TYPE_NOTICE,
                {
                    "id": notice.id,
                    "title": notice.title,
                    "message": notice.message,
                    "date": notice.date.isoformat() if notice.date else None,
                },
            )
        super()._handle_coordinator_update()
