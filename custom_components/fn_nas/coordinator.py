"""DataUpdateCoordinator for fnOS over the WebSocket (WSS) API — CORRECTED."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SCHEME,
    CONF_TLS_INSECURE,
    CONF_USERNAME,
    CONF_IGNORE_DISKS,
    CONF_SSH_PORT,
    CONF_SSH_SUDO_PASSWORD,
    DEFAULT_SSH_PORT,
    SYSTEM_MACHINE_TYPE,
    SYSTEM_CPU_USAGE,
    SYSTEM_CPU_CORES,
    SYSTEM_CPU_TEMP,
    SYSTEM_MEM_TOTAL,
    SYSTEM_MEM_USED,
    SYSTEM_MEM_USAGE,
    SYSTEM_STORAGE_TOTAL,
    SYSTEM_STORAGE_FREE,
    SYSTEM_SYS_DISK_TYPE,
)
from .wss_client import FnWssClient, FnWssError

_LOGGER = logging.getLogger(__name__)


class FlynasCoordinator(DataUpdateCoordinator):
    """Coordinate fnOS data fetched exclusively via the WSS API."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any], entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=config.get(CONF_SCAN_INTERVAL, 30)),
        )
        self.config = config
        self.entry = entry
        self.wss = FnWssClient(
            host=config[CONF_HOST],
            username=config[CONF_USERNAME],
            password=config[CONF_PASSWORD],
            port=config.get(CONF_PORT),
            scheme=config.get(CONF_SCHEME, "auto"),
            tls_insecure=config.get(CONF_TLS_INSECURE, False),
        )
        self.ignore_disks = {
            d.strip()
            for d in (config.get(CONF_IGNORE_DISKS) or "").split(",")
            if d.strip()
        }
        # SSH power-control settings — the 关机/重启 buttons always run over SSH.
        self.ssh_port = int(config.get(CONF_SSH_PORT) or DEFAULT_SSH_PORT)
        self.ssh_sudo_password = config.get(CONF_SSH_SUDO_PASSWORD) or ""
        self.data: dict[str, Any] = {"system": {}, "disks": [], "pools": []}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            system_info = await self.wss.get_system_info()
            cpu = await self.wss.get_cpu()
            mem = await self.wss.get_memory()
            space = await self.wss.get_storage_space()
            overview = await self.wss.get_storage_overview()
            disks = await self.wss.get_all_disk_info()
        except FnWssError as err:
            raise UpdateFailed(f"fnOS WSS 错误: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"获取 fnOS 数据失败: {err}") from err
        finally:
            # Drop the socket so the next poll starts fresh; the NAS may close
            # idle connections, and reusing a stale one causes silent failures.
            await self.wss.close()

        disks = [d for d in disks if d["name"] not in self.ignore_disks]
        pools = self._parse_pools(overview)

        self.data = {
            "system": self._parse_system(system_info, cpu, mem, space),
            "disks": disks,
            "pools": pools,
        }
        return self.data

    @staticmethod
    def _parse_system(system_info, cpu, mem, space) -> dict[str, Any]:
        model = system_info.get("data", {}).get("model") or system_info.get("model")
        machine_type = system_info.get("data", {}).get("type") or system_info.get("type") or (
            "-".join(str(x) for x in model) if isinstance(model, list) else str(model or "")
        )

        # Response structure: resp["data"]["cpu"]["busy"]["all"] and resp["data"]["cpu"]["core"]
        cpu_data = cpu.get("data", {}).get("cpu", {}) or cpu.get("cpu", {})
        cpu_usage = cpu_data.get("busy", {}).get("all") if isinstance(cpu_data.get("busy"), dict) else cpu_data.get("usage")
        cpu_cores = cpu_data.get("core") or cpu_data.get("cores")
        # temp is an array, e.g. [48] for a single-sensor CPU
        cpu_temp_arr = cpu_data.get("temp", [])
        cpu_temp = cpu_temp_arr[0] if cpu_temp_arr else None

        # Response structure: resp["data"]["mem"] and resp["data"]["swap"]
        mem_data = mem.get("data", {}).get("mem", {}) or mem.get("mem", {})
        mem_total = mem_data.get("total", 0)
        mem_used = mem_data.get("used", 0)

        # Response is flat (no "data" wrapper)
        storage_total = space.get("fssizeStor", 0)
        storage_free = space.get("frsizeStor", 0)

        return {
            SYSTEM_MACHINE_TYPE: machine_type,
            SYSTEM_CPU_USAGE: cpu_usage,
            SYSTEM_CPU_CORES: cpu_cores,
            SYSTEM_CPU_TEMP: cpu_temp,
            SYSTEM_MEM_TOTAL: mem_total,
            SYSTEM_MEM_USED: mem_used,
            SYSTEM_MEM_USAGE: round(mem_used / mem_total * 100, 1) if mem_total else None,
            SYSTEM_STORAGE_TOTAL: storage_total,
            SYSTEM_STORAGE_FREE: storage_free,
            SYSTEM_SYS_DISK_TYPE: space.get("sysDiskType"),
            "_model_raw": model,
            "_hdd_count": space.get("HDD"),
            "_ssd_count": space.get("SSD"),
        }

    @staticmethod
    def _parse_pools(overview) -> list[dict[str, Any]]:
        pools: list[dict[str, Any]] = []
        for item in overview.get("array", []):
            total = item.get("fssize", 0)
            free = item.get("frsize", 0)
            mountpoint = item.get("mountpoint", "")
            name = item.get("comment") or mountpoint.rstrip("/").split("/")[-1] or item.get("uuid")
            pools.append(
                {
                    "uuid": item.get("uuid"),
                    "name": name,
                    "mountpoint": mountpoint,
                    "level": item.get("level"),
                    "size": total,
                    "free": free,
                    "usage": round((total - free) / total * 100, 1) if total else None,
                }
            )
        return pools

    async def ssh_poweroff(self) -> None:
        """Shut the NAS down over SSH (``sudo shutdown -h now``)."""
        from .ssh_power import SshPowerError, send_power_command

        try:
            await send_power_command(
                host=self.config[CONF_HOST],
                port=self.ssh_port,
                username=self.config[CONF_USERNAME],
                password=self.config[CONF_PASSWORD],
                sudo_password=self.ssh_sudo_password,
                command="shutdown -h now",
            )
        except SshPowerError:
            raise

    async def ssh_reboot(self) -> None:
        """Reboot the NAS over SSH (``sudo reboot``)."""
        from .ssh_power import SshPowerError, send_power_command

        try:
            await send_power_command(
                host=self.config[CONF_HOST],
                port=self.ssh_port,
                username=self.config[CONF_USERNAME],
                password=self.config[CONF_PASSWORD],
                sudo_password=self.ssh_sudo_password,
                command="reboot",
            )
        except SshPowerError:
            raise

    async def power_control(self, action: str) -> None:
        """Issue a power action (``poweroff``/``reboot``) over SSH.

        fnOS reliably honors ``sudo shutdown``/``reboot`` over SSH; the
        WebSocket poweroff API is refused on some firmwares (error 266240), so
        SSH is used directly for both the 关机 and 重启 buttons.
        """
        await self._ssh_power(action)

    async def _ssh_power(self, action: str) -> None:
        if action == "reboot":
            await self.ssh_reboot()
        else:
            await self.ssh_poweroff()

    async def async_disconnect(self) -> None:
        await self.wss.close()
