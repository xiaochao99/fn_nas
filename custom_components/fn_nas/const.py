"""Constants for the fn_nas (飞牛NAS) integration.

This integration talks to fnOS exclusively over its WebSocket (WSS) monitoring
API. Features that fnOS does not expose over WebSocket (UPS, VM, Docker, fan,
ZFS scrub, sensor temperatures, uptime, MAC/WoL) are intentionally out of scope.
"""

DOMAIN = "fn_nas"
DATA_UPDATE_COORDINATOR = "coordinator"

# Config keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCHEME = "scheme"
CONF_TLS_INSECURE = "tls_insecure"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_IGNORE_DISKS = "ignore_disks"
CONF_DEVICE_ID = "device_id"

# SSH power-control — the 关机/重启 buttons ALWAYS use SSH. fnOS sometimes
# refuses the WebSocket ``appcgi.system.poweroff`` call with error 266240
# (device-side policy / unfinished VM-Docker-tasks block), while ``sudo
# shutdown``/``reboot`` over SSH is reliably honored. The same SSH connection
# (at setup time) auto-detects the NIC MAC used for Wake-on-LAN power-on.
CONF_SSH_PORT = "ssh_port"
CONF_SSH_SUDO_PASSWORD = "ssh_sudo_password"
DEFAULT_SSH_PORT = 22

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_SCHEME = "auto"

# Wake-on-LAN (power-on) — SSH can only shut the NAS down.
CONF_MAC = "mac"
DEFAULT_WOL_PORT = 9

# Device identifiers
DEVICE_ID_NAS = "flynas_nas"
DEVICE_ID_DISK_PREFIX = "flynas_disk_"
DEVICE_ID_POOL_PREFIX = "flynas_pool_"

# Icons
ICON_NAS = "mdi:server"
ICON_DISK = "mdi:harddisk"
ICON_TEMPERATURE = "mdi:thermometer"
ICON_STORAGE = "mdi:database"
ICON_CPU = "mdi:chip"
ICON_MEMORY = "mdi:memory"
ICON_RESTART = "mdi:restart"
ICON_POWEROFF = "mdi:power"
ICON_POWERON = "mdi:power-on"

# System sensor keys (into coordinator.data["system"])
SYSTEM_MACHINE_TYPE = "machine_type"
SYSTEM_CPU_USAGE = "cpu_usage"
SYSTEM_CPU_CORES = "cpu_cores"
SYSTEM_CPU_TEMP = "cpu_temp"
SYSTEM_MEM_TOTAL = "mem_total"
SYSTEM_MEM_USED = "mem_used"
SYSTEM_MEM_USAGE = "mem_usage"
SYSTEM_STORAGE_TOTAL = "storage_total"
SYSTEM_STORAGE_FREE = "storage_free"
SYSTEM_SYS_DISK_TYPE = "sys_disk_type"

# Disk sensor keys (into a disk entry)
HDD_MODEL = "model"
HDD_SERIAL = "serial"
HDD_TEMP = "temp"
HDD_STATUS = "health"
HDD_POWER_ON = "power_on_hours"
HDD_WEAR = "wear_level"

# Pool sensor keys (into a pool entry)
POOL_SIZE = "size"
POOL_FREE = "free"
POOL_USAGE = "usage"
POOL_LEVEL = "level"

# Attributes
ATTR_DISK_MODEL = "型号"
ATTR_DISK_SERIAL = "序列号"
ATTR_PROTOCOL = "接口协议"
ATTR_RPM = "转速"
ATTR_IS_SYSTEM = "系统盘"
ATTR_POOL_NAME = "存储池名称"
ATTR_POOL_LEVEL = "RAID 级别"
ATTR_POOL_MOUNTPOINT = "挂载点"
ATTR_POOL_UUID = "UUID"
ATTR_POWER_ON_HOURS = "通电时长(小时)"
ATTR_HEALTH_STATUS = "健康状态"
ATTR_TOTAL_CAPACITY = "总容量"
ATTR_MACHINE_TYPE_RAW = "原始机器类型"
ATTR_SYS_DISK_TYPE = "系统盘类型"
ATTR_HDD_COUNT = "机械硬盘数量"
ATTR_SSD_COUNT = "固态硬盘数量"

# Health status display strings
HEALTH_GOOD = "良好"
HEALTH_BAD = "故障"
