"""The fn_nas (飞牛NAS) integration, communicating with fnOS over WSS only."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_UPDATE_COORDINATOR, DOMAIN
from .coordinator import FlynasCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = FlynasCoordinator(hass, dict(entry.data), entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_UPDATE_COORDINATOR: coordinator
    }

    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: FlynasCoordinator = hass.data[DOMAIN][entry.entry_id][
            DATA_UPDATE_COORDINATOR
        ]
        await coordinator.async_disconnect()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
