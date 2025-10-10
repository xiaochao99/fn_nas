import re
import logging
import asyncio
from .const import CONF_IGNORE_DISKS

_LOGGER = logging.getLogger(__name__)

class DiskManager:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.logger = _LOGGER.getChild("disk_manager")
        self.logger.setLevel(logging.DEBUG)
        self.disk_status_cache = {}  # 缓存磁盘状态 {"sda": "活动中", ...}
        self.disk_full_info_cache = {}  # 缓存磁盘完整信息
        self.first_run = True  # 首次运行标志
        self.initial_detection_done = False  # 首次完整检测完成标志
        self.disk_io_stats_cache = {}  # 缓存磁盘I/O统计信息
    
    def extract_value(self, text: str, patterns, default="未知", format_func=None):
        if not text:
            return default
        
        if not isinstance(patterns, list):
            patterns = [patterns]
            
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            if matches:
                value = matches[0]
                try:
                    return format_func(value) if format_func else value.strip()
                except Exception as e:
                    self.logger.debug("Format error for value '%s': %s", value, str(e))
                    return value.strip()
        
        self.logger.debug("No match found for patterns: %s", patterns)
        return default
    
    def _format_capacity(self, capacity_str: str) -> str:
        """将容量字符串格式化为GB或TB格式"""
        if not capacity_str or capacity_str == "未知":
            return "未知"
        
        try:
            # 处理逗号分隔的数字（如 "1,000,204,886,016 bytes"）
            capacity_str = capacity_str.replace(',', '')
            
            # 提取数字和单位
            import re
            # 匹配数字和单位（如 "500 GB", "1.0 TB", "1000204886016 bytes", "1,000,204,886,016 bytes"）
            match = re.search(r'(\d+(?:\.\d+)?)\s*([KMGT]?B|bytes?)', capacity_str, re.IGNORECASE)
            if not match:
                # 如果没有匹配到单位，尝试直接提取数字
                numbers = re.findall(r'\d+', capacity_str)
                if numbers:
                    # 取最大的数字（通常是容量值）
                    value = float(max(numbers, key=len))
                    bytes_value = value  # 假设为字节
                else:
                    return capacity_str
            else:
                value = float(match.group(1))
                unit = match.group(2).upper()
                
                # 转换为字节
                if unit in ['B', 'BYTE', 'BYTES']:
                    bytes_value = value
                elif unit in ['KB', 'KIB']:
                    bytes_value = value * 1024
                elif unit in ['MB', 'MIB']:
                    bytes_value = value * 1024 * 1024
                elif unit in ['GB', 'GIB']:
                    bytes_value = value * 1024 * 1024 * 1024
                elif unit in ['TB', 'TIB']:
                    bytes_value = value * 1024 * 1024 * 1024 * 1024
                else:
                    bytes_value = value  # 默认假设为字节
            
            # 转换为合适的单位
            if bytes_value >= 1024**4:  # 1 TB
                return f"{bytes_value / (1024**4):.1f} TB"
            elif bytes_value >= 1024**3:  # 1 GB
                return f"{bytes_value / (1024**3):.1f} GB"
            elif bytes_value >= 1024**2:  # 1 MB
                return f"{bytes_value / (1024**2):.1f} MB"
            elif bytes_value >= 1024:  # 1 KB
                return f"{bytes_value / 1024:.1f} KB"
            else:
                return f"{bytes_value:.1f} B"
                
        except Exception as e:
            self.logger.debug(f"格式化容量失败: {capacity_str}, 错误: {e}")
            return capacity_str
    
    async def check_disk_active(self, device: str, window: int = 30) -> bool:
        """检查硬盘在指定时间窗口内是否有活动"""
        try:
            # 首先检查硬盘当前状态
            current_status = await self.get_disk_activity(device)
            
            # 如果硬盘处于休眠状态，直接返回非活跃
            if current_status == "休眠中":
                self.logger.debug(f"硬盘 {device} 处于休眠状态，不执行详细检测")
                return False
            
            # 如果硬盘处于空闲状态，检查是否有近期活动
            if current_status == "空闲中":
                # 检查缓存的统计信息来判断近期活动
                stat_path = f"/sys/block/{device}/stat"
                stat_output = await self.coordinator.run_command(f"cat {stat_path} 2>/dev/null")
                
                if stat_output:
                    stats = stat_output.split()
                    if len(stats) >= 11:
                        try:
                            current_read_ios = int(stats[0])
                            current_write_ios = int(stats[4])
                            current_io_ticks = int(stats[9])
                            
                            cached_stats = self.disk_io_stats_cache.get(device)
                            if cached_stats:
                                read_diff = current_read_ios - cached_stats.get('read_ios', 0)
                                write_diff = current_write_ios - cached_stats.get('write_ios', 0)
                                io_ticks_diff = current_io_ticks - cached_stats.get('io_ticks', 0)
                                
                                # 如果在最近30秒内有I/O活动，认为硬盘活跃
                                if read_diff > 0 or write_diff > 0 or io_ticks_diff > 100:
                                    self.logger.debug(f"硬盘 {device} 近期有I/O活动，需要更新信息")
                                    return True
                            
                            # 更新缓存
                            self.disk_io_stats_cache[device] = {
                                'read_ios': current_read_ios,
                                'write_ios': current_write_ios,
                                'io_ticks': current_io_ticks
                            }
                            
                        except (ValueError, IndexError):
                            pass
                
                # 如果硬盘空闲且没有近期活动，返回非活跃
                self.logger.debug(f"硬盘 {device} 处于空闲状态且无近期活动，不执行详细检测")
                return False
            
            # 如果硬盘处于活动中，返回活跃状态
            if current_status == "活动中":
                self.logger.debug(f"硬盘 {device} 处于活动中，执行详细检测")
                return True
            
            # 默认情况下返回活跃状态
            self.logger.debug(f"硬盘 {device} 状态未知，默认执行详细检测")
            return True
                
        except Exception as e:
            self.logger.error(f"检测硬盘活动状态失败: {str(e)}")
            return True  # 出错时默认执行检测
    
    async def get_disk_power_state(self, device: str) -> str:
        """获取硬盘电源状态"""
        try:
            # 检查 SCSI 设备状态
            state_path = f"/sys/block/{device}/device/state"
            state_output = await self.coordinator.run_command(f"cat {state_path} 2>/dev/null || echo 'unknown'")
            state = state_output.strip().lower()
            
            if state in ["running", "active"]:
                return "active"
            elif state in ["standby", "sleep"]:
                return state
            
            # 对于某些设备，尝试通过hdparm检查状态（非侵入性）
            hdparm_output = await self.coordinator.run_command(f"hdparm -C /dev/{device} 2>/dev/null || echo 'unknown'")
            if "standby" in hdparm_output.lower():
                return "standby" 
            elif "sleeping" in hdparm_output.lower():
                return "sleep"
            elif "active/idle" in hdparm_output.lower():
                return "active"
            
            return "unknown"
            
        except Exception as e:
            self.logger.debug(f"获取磁盘 {device} 电源状态失败: {e}")
            return "unknown"
    
    async def get_disk_activity(self, device: str) -> str:
        """获取硬盘活动状态（活动中/空闲中/休眠中）"""
        try:
            # 先检查电源状态
            power_state = await self.get_disk_power_state(device)
            if power_state in ["standby", "sleep"]:
                return "休眠中"
            
            # 检查最近的I/O活动 - 使用非侵入性方式
            stat_path = f"/sys/block/{device}/stat"
            stat_output = await self.coordinator.run_command(f"cat {stat_path} 2>/dev/null")
            
            if stat_output:
                stats = stat_output.split()
                if len(stats) >= 11:
                    try:
                        in_flight = int(stats[8])  # 当前进行中的I/O
                        io_ticks = int(stats[9])   # I/O活动时间(ms)
                        
                        # 如果有正在进行的I/O，返回活动中
                        if in_flight > 0:
                            self.logger.debug(f"硬盘 {device} 有进行中的I/O操作: {in_flight}")
                            return "活动中"
                        
                        # 检查缓存的统计信息来判断近期活动
                        cached_stats = self.disk_io_stats_cache.get(device)
                        if cached_stats:
                            current_read_ios = int(stats[0])
                            current_write_ios = int(stats[4])
                            
                            read_diff = current_read_ios - cached_stats.get('read_ios', 0)
                            write_diff = current_write_ios - cached_stats.get('write_ios', 0)
                            io_ticks_diff = io_ticks - cached_stats.get('io_ticks', 0)
                            
                            # 如果在最近30秒内有I/O活动，认为硬盘活动中
                            if read_diff > 0 or write_diff > 0 or io_ticks_diff > 100:  # 100ms内的活动
                                self.logger.debug(f"硬盘 {device} 近期有I/O活动: 读={read_diff}, 写={write_diff}, 活动时间={io_ticks_diff}ms")
                                
                                # 更新缓存统计信息
                                self.disk_io_stats_cache[device] = {
                                    'read_ios': current_read_ios,
                                    'write_ios': current_write_ios,
                                    'in_flight': in_flight,
                                    'io_ticks': io_ticks
                                }
                                return "活动中"
                        else:
                            # 首次检测，保存当前状态并认为活跃
                            self.logger.debug(f"硬盘 {device} 首次检测，保存统计信息")
                            self.disk_io_stats_cache[device] = {
                                'read_ios': int(stats[0]),
                                'write_ios': int(stats[4]),
                                'in_flight': in_flight,
                                'io_ticks': io_ticks
                            }
                            return "活动中"  # 首次检测默认返回活动中
                        
                        # 更新缓存统计信息
                        self.disk_io_stats_cache[device] = {
                            'read_ios': int(stats[0]),
                            'write_ios': int(stats[4]),
                            'in_flight': in_flight,
                            'io_ticks': io_ticks
                        }
                        
                        # 如果没有活动，返回空闲中
                        self.logger.debug(f"硬盘 {device} 处于空闲状态")
                        return "空闲中"
                        
                    except (ValueError, IndexError) as e:
                        self.logger.debug(f"解析硬盘 {device} 统计信息失败: {e}")
                        return "活动中"  # 出错时默认返回活动中，避免中断休眠
            
            # 如果无法获取统计信息，默认返回活动中
            self.logger.debug(f"无法获取硬盘 {device} 的统计信息，默认返回活动中")
            return "活动中"
            
        except Exception as e:
            self.logger.error(f"获取硬盘 {device} 状态失败: {str(e)}", exc_info=True)
            return "活动中"  # 出错时默认返回活动中，避免中断休眠
    
    async def get_disks_info(self) -> list[dict]:
        disks = []
        try:
            self.logger.debug("Fetching disk list...")
            lsblk_output = await self.coordinator.run_command("lsblk -dno NAME,TYPE")
            self.logger.debug("lsblk output: %s", lsblk_output)
            
            devices = []
            for line in lsblk_output.splitlines():
                if line:
                    parts = line.split()
                    if len(parts) >= 2:
                        devices.append({"name": parts[0], "type": parts[1]})
            
            self.logger.debug("Found %d block devices", len(devices))
            
            ignore_list = self.coordinator.config.get(CONF_IGNORE_DISKS, "").split(",")
            self.logger.debug("Ignoring disks: %s", ignore_list)
            
            for dev_info in devices:
                device = dev_info["name"]
                if device in ignore_list:
                    self.logger.debug("Skipping ignored disk: %s", device)
                    continue
                    
                if dev_info["type"] not in ["disk", "nvme", "rom"]:
                    self.logger.debug("Skipping non-disk device: %s (type: %s)", device, dev_info["type"])
                    continue
                
                device_path = f"/dev/{device}"
                disk_info = {"device": device}
                self.logger.debug("Processing disk: %s", device)
                
                # 获取硬盘状态（活动中/空闲中/休眠中）
                status = await self.get_disk_activity(device)
                disk_info["status"] = status
                
                # 更新状态缓存
                self.disk_status_cache[device] = status
                
                # 检查是否有缓存的完整信息
                cached_info = self.disk_full_info_cache.get(device, {})
                
                # 优化点：首次运行时强制获取完整信息
                if self.first_run:
                    self.logger.debug(f"首次运行，强制获取硬盘 {device} 的完整信息")
                    try:
                        # 执行完整的信息获取
                        await self._get_full_disk_info(disk_info, device_path)
                        # 更新缓存
                        self.disk_full_info_cache[device] = disk_info.copy()
                    except Exception as e:
                        self.logger.warning(f"首次运行获取硬盘信息失败: {str(e)}", exc_info=True)
                        # 使用缓存信息（如果有）
                        disk_info.update(cached_info)
                        disk_info.update({
                            "model": "未知" if not cached_info.get("model") else cached_info["model"],
                            "serial": "未知" if not cached_info.get("serial") else cached_info["serial"],
                            "capacity": "未知" if not cached_info.get("capacity") else cached_info["capacity"],
                            "health": "检测失败" if not cached_info.get("health") else cached_info["health"],
                            "temperature": "未知" if not cached_info.get("temperature") else cached_info["temperature"],
                            "power_on_hours": "未知" if not cached_info.get("power_on_hours") else cached_info["power_on_hours"],
                            "attributes": cached_info.get("attributes", {})
                        })
                    disks.append(disk_info)
                    continue
                
                # 检查硬盘是否活跃
                is_active = await self.check_disk_active(device, window=30)
                if not is_active:
                    self.logger.debug(f"硬盘 {device} 处于非活跃状态，使用上一次获取的信息")
                    
                    # 优先使用缓存的完整信息
                    if cached_info:
                        disk_info.update({
                            "model": cached_info.get("model", "未检测"),
                            "serial": cached_info.get("serial", "未检测"),
                            "capacity": cached_info.get("capacity", "未检测"),
                            "health": cached_info.get("health", "未检测"),
                            "temperature": cached_info.get("temperature", "未检测"),
                            "power_on_hours": cached_info.get("power_on_hours", "未检测"),
                            "attributes": cached_info.get("attributes", {})
                        })
                    else:
                        # 如果没有缓存信息，使用默认值
                        disk_info.update({
                            "model": "未检测",
                            "serial": "未检测",
                            "capacity": "未检测",
                            "health": "未检测",
                            "temperature": "未检测",
                            "power_on_hours": "未检测",
                            "attributes": {}
                        })
                    
                    disks.append(disk_info)
                    continue
                
                try:
                    # 执行完整的信息获取
                    await self._get_full_disk_info(disk_info, device_path)
                    # 更新缓存
                    self.disk_full_info_cache[device] = disk_info.copy()
                except Exception as e:
                    self.logger.warning(f"获取硬盘信息失败: {str(e)}", exc_info=True)
                    # 使用缓存信息（如果有）
                    disk_info.update(cached_info)
                    disk_info.update({
                        "model": "未知" if not cached_info.get("model") else cached_info["model"],
                        "serial": "未知" if not cached_info.get("serial") else cached_info["serial"],
                        "capacity": "未知" if not cached_info.get("capacity") else cached_info["capacity"],
                        "health": "检测失败" if not cached_info.get("health") else cached_info["health"],
                        "temperature": "未知" if not cached_info.get("temperature") else cached_info["temperature"],
                        "power_on_hours": "未知" if not cached_info.get("power_on_hours") else cached_info["power_on_hours"],
                        "attributes": cached_info.get("attributes", {})
                    })
                
                disks.append(disk_info)
                self.logger.debug("Processed disk %s: %s", device, disk_info)
            
            # 首次运行完成后标记
            if self.first_run:
                self.first_run = False
                self.initial_detection_done = True
                self.logger.info("首次磁盘检测完成")
            
            self.logger.info("Found %d disks after processing", len(disks))
            return disks
        
        except Exception as e:
            self.logger.error("Failed to get disk info: %s", str(e), exc_info=True)
            return []
    
    async def _get_full_disk_info(self, disk_info, device_path):
        """获取硬盘的完整信息（模型、序列号、健康状态等）"""
        # 获取基本信息 - 首先尝试NVMe格式
        info_output = await self.coordinator.run_command(f"smartctl -i {device_path}")
        self.logger.debug("smartctl -i output for %s: %s", disk_info["device"], info_output[:200] + "..." if len(info_output) > 200 else info_output)
        
        # 检查是否为NVMe设备
        is_nvme = "nvme" in disk_info["device"].lower()
        
        # 模型 - 增强NVMe支持
        disk_info["model"] = self.extract_value(
            info_output, 
            [
                r"Device Model:\s*(.+)",
                r"Model(?: Family)?\s*:\s*(.+)",
                r"Model\s*Number:\s*(.+)",
                r"Product:\s*(.+)",  # NVMe格式
                r"Model Number:\s*(.+)",  # NVMe格式
            ]
        )
        
        # 序列号 - 增强NVMe支持
        disk_info["serial"] = self.extract_value(
            info_output, 
            [
                r"Serial Number\s*:\s*(.+)",
                r"Serial Number:\s*(.+)",  # NVMe格式
                r"Serial\s*:\s*(.+)",  # NVMe格式
            ]
        )
        
        # 容量 - 增强NVMe支持并转换为GB/TB格式
        capacity_patterns = [
            r"User Capacity:\s*([^[]+)",
            r"Namespace 1 Size/Capacity:\s*([^[]+)",  # NVMe格式
            r"Total NVM Capacity:\s*([^[]+)",  # NVMe格式
            r"Capacity:\s*([^[]+)",  # NVMe格式
        ]
        
        raw_capacity = self.extract_value(info_output, capacity_patterns)
        disk_info["capacity"] = self._format_capacity(raw_capacity)
        
        # 健康状态
        health_output = await self.coordinator.run_command(f"smartctl -H {device_path}")
        raw_health = self.extract_value(
            health_output,
            [
                r"SMART overall-health self-assessment test result:\s*(.+)",
                r"SMART Health Status:\s*(.+)"
            ],
            default="UNKNOWN"
        )

        # 健康状态中英文映射
        health_map = {
            "PASSED": "良好",
            "PASS": "良好",
            "OK": "良好",
            "GOOD": "良好",
            "FAILED": "故障",
            "FAIL": "故障",
            "ERROR": "错误",
            "WARNING": "警告",
            "CRITICAL": "严重",
            "UNKNOWN": "未知",
            "NOT AVAILABLE": "不可用"
        }

        # 转换为中文（不区分大小写）
        disk_info["health"] = health_map.get(raw_health.strip().upper(), "未知")
        
        # 获取详细数据
        data_output = await self.coordinator.run_command(f"smartctl -A {device_path}")
        self.logger.debug("smartctl -A output for %s: %s", disk_info["device"], data_output[:200] + "..." if len(data_output) > 200 else data_output)
        
        # 智能温度检测逻辑 - 处理多温度属性
        temp_patterns = [
            # 新增的NVMe专用模式
            r"Temperature:\s*(\d+)\s*Celsius",  # 匹配 NVMe 格式
            r"Composite:\s*\+?(\d+\.?\d*)°C",    # 匹配 NVMe 复合温度
            # 优先匹配属性194行（通常包含当前温度）
            r"194\s+Temperature_Celsius\s+.*?(\d+)\s*(?:$|$)",
            
            # 匹配其他温度属性
            r"\bTemperature_Celsius\b.*?(\d+)\b",
            r"Current Temperature:\s*(\d+)",
            r"Airflow_Temperature_Cel\b.*?(\d+)\b",
            r"Temp\s*[=:]\s*(\d+)"
        ]
        
        # 查找所有温度值
        temperatures = []
        for pattern in temp_patterns:
            matches = re.findall(pattern, data_output, re.IGNORECASE | re.MULTILINE)
            if matches:
                for match in matches:
                    try:
                        temperatures.append(int(match))
                    except ValueError:
                        pass
        
        # 优先选择属性194的温度值，如果没有则选择最大值
        if temperatures:
            # 优先选择属性194的值（如果存在）
            primary_match = re.search(r"194\s+Temperature_Celsius\s+.*?(\d+)\s*(?:\(|$)", 
                                    data_output, re.IGNORECASE | re.MULTILINE)
            if primary_match:
                disk_info["temperature"] = f"{primary_match.group(1)} °C"
            else:
                # 选择最高温度值（通常是当前温度）
                disk_info["temperature"] = f"{max(temperatures)} °C"
        else:
            disk_info["temperature"] = "未知"
        
        # 改进的通电时间检测逻辑 - 处理特殊格式
        power_on_hours = "未知"
        
        # 检查是否为NVMe设备
        is_nvme = "nvme" in disk_info["device"].lower()
        
        # 方法0：NVMe设备的通电时间提取（优先处理）
        if is_nvme:
            # NVMe格式的通电时间提取 - 支持带逗号的数字格式
            nvme_patterns = [
                r"Power On Hours\s*:\s*([\d,]+)",  # 支持带逗号的数字格式（如 "6,123"）
                r"Power On Time\s*:\s*([\d,]+)",  # NVMe备用格式
                r"Power on hours\s*:\s*([\d,]+)",  # 小写格式
                r"Power on time\s*:\s*([\d,]+)",  # 小写格式
            ]
            
            for pattern in nvme_patterns:
                match = re.search(pattern, data_output, re.IGNORECASE)
                if match:
                    try:
                        # 处理带逗号的数字格式（如 "6,123"）
                        hours_str = match.group(1).replace(',', '')
                        hours = int(hours_str)
                        power_on_hours = f"{hours} 小时"
                        self.logger.debug("Found NVMe power_on_hours via pattern %s: %s", pattern, power_on_hours)
                        break
                    except:
                        continue
            
            # 如果还没找到，尝试在SMART数据部分查找
            if power_on_hours == "未知":
                # 查找SMART数据部分中的Power On Hours
                smart_section_match = re.search(r"SMART/Health Information.*?Power On Hours\s*:\s*([\d,]+)", 
                                               data_output, re.IGNORECASE | re.DOTALL)
                if smart_section_match:
                    try:
                        hours_str = smart_section_match.group(1).replace(',', '')
                        hours = int(hours_str)
                        power_on_hours = f"{hours} 小时"
                        self.logger.debug("Found NVMe power_on_hours in SMART section: %s", power_on_hours)
                    except:
                        pass
        
        # 方法1：提取属性9的RAW_VALUE（处理特殊格式）
        attr9_match = re.search(
            r"^\s*9\s+Power_On_Hours\b[^\n]+\s+(\d+)h(?:\+(\d+)m(?:\+(\d+)\.\d+s)?)?",
            data_output, re.IGNORECASE | re.MULTILINE
        )
        if attr9_match:
            try:
                hours = int(attr9_match.group(1))
                # 如果有分钟部分，转换为小时的小数部分
                if attr9_match.group(2):
                    minutes = int(attr9_match.group(2))
                    hours += minutes / 60
                power_on_hours = f"{hours:.1f} 小时"
                self.logger.debug("Found power_on_hours via method1: %s", power_on_hours)
            except:
                pass
        
        # 方法2：如果方法1失败，尝试提取纯数字格式
        if power_on_hours == "未知":
            attr9_match = re.search(
                r"^\s*9\s+Power_On_Hours\b[^\n]+\s+(\d+)\s*$",
                data_output, re.IGNORECASE | re.MULTILINE
            )
            if attr9_match:
                try:
                    power_on_hours = f"{int(attr9_match.group(1))} 小时"
                    self.logger.debug("Found power_on_hours via method2: %s", power_on_hours)
                except:
                    pass
        
        # 方法3：如果前两种方法失败，使用原来的多模式匹配
        if power_on_hours == "未知":
            power_on_hours = self.extract_value(
                data_output,
                [
                    # 精确匹配属性9行
                    r"^\s*9\s+Power_On_Hours\b[^\n]+\s+(\d+)\s*$",
                    r"^\s*9\s+Power On Hours\b[^\n]+\s+(\d+)h(?:\+(\d+)m(?:\+(\d+)\.\d+s)?)?",
                    # 通用匹配模式
                    r"9\s+Power_On_Hours\b.*?(\d+)\b",
                    r"Power_On_Hours\b.*?(\d+)\b",
                    r"Power On Hours\s+(\d+)",
                    r"Power on time\s*:\s*(\d+)\s*hours"
                ],
                default="未知",
                format_func=lambda x: f"{int(x)} 小时"
            )
            if power_on_hours != "未知":
                self.logger.debug("Found power_on_hours via method3: %s", power_on_hours)
        
        # 方法4：如果还没找到，尝试扫描整个属性表
        if power_on_hours == "未知":
            for line in data_output.split('\n'):
                if "Power_On_Hours" in line:
                    # 尝试提取特殊格式
                    match = re.search(r"(\d+)h(?:\+(\d+)m(?:\+(\d+)\.\d+s)?)?", line)
                    if match:
                        try:
                            hours = int(match.group(1))
                            if match.group(2):
                                minutes = int(match.group(2))
                                hours += minutes / 60
                            power_on_hours = f"{hours:.1f} 小时"
                            self.logger.debug("Found power_on_hours via method4 (special format): %s", power_on_hours)
                            break
                        except:
                            pass
                            
                    # 尝试提取纯数字
                    fields = line.split()
                    if fields and fields[-1].isdigit():
                        try:
                            power_on_hours = f"{int(fields[-1])} 小时"
                            self.logger.debug("Found power_on_hours via method4 (numeric): %s", power_on_hours)
                            break
                        except:
                            pass
        
        disk_info["power_on_hours"] = power_on_hours
        
        # 添加额外属性：温度历史记录
        temp_history = {}
        # 提取属性194的温度历史
        temp194_match = re.search(r"194\s+Temperature_Celsius+.*?\(\s*([\d\s]+)$", data_output)
        if temp194_match:
            try:
                values = [int(x) for x in temp194_match.group(1).split()]
                if len(values) >= 4:
                    temp_history = {
                        "最低温度": f"{values[0]} °C",
                        "最高温度": f"{values[1]} °C",
                        "当前温度": f"{values[2]} °C",
                        "阈值": f"{values[3]} °C" if len(values) > 3 else "N/A"
                    }
            except:
                pass
        
        # 保存额外属性
        disk_info["attributes"] = temp_history