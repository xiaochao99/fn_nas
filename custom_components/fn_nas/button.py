import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN, DATA_UPDATE_COORDINATOR, DEVICE_ID_NAS, CONF_ENABLE_DOCKER, DEVICE_ID_ZFS
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    domain_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = domain_data[DATA_UPDATE_COORDINATOR]
    enable_docker = domain_data.get(CONF_ENABLE_DOCKER, False)
    
    entities = []
    
    # 1. 添加NAS重启按钮
    entities.append(RebootButton(coordinator, config_entry.entry_id))
    
    # 2. 添加虚拟机重启按钮和强制关机按钮
    if "vms" in coordinator.data:
        for vm in coordinator.data["vms"]:
            entities.append(
                VMRebootButton(
                    coordinator, 
                    vm["name"],
                    vm.get("title", vm["name"]),
                    config_entry.entry_id
                )
            )
            entities.append(
                VMDestroyButton(
                    coordinator, 
                    vm["name"],
                    vm.get("title", vm["name"]),
                    config_entry.entry_id
                )
            )
    
    # 3. 添加Docker容器重启按钮（如果启用了Docker功能）
    if enable_docker and "docker_containers" in coordinator.data:
        for container in coordinator.data["docker_containers"]:
            # 使用容器名称生成安全ID（替换特殊字符）
            safe_name = container["name"].replace(" ", "_").replace("/", "_").replace(".", "_")
            entities.append(
                DockerContainerRestartButton(
                    coordinator, 
                    container["name"],
                    safe_name,
                    config_entry.entry_id
                )
            )
    
    # 4. 添加ZFS存储池scrub按钮
    if "zpools" in coordinator.data:
        for zpool in coordinator.data["zpools"]:
            safe_name = zpool["name"].replace(" ", "_").replace("/", "_").replace(".", "_")
            entities.append(
                ZpoolScrubButton(
                    coordinator, 
                    zpool["name"],
                    safe_name,
                    config_entry.entry_id
                )
            )
    
    async_add_entities(entities)

class RebootButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator)
        self._attr_name = "重启"
        self._attr_unique_id = f"{entry_id}_flynas_reboot"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = {
            "identifiers": {(DOMAIN, DEVICE_ID_NAS)},
            "name": "飞牛NAS系统",
            "manufacturer": "飞牛",
            "model": "飞牛NAS"
        }
    
    async def async_press(self):
        await self.coordinator.reboot_system()
        self.async_write_ha_state()
        
    @property
    def extra_state_attributes(self):
        return {
            "提示": "按下此按钮将重启飞牛NAS系统"
        }

class VMRebootButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, vm_name, vm_title, entry_id):
        super().__init__(coordinator)
        self.vm_name = vm_name
        self.vm_title = vm_title
        self._attr_name = f"{vm_title} 重启"
        self._attr_unique_id = f"{entry_id}_flynas_vm_{vm_name}_reboot"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"vm_{vm_name}")},
            "name": vm_title,
            "via_device": (DOMAIN, DEVICE_ID_NAS)
        }

        self.vm_manager = coordinator.vm_manager if hasattr(coordinator, 'vm_manager') else None

    async def async_press(self):
        """重启虚拟机"""
        if not self.vm_manager:
            _LOGGER.error("vm_manager不可用，无法重启虚拟机 %s", self.vm_name)
            return
            
        try:
            success = await self.vm_manager.control_vm(self.vm_name, "reboot")
            if success:
                # 更新状态为"重启中"
                for vm in self.coordinator.data["vms"]:
                    if vm["name"] == self.vm_name:
                        vm["state"] = "rebooting"
                self.async_write_ha_state()
                
                # 在下次更新时恢复实际状态
                self.coordinator.async_add_listener(self.async_write_ha_state)
        except Exception as e:
            _LOGGER.error("重启虚拟机时出错: %s", str(e), exc_info=True)

class DockerContainerRestartButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, container_name, safe_name, entry_id):
        super().__init__(coordinator)
        self.container_name = container_name
        self.safe_name = safe_name
        self._attr_name = f"{container_name} 重启"
        self._attr_unique_id = f"{entry_id}_docker_{safe_name}_restart"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"docker_{safe_name}")},
            "name": container_name,
            "via_device": (DOMAIN, DEVICE_ID_NAS)
        }
        self._attr_icon = "mdi:docker"

    async def async_press(self):
        """重启Docker容器"""
        # 检查是否启用了Docker功能
        if not hasattr(self.coordinator, 'docker_manager') or self.coordinator.docker_manager is None:
            _LOGGER.error("Docker管理功能未启用，无法重启容器 %s", self.container_name)
            return
            
        try:
            # 更新状态为"重启中"
            for container in self.coordinator.data.get("docker_containers", []):
                if container["name"] == self.container_name:
                    container["status"] = "restarting"
            self.async_write_ha_state()
            
            # 执行重启命令
            success = await self.coordinator.docker_manager.control_container(self.container_name, "restart")
            
            if success:
                _LOGGER.info("Docker容器 %s 重启命令已发送", self.container_name)
                
                # 强制刷新状态（因为容器重启可能需要时间）
                self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("Docker容器 %s 重启失败", self.container_name)
                # 恢复原始状态
                for container in self.coordinator.data.get("docker_containers", []):
                    if container["name"] == self.container_name:
                        container["status"] = "running"  # 假设重启失败后状态不变
                self.async_write_ha_state()
                
        except Exception as e:
            _LOGGER.error("重启Docker容器 %s 时出错: %s", self.container_name, str(e), exc_info=True)
            # 恢复原始状态
            for container in self.coordinator.data.get("docker_containers", []):
                if container["name"] == self.container_name:
                    container["status"] = "running"
            self.async_write_ha_state()
    
    @property
    def extra_state_attributes(self):
        return {
            "容器名称": self.container_name,
            "操作类型": "重启容器",
            "提示": "重启操作可能需要一些时间完成"
        }

class VMDestroyButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, vm_name, vm_title, entry_id):
        super().__init__(coordinator)
        self.vm_name = vm_name
        self.vm_title = vm_title
        self._attr_name = f"{vm_title} 强制关机"
        self._attr_unique_id = f"{entry_id}_flynas_vm_{vm_name}_destroy"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"vm_{vm_name}")},
            "name": vm_title,
            "via_device": (DOMAIN, DEVICE_ID_NAS)
        }
        self._attr_icon = "mdi:power-off"  # 使用关机图标

        self.vm_manager = coordinator.vm_manager if hasattr(coordinator, 'vm_manager') else None

    async def async_press(self):
        """强制关机虚拟机"""
        if not self.vm_manager:
            _LOGGER.error("vm_manager不可用，无法强制关机虚拟机 %s", self.vm_name)
            return
            
        try:
            success = await self.vm_manager.control_vm(self.vm_name, "destroy")
            if success:
                # 更新状态为"强制关机中"
                for vm in self.coordinator.data["vms"]:
                    if vm["name"] == self.vm_name:
                        vm["state"] = "destroying"
                self.async_write_ha_state()
                
                # 在下次更新时恢复实际状态
                self.coordinator.async_add_listener(self.async_write_ha_state)
        except Exception as e:
            _LOGGER.error("强制关机虚拟机时出错: %s", str(e), exc_info=True)

    @property
    def extra_state_attributes(self):
        return {
            "虚拟机名称": self.vm_name,
            "操作类型": "强制关机",
            "警告": "此操作会强制关闭虚拟机，可能导致数据丢失",
            "提示": "仅在虚拟机无法正常关机时使用此功能"
        }

class ZpoolScrubButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, zpool_name, safe_name, entry_id):
        super().__init__(coordinator)
        self.zpool_name = zpool_name
        self.safe_name = safe_name
        self._attr_name = f"ZFS {zpool_name} 数据检查"
        self._attr_unique_id = f"{entry_id}_zpool_{safe_name}_scrub"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, DEVICE_ID_ZFS)},
            "name": "ZFS存储池",
            "via_device": (DOMAIN, DEVICE_ID_NAS)
        }
        self._attr_icon = "mdi:harddisk-check"

    @property
    def available(self):
        """检查按钮是否可用（当scrub进行中时不可点击）"""
        scrub_status = self.coordinator.data.get("scrub_status", {}).get(self.zpool_name, {})
        return not scrub_status.get("scrub_in_progress", False)

    async def async_press(self):
        """执行ZFS存储池数据一致性检查"""
        try:
            # 检查是否已经有scrub在进行中
            scrub_status = self.coordinator.data.get("scrub_status", {}).get(self.zpool_name, {})
            if scrub_status.get("scrub_in_progress", False):
                self.coordinator.logger.warning(f"ZFS存储池 {self.zpool_name} 已在进行数据一致性检查")
                return
            
            success = await self.coordinator.scrub_zpool(self.zpool_name)
            if success:
                self.coordinator.logger.info(f"ZFS存储池 {self.zpool_name} 数据一致性检查启动成功")
                # 立即刷新状态以更新按钮状态
                await self.coordinator.async_request_refresh()
            else:
                self.coordinator.logger.error(f"ZFS存储池 {self.zpool_name} 数据一致性检查启动失败")
        except Exception as e:
            self.coordinator.logger.error(f"启动ZFS存储池 {self.zpool_name} 数据一致性检查时出错: {str(e)}", exc_info=True)
    
    @property
    def extra_state_attributes(self):
        return {
            "存储池名称": self.zpool_name,
            "操作类型": "数据一致性检查",
            "说明": "对ZFS存储池执行数据完整性和一致性验证",
            "提示": "此操作可能需要较长时间完成，建议在低峰期执行"
        }