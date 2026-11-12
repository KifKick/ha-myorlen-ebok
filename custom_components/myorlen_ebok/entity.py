"""Base entity: one device per gas meter."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import BASE_URL, DOMAIN
from .coordinator import MyOrlenCoordinator
from .models import Meter


class MyOrlenEntity(CoordinatorEntity[MyOrlenCoordinator]):
    """An entity of one meter.

    Entity ids are myorlen_<local meter id>_<key>, e.g.
    sensor.myorlen_1000001_do_zaplaty - short, and independent of the device
    name and area HA would otherwise prefix. Ids already in the registry stay.
    """

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: MyOrlenCoordinator, meter: Meter, key: str, platform: Platform
    ) -> None:
        super().__init__(coordinator)
        self.meter = meter
        self._attr_unique_id = f"{meter.number}_{key}"
        self.entity_id = f"{platform}.{slugify(f'myorlen {meter.id_local} {key}')}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, meter.number)},
            name=f"Gaz {meter.number}",
            manufacturer="ORLEN",
            model=meter.tariff or "Licznik gazu",
            serial_number=meter.number,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"{BASE_URL}/home",
        )
