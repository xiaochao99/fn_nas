"""The fn_nas (飞牛NAS) integration, communicating with fnOS over WSS only."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    DATA_UPDATE_COORDINATOR,
    DEVICE_ID_DISK_PREFIX,
    DEVICE_ID_NAS,
    DEVICE_ID_POOL_PREFIX,
    DOMAIN,
)
from .coordinator import FlynasCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "button"]


def _is_legacy_device_identifier(identifier: str) -> bool:
    return identifier == DEVICE_ID_NAS or identifier.startswith(
        (DEVICE_ID_DISK_PREFIX, DEVICE_ID_POOL_PREFIX)
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scope device identifiers created before config entry version 3."""
    if entry.version < 3:
        device_registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        ):
            identifiers = {
                (
                    domain,
                    f"{entry.entry_id}_{identifier}"
                    if domain == DOMAIN and _is_legacy_device_identifier(identifier)
                    else identifier,
                )
                for domain, identifier in device.identifiers
            }
            if identifiers != device.identifiers:
                device_registry.async_update_device(
                    device.id, new_identifiers=identifiers
                )

        hass.config_entries.async_update_entry(entry, version=3)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Options (e.g. the WoL MAC set via the options flow) override data.
    config = {**entry.data, **(entry.options or {})}
    coordinator = FlynasCoordinator(hass, config, entry)
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
