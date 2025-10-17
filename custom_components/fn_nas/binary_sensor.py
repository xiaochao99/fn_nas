import logging
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN, HDD_HEALTH, DEVICE_ID_NAS, DATA_UPDATE_COORDINATOR
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    domain_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = domain_data[DATA_UPDATE_COORDINATOR]
    
    entities = []
    existing_ids = set()
    
    # 添加硬盘健康状态二元传感器
    for disk in coordinator.data.get("disks", []):
        health_uid = f"{config_entry.entry_id}_{disk['device']}_health_binary"
        if health_uid not in existing_ids:
            entities.append(
                DiskHealthBinarySensor(
                    coordinator, 
                    disk["device"], 
                    f"硬盘 {disk.get('model', '未知')} 健康状态",
                    health_uid,
                    disk
                )
            )
            existing_ids.add(health_uid)
    
    async_add_entities(entities)


class DiskHealthBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, device_id, name, unique_id, disk_info):
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = unique_id
        self.disk_info = disk_info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"disk_{device_id}")},
            "name": disk_info.get("model", "未知硬盘"),
            "manufacturer": "硬盘设备",
            "via_device": (DOMAIN, DEVICE_ID_NAS)
        }
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
    
    @property
    def is_on(self):
        """返回True表示有问题，False表示正常"""
        for disk in self.coordinator.data.get("disks", []):
            if disk["device"] == self.device_id:
                health = disk.get("health", "未知")
                # 将健康状态映射为二元状态
                if health in ["正常", "良好", "OK", "ok", "good", "Good"]:
                    return False  # 正常状态
                elif health in ["警告", "异常", "错误", "warning", "Warning", "error", "Error", "bad", "Bad"]:
                    return True   # 有问题状态
                else:
                    # 未知状态也视为有问题
                    return True
        return True  # 默认视为有问题
    
    @property
    def icon(self):
        """根据状态返回图标"""
        if self.is_on:
            return "mdi:alert-circle"  # 有问题时显示警告图标
        else:
            return "mdi:check-circle"   # 正常时显示对勾图标