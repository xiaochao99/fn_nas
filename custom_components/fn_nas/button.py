"""Buttons for fnOS system power management."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_MAC,
    DOMAIN,
    ICON_POWEROFF,
    ICON_POWERON,
    ICON_RESTART,
)
from .coordinator import FlynasCoordinator
from .sensor import _nas_device_info
from .wol import async_send_magic_packet

_LOGGER = logging.getLogger(__name__)


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
        try:
            # 关机/重启 always run over SSH (fnOS's WebSocket poweroff API is
            # refused on some firmwares, error 266240). ``power_control`` raises
            # SshPowerError on SSH failure; it bubbles up here and is surfaced
            # cleanly instead of an uncaught "Unexpected exception".
            await self.coordinator.power_control(self._action)
        except HomeAssistantError:
            # Already a user-facing error (e.g. SSH dependency missing) — re-raise.
            raise
        except Exception as err:
            # Surface a clean, user-visible error instead of an uncaught
            # "Unexpected exception" in the websocket handler. A device-side
            # refusal (e.g. fnOS error 266240) is reported with its code so the
            # user knows it is a NAS policy/state issue, not an integration crash.
            _LOGGER.error("飞牛NAS %s 操作失败: %s", self._action, err)
            raise HomeAssistantError(f"飞牛NAS{self._attr_name}失败：{err}") from err


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlynasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [
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

    # Wake-on-LAN power-on button — only when a MAC address is configured.
    mac = coordinator.config.get(CONF_MAC)
    if mac:
        entities.append(
            WolButton(
                coordinator,
                entry.entry_id,
                mac,
                "开机",
                ICON_POWERON,
            )
        )

    async_add_entities(entities)


class WolButton(ButtonEntity):
    """Send a Wake-on-LAN magic packet to power the NAS on.

    This entity is intentionally NOT a CoordinatorEntity: Wake-on-LAN only
    needs to broadcast a UDP packet addressed to the NIC's MAC, so it must
    stay usable even when the NAS is powered off — at which point the
    coordinator's polling fails and ordinary CoordinatorEntities get marked
    ``unavailable`` by Home Assistant, which would otherwise grey out the
    power-on button exactly when it is needed most.

    The MAC is captured at setup and refreshed via an integration reload when
    changed in the options flow.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FlynasCoordinator,
        entry_id: str,
        mac: str,
        name: str,
        icon: str,
    ) -> None:
        # Not a CoordinatorEntity — deliberately do NOT call super().__init__
        # with the coordinator, so availability is independent of polling.
        self._mac = mac
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry_id}_wol"
        self._attr_device_info = _nas_device_info(coordinator, entry_id)

    @property
    def available(self) -> bool:
        # A magic packet is sent blindly over UDP; it does not require the NAS
        # to be reachable. Keep the button always pressable.
        return True

    async def async_press(self) -> None:
        try:
            await async_send_magic_packet(self.hass, self._mac)
        except Exception as err:
            _LOGGER.error("飞牛NAS 开机 (WoL) 失败: %s", err)
            raise HomeAssistantError(f"飞牛NAS开机(WoL)失败：{err}") from err

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "mac": self._mac,
            "说明": "需 NAS 开启 WoL 且 HA 与 NAS 在同一局域网",
        }
