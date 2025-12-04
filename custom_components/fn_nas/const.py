from homeassistant.const import Platform

DOMAIN = "fn_nas"
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON
]

CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ROOT_PASSWORD = "root_password"
CONF_SSH_KEY = "ssh_key"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_FAN_CONFIG_PATH = "fan_config_path"
CONF_IGNORE_DISKS = "ignore_disks"
CONF_MAC = "mac"
CONF_UPS_SCAN_INTERVAL = "ups_scan_interval"
CONF_ENABLE_DOCKER = "enable_docker"
DOCKER_CONTAINERS = "docker_containers"

DEFAULT_PORT = 22
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_UPS_SCAN_INTERVAL = 30 

DATA_UPDATE_COORDINATOR = "coordinator"

HDD_TEMP = "temperature"
HDD_HEALTH = "health"
HDD_STATUS = "status"
SYSTEM_INFO = "system"
FAN_SPEED = "fan_speed"
UPS_INFO = "ups_info"
ZFS_POOL = "zfs_pool" 

ATTR_DISK_MODEL = "硬盘型号"
ATTR_SERIAL_NO = "序列号"
ATTR_POWER_ON_HOURS = "通电时间"
ATTR_TOTAL_CAPACITY = "总容量"
ATTR_HEALTH_STATUS = "健康状态"
ATTR_FAN_MODE = "控制模式"
ATTR_FAN_CONFIG = "配置文件"

ICON_DISK = "mdi:harddisk"
ICON_FAN = "mdi:fan"
ICON_TEMPERATURE = "mdi:thermometer"
ICON_HEALTH = "mdi:heart-pulse"
ICON_POWER = "mdi:power"
ICON_RESTART = "mdi:restart"
ICON_ZFS = "mdi:harddisk-plus"

# 设备标识符常量
DEVICE_ID_NAS = "flynas_nas_system"
DEVICE_ID_UPS = "flynas_ups"
DEVICE_ID_ZFS = "flynas_zfs"
CONF_NETWORK_MACS = "network_macs"

# ZFS相关常量
ATTR_ZPOOL_NAME = "存储池名称"
ATTR_ZPOOL_HEALTH = "健康状态"
ATTR_ZPOOL_SIZE = "总大小"
ATTR_ZPOOL_ALLOC = "已使用"
ATTR_ZPOOL_FREE = "可用空间"
ATTR_ZPOOL_CAPACITY = "使用率"
ATTR_ZPOOL_FRAGMENTATION = "碎片率"
ATTR_ZPOOL_CKPOINT = "检查点"
ATTR_ZPOOL_EXPANDSZ = "扩展大小"
ATTR_ZPOOL_DEDUP = "重复数据删除率"
ATTR_ZPOOL_SCRUB_STATUS = "检查状态"
ATTR_ZPOOL_SCRUB_PROGRESS = "检查进度"
ATTR_ZPOOL_SCRUB_SCAN_RATE = "扫描速度"
ATTR_ZPOOL_SCRUB_TIME_REMAINING = "剩余时间"
ATTR_ZPOOL_SCRUB_ISSUED = "已发出数据"
ATTR_ZPOOL_SCRUB_REPAIRED = "已修复数据"