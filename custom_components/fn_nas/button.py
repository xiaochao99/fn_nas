"""Buttons for fnOS system power management."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ICON_POWEROFF,
    ICON_RESTART,
)
from .coordinator import FlynasCoordinator
from .sensor import _nas_device_info


class FlynasPowerButton(CoordinatorEntity, ButtonEntity):
    """A button that invokes one fnOS power-management action."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FlynasCoordinator,
        entry_id: str,
        action: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._action = action
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry_id}_{action}"
        self._attr_device_info = _nas_device_info(coordinator, entry_id)

    async def async_press(self) -> None:
        if self._action == "reboot":
            await self.coordinator.wss.reboot()
        else:
            await self.coordinator.wss.poweroff()


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlynasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            FlynasPowerButton(
                coordinator,
                entry.entry_id,
                "reboot",
                "重启",
                ICON_RESTART,
            ),
            FlynasPowerButton(
                coordinator,
                entry.entry_id,
                "poweroff",
                "关机",
                ICON_POWEROFF,
            ),
        ]
    )
