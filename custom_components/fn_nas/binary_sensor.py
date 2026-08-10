"""Binary sensor platform for fnOS over the WSS API (disk health)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_HEALTH_STATUS,
    DOMAIN,
    HEALTH_BAD,
    HEALTH_GOOD,
    ICON_DISK,
)
from .coordinator import FlynasCoordinator
from .sensor import _disk_device_info

_LOGGER = logging.getLogger(__name__)


class FlynasDiskHealthBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Report a disk SMART health problem (on = unhealthy)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: FlynasCoordinator, entry_id: str, disk: dict) -> None:
        super().__init__(coordinator)
        self._disk_name = disk["name"]
        self._attr_name = "健康状态异常"
        self._attr_icon = ICON_DISK
        self._attr_unique_id = f"{entry_id}_disk_{self._disk_name}_health_problem"
        self._attr_device_info = _disk_device_info(disk, entry_id)

    def _disk(self) -> dict | None:
        return next(
            (d for d in self.coordinator.data["disks"] if d["name"] == self._disk_name),
            None,
        )

    @property
    def is_on(self) -> bool:
        disk = self._disk()
        if disk is None:
            return False
        return not disk.get("smart_ok", True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        disk = self._disk()
        if disk is None:
            return {}
        healthy = disk.get("smart_ok", True)
        return {ATTR_HEALTH_STATUS: HEALTH_GOOD if healthy else HEALTH_BAD}


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlynasCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    entry_id = entry.entry_id
    entities = [
        FlynasDiskHealthBinarySensor(coordinator, entry_id, disk)
        for disk in coordinator.data.get("disks", [])
    ]
    async_add_entities(entities)
