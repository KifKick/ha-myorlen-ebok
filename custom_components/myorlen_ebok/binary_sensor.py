"""Overdue payment of a gas meter."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MyOrlenConfigEntry, MyOrlenCoordinator
from .entity import MyOrlenEntity
from .models import Invoice, Meter
from .sensor import unpaid

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyOrlenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(MyOrlenOverdue(coordinator, meter) for meter in coordinator.data.meters)


class MyOrlenOverdue(MyOrlenEntity, BinarySensorEntity):
    """On while an invoice is past its due date and not paid.

    A payment made but not booked yet does not count.
    """

    _attr_translation_key = "overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: MyOrlenCoordinator, meter: Meter) -> None:
        super().__init__(coordinator, meter, "zalegla_platnosc", Platform.BINARY_SENSOR)

    def _overdue(self) -> list[Invoice]:
        today = self.coordinator.today
        return [
            i
            for i in unpaid(self.coordinator.data, self.meter)
            if i.due_date is not None and i.due_date < today
        ]

    @property
    def is_on(self) -> bool:
        return bool(self._overdue())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        overdue = self._overdue()
        return {
            "amount": round(sum(i.to_pay for i in overdue), 2),
            "invoices": [i.number for i in overdue],
            "since": min((i.due_date for i in overdue if i.due_date), default=None),
        }
