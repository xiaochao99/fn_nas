"""Sensor platform for fnOS over the WSS API (system, disks, storage pools)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfInformation, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DISK_MODEL,
    ATTR_DISK_SERIAL,
    ATTR_PROTOCOL,
    ATTR_RPM,
    ATTR_IS_SYSTEM,
    ATTR_POOL_NAME,
    ATTR_POOL_LEVEL,
    ATTR_POOL_MOUNTPOINT,
    ATTR_POOL_UUID,
    ATTR_TOTAL_CAPACITY,
    ATTR_MACHINE_TYPE_RAW,
    ATTR_SYS_DISK_TYPE,
    ATTR_HDD_COUNT,
    ATTR_SSD_COUNT,
    ATTR_HEALTH_STATUS,
    ATTR_POWER_ON_HOURS,
    CONF_HOST,
    DEVICE_ID_DISK_PREFIX,
    DEVICE_ID_NAS,
    DEVICE_ID_POOL_PREFIX,
    DOMAIN,
    HDD_MODEL,
    HDD_POWER_ON,
    HDD_SERIAL,
    HDD_STATUS,
    HDD_TEMP,
    HDD_WEAR,
    HEALTH_BAD,
    HEALTH_GOOD,
    ICON_CPU,
    ICON_DISK,
    ICON_MEMORY,
    ICON_NAS,
    ICON_STORAGE,
    ICON_TEMPERATURE,
    POOL_FREE,
    POOL_LEVEL,
    POOL_SIZE,
    POOL_USAGE,
    SYSTEM_CPU_CORES,
    SYSTEM_CPU_USAGE,
    SYSTEM_MACHINE_TYPE,
    SYSTEM_MEM_TOTAL,
    SYSTEM_MEM_USAGE,
    SYSTEM_MEM_USED,
    SYSTEM_STORAGE_FREE,
    SYSTEM_STORAGE_TOTAL,
    SYSTEM_SYS_DISK_TYPE,
)
from .coordinator import FlynasCoordinator

_LOGGER = logging.getLogger(__name__)

_GB = 1024**3


def _gb(value: int | None) -> float | None:
    return round(value / _GB, 2) if value else None


# ── System sensors ────────────────────────────────────────────────────────

SYSTEM_SENSORS = [
    {
        "key": SYSTEM_MACHINE_TYPE,
        "name": "机器类型",
        "icon": ICON_NAS,
        "gb": False,
    },
    {
        "key": SYSTEM_CPU_USAGE,
        "name": "CPU使用率",
        "icon": ICON_CPU,
        "unit": "%",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": SYSTEM_CPU_CORES,
        "name": "CPU核心数",
        "icon": ICON_CPU,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": SYSTEM_MEM_TOTAL,
        "name": "内存总量",
        "icon": ICON_MEMORY,
        "gb": True,
    },
    {
        "key": SYSTEM_MEM_USED,
        "name": "内存已用",
        "icon": ICON_MEMORY,
        "gb": True,
    },
    {
        "key": SYSTEM_MEM_USAGE,
        "name": "内存使用率",
        "icon": ICON_MEMORY,
        "unit": "%",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": SYSTEM_STORAGE_TOTAL,
        "name": "存储总容量",
        "icon": ICON_STORAGE,
        "gb": True,
    },
    {
        "key": SYSTEM_STORAGE_FREE,
        "name": "存储可用空间",
        "icon": ICON_STORAGE,
        "gb": True,
    },
    {
        "key": SYSTEM_SYS_DISK_TYPE,
        "name": "系统盘类型",
        "icon": ICON_DISK,
        "gb": False,
    },
]


class FlynasSystemSensor(CoordinatorEntity, SensorEntity):
    """A sensor sourced from coordinator.data['system']."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FlynasCoordinator, entry_id: str, spec: dict) -> None:
        super().__init__(coordinator)
        self._key = spec["key"]
        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._attr_unique_id = f"{entry_id}_sys_{self._key}"
        self._gb = spec.get("gb", False)
        if spec.get("unit"):
            self._attr_native_unit_of_measurement = spec["unit"]
        if spec.get("state_class"):
            self._attr_state_class = spec["state_class"]
        if self._gb:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
        self._attr_device_info = _nas_device_info(coordinator)

    @property
    def native_value(self) -> Any:
        value = self.coordinator.data["system"].get(self._key)
        if self._gb and isinstance(value, (int, float)):
            return _gb(value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._key == SYSTEM_MACHINE_TYPE:
            raw = self.coordinator.data["system"].get("_model_raw")
            hdd = self.coordinator.data["system"].get("_hdd_count")
            ssd = self.coordinator.data["system"].get("_ssd_count")
            attrs = {ATTR_MACHINE_TYPE_RAW: raw}
            if hdd is not None:
                attrs[ATTR_HDD_COUNT] = hdd
            if ssd is not None:
                attrs[ATTR_SSD_COUNT] = ssd
            return attrs
        if self._key == SYSTEM_SYS_DISK_TYPE:
            return {ATTR_SYS_DISK_TYPE: self.coordinator.data["system"].get(self._key)}
        return {}


# ── Disk sensors ──────────────────────────────────────────────────────────

DISK_SENSORS = [
    {
        "key": HDD_MODEL,
        "name": "型号",
        "icon": ICON_DISK,
        "diagnostic": True,
    },
    {
        "key": HDD_SERIAL,
        "name": "序列号",
        "icon": ICON_DISK,
        "diagnostic": True,
    },
    {
        "key": HDD_TEMP,
        "name": "温度",
        "icon": ICON_TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": HDD_STATUS,
        "name": "健康状态",
        "icon": ICON_DISK,
        "health": True,
    },
    {
        "key": HDD_POWER_ON,
        "name": "通电时长",
        "icon": ICON_DISK,
        "unit": "h",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": HDD_WEAR,
        "name": "寿命消耗",
        "icon": ICON_DISK,
        "unit": "%",
        "state_class": SensorStateClass.MEASUREMENT,
    },
]


class FlynasDiskSensor(CoordinatorEntity, SensorEntity):
    """A sensor sourced from a specific disk entry."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FlynasCoordinator, entry_id: str, disk: dict, spec: dict
    ) -> None:
        super().__init__(coordinator)
        self._disk_name = disk["name"]
        self._key = spec["key"]
        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._attr_unique_id = f"{entry_id}_disk_{self._disk_name}_{self._key}"
        if spec.get("unit"):
            self._attr_native_unit_of_measurement = spec["unit"]
        if spec.get("device_class"):
            self._attr_device_class = spec["device_class"]
        if spec.get("state_class"):
            self._attr_state_class = spec["state_class"]
        if spec.get("diagnostic"):
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = _disk_device_info(disk)

    def _disk(self) -> dict | None:
        return next(
            (d for d in self.coordinator.data["disks"] if d["name"] == self._disk_name),
            None,
        )

    @property
    def native_value(self) -> Any:
        disk = self._disk()
        if disk is None:
            return None
        if self._key == HDD_STATUS:
            return HEALTH_GOOD if disk.get("smart_ok") else HEALTH_BAD
        return disk.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        disk = self._disk()
        if disk is None:
            return {}
        attrs = {
            ATTR_DISK_MODEL: disk.get("model"),
            ATTR_DISK_SERIAL: disk.get("serial"),
            ATTR_PROTOCOL: disk.get("protocol"),
            ATTR_RPM: disk.get("rotation"),
            ATTR_IS_SYSTEM: disk.get("is_system"),
        }
        if self._key == HDD_POWER_ON:
            attrs[ATTR_POWER_ON_HOURS] = disk.get("power_on_hours")
        if self._key == HDD_STATUS:
            attrs[ATTR_HEALTH_STATUS] = (
                HEALTH_GOOD if disk.get("smart_ok") else HEALTH_BAD
            )
        return {k: v for k, v in attrs.items() if v is not None}


# ── Pool sensors ──────────────────────────────────────────────────────────

POOL_SENSORS = [
    {
        "key": POOL_SIZE,
        "name": "容量",
        "icon": ICON_STORAGE,
        "gb": True,
    },
    {
        "key": POOL_FREE,
        "name": "可用",
        "icon": ICON_STORAGE,
        "gb": True,
    },
    {
        "key": POOL_USAGE,
        "name": "使用率",
        "icon": ICON_STORAGE,
        "unit": "%",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": POOL_LEVEL,
        "name": "RAID级别",
        "icon": ICON_STORAGE,
        "gb": False,
    },
]


class FlynasPoolSensor(CoordinatorEntity, SensorEntity):
    """A sensor sourced from a specific storage pool entry."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: FlynasCoordinator, entry_id: str, pool: dict, spec: dict
    ) -> None:
        super().__init__(coordinator)
        self._pool_uuid = pool["uuid"]
        self._key = spec["key"]
        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._attr_unique_id = f"{entry_id}_pool_{self._pool_uuid}_{self._key}"
        self._gb = spec.get("gb", False)
        if self._gb:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
        elif spec.get("unit"):
            self._attr_native_unit_of_measurement = spec["unit"]
        if spec.get("state_class"):
            self._attr_state_class = spec["state_class"]
        self._attr_device_info = _pool_device_info(pool)

    def _pool(self) -> dict | None:
        return next(
            (p for p in self.coordinator.data["pools"] if p["uuid"] == self._pool_uuid),
            None,
        )

    @property
    def native_value(self) -> Any:
        pool = self._pool()
        if pool is None:
            return None
        value = pool.get(self._key)
        if self._gb and isinstance(value, (int, float)):
            return _gb(value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pool = self._pool()
        if pool is None:
            return {}
        return {
            ATTR_POOL_NAME: pool.get("name"),
            ATTR_POOL_LEVEL: pool.get("level"),
            ATTR_POOL_MOUNTPOINT: pool.get("mountpoint"),
            ATTR_POOL_UUID: pool.get("uuid"),
            ATTR_TOTAL_CAPACITY: _gb(pool.get("size")),
        }


# ── Device info helpers ───────────────────────────────────────────────────

def _nas_device_info(coordinator: FlynasCoordinator):
    host = coordinator.config[CONF_HOST]
    return {
        "identifiers": {(DOMAIN, DEVICE_ID_NAS)},
        "name": f"飞牛NAS ({host})",
        "manufacturer": "飞牛 fnOS",
        "model": coordinator.data["system"].get(SYSTEM_MACHINE_TYPE),
    }


def _disk_device_info(disk: dict):
    dev = disk.get("dev", "")
    display = disk.get("display_name", disk.get("name", dev))
    return {
        "identifiers": {(DOMAIN, f"{DEVICE_ID_DISK_PREFIX}{disk['name']}")},
        "name": f"磁盘 {display}",
        "model": disk.get("model") or dev,
        "manufacturer": disk.get("protocol"),
        "via_device": (DOMAIN, DEVICE_ID_NAS),
    }


def _pool_device_info(pool: dict):
    return {
        "identifiers": {(DOMAIN, f"{DEVICE_ID_POOL_PREFIX}{pool['uuid']}")},
        "name": f"存储池 {pool.get('name')}",
        "model": pool.get("level"),
        "via_device": (DOMAIN, DEVICE_ID_NAS),
    }


# ── Setup ─────────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FlynasCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    entry_id = entry.entry_id

    entities = [FlynasSystemSensor(coordinator, entry_id, spec) for spec in SYSTEM_SENSORS]

    for disk in coordinator.data.get("disks", []):
        for spec in DISK_SENSORS:
            entities.append(FlynasDiskSensor(coordinator, entry_id, disk, spec))

    for pool in coordinator.data.get("pools", []):
        for spec in POOL_SENSORS:
            entities.append(FlynasPoolSensor(coordinator, entry_id, pool, spec))

    async_add_entities(entities)
