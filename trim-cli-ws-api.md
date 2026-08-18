# TRIM NAS WebSocket API 文档

## 概述

TRIM NAS（fnOS）通过 WebSocket 提供命令行管理接口。本文档整理了 trim-cli 技能使用的 WS 协议接口，供其他客户端集成使用。

## 连接信息

### 默认端口

| 场景 | 协议 | 端口 | 说明 |
|------|------|------|------|
| 本地回环 | ws:// | 5666 | 默认 localhost |
| 远程 IP | wss:// | 5667 | 需要 TLS |
| 远程域名 | wss:// | 443 | 标准 HTTPS 端口 |

### WebSocket 端点

```
wss://<host>:<port>/websocket?type=main
```

### TLS 配置

- 内网或自签证书需要 `--tls-insecure` 或禁用证书验证
- 远程明文 `ws://` 需要显式允许不安全连接

## 认证流程

### 1. 密码登录 (user.login)

**Endpoint:** `user.login`

**请求:**
```json
{
  "req": "user.login",
  "reqid": "<生成的请求ID>",
  "user": "username",
  "password": "password",
  "stay": 1,
  "deviceName": "fnOS CLI",
  "deviceType": "CLI",
  "did": "<设备ID>"
}
```

**响应:**
```json
{
  "result": "succ",
  "token": "短期会话令牌",
  "longToken": "长期令牌",
  "backId": "请求ID backId 分量",
  "secret": "HMAC签名密钥(base64)",
  "uid": 1000,
  "admin": true
}
```

### 2. 令牌恢复 (user.authToken)

**Endpoint:** `user.authToken`

**请求:**
```json
{
  "req": "user.authToken",
  "reqid": "<生成的请求ID>",
  "token": "<短期会话令牌>",
  "main": true,
  "active": true,
  "si": "<会话完整性盐>"
}
```

### 3. 长期令牌恢复 (user.tokenLogin)

**Endpoint:** `user.tokenLogin`

当短期令牌失效时使用。

**请求:**
```json
{
  "req": "user.tokenLogin",
  "reqid": "<生成的请求ID>",
  "token": "<长期令牌>",
  "deviceName": "fnOS CLI",
  "deviceType": "CLI",
  "si": "<会话完整性盐>"
}
```

### 4. 登出 (user.logout)

**Endpoint:** `user.logout`

**请求:**
```json
{
  "req": "user.logout",
  "reqid": "<生成的请求ID>"
}
```

## HMAC 签名机制

### 签名格式

当 session 中存在 `secret` 时，非直通请求需要 HMAC-SHA256 签名：

```
<base64-hmac-signature><json-body>
```

### 签名密钥

- `secret` 是 base64 编码，解码后用作 HMAC 密钥
- 签名前会在 JSON 中注入 `si`（会话完整性盐）

### 直通请求

以下请求不需要签名：
- `user.login`
- `user.authToken`（使用 token 时）

## 请求格式

### 通用请求结构

```json
{
  "req": "<endpoint>",
  "reqid": "<请求关联ID>",
  ...其他参数
}
```

### 请求 ID 生成

请求 ID 通常是 fnOS 兼容的生成 ID，格式如：
```
69ba234069ba2df8000004c40001
```

## 响应格式

### 通用响应信封

```json
{
  "result": "succ|fail",
  "errno": 0,
  "errmsg": "错误描述",
  ...其他字段
}
```

### 多包响应

某些端点（如 `file.ls`、`appcgi.finder.fileSearch`）返回多包响应：

- 中间包：携带 `data` 或 `files`，`result` 可能为 `doing`
- 终态包：包含 `result: succ/fail`

### 成功判定

- `result: succ` 或 `errno: 0` 表示成功
- `result: fail` 或非零 `errno` 表示失败

## API 模块

### 系统信息 (appcgi.sysinfo.*)

#### 获取机器类型

**Endpoint:** `appcgi.sysinfo.getTrimMachineType`

```json
{"req": "appcgi.sysinfo.getTrimMachineType", "reqid": "..."}
```

#### 其他只读端点

| Endpoint | 用途 |
|----------|------|
| `appcgi.sysinfo.getTrimVersion` | 系统版本 |
| `appcgi.sysinfo.getKernelVersion` | 内核版本 |
| `appcgi.sysinfo.getHostName` | 主机名 |
| `appcgi.sysinfo.getMachineId` | 机器 ID |
| `appcgi.sysinfo.getUptime` | 运行时间 |
| `appcgi.sysinfo.getAllVolsInfo` | 全部卷信息 |
| `appcgi.sysinfo.getVolsList` | 卷列表 |
| `appcgi.sysinfo.getDockerInfo` | Docker 信息 |
| `appcgi.sysinfo.getUnixTime` | Unix 时间 |
| `appcgi.sysinfo.getHardwareInfo` | 硬件信息 |
| `appcgi.sysinfo.getTrimDisk` | 系统盘信息 |

### 资源监控 (appcgi.resmon.*)

#### CPU 监控

**Endpoint:** `appcgi.resmon.cpu`

```json
{"req": "appcgi.resmon.cpu", "reqid": "..."}
```

**响应:**
```json
{
  "data": {"usage": 37, "cores": 4},
  "result": "succ"
}
```

#### 内存监控

**Endpoint:** `appcgi.resmon.mem`

```json
{"req": "appcgi.resmon.mem", "reqid": "..."}
```

#### 其他监控端点

| Endpoint | 用途 | 参数 |
|----------|------|------|
| `appcgi.resmon.gen` | 聚合指标 | `item`: 字符串数组 |
| `appcgi.resmon.net` | 网络指标 | 无 |
| `appcgi.resmon.disk` | 磁盘指标 | 无 |
| `appcgi.resmon.gpu` | GPU 指标 | 无 |
| `appcgi.resmon.proc.list` | 进程列表 | `uid`: 非负整数 |
| `appcgi.resmon.proc.info` | 进程详情 | `pids`: 正整数数组 |
| `appcgi.resmon.sysWarn` | 系统告警 | 无 |
| `appcgi.resmon.battery` | 电池状态 | 无 |
| `appcgi.resmon.sysFan` | 系统风扇 | 无 |

### 文件操作 (file.*)

#### 列出文件

**Endpoint:** `file.ls`

```json
{"req": "file.ls", "reqid": "...", "path": "/vol1/downloads"}
```

**响应（多包）:**
```json
{"files": [{"name": "file.txt", "dir": 0, "size": 1234}]}
{"result": "succ"}
```

#### 创建目录

**Endpoint:** `file.mkdir`

```json
{"req": "file.mkdir", "reqid": "...", "path": "/vol2/1106/new-dir"}
```

#### 删除文件

**Endpoint:** `file.rm`

```json
{"req": "file.rm", "reqid": "...", "files": ["/vol2/1106/old-dir"]}
```

#### 复制文件

**Endpoint:** `file.cp`

```json
{
  "req": "file.cp",
  "reqid": "...",
  "files": ["/vol3/1106/source"],
  "pathTo": "/vol4/1106/backup",
  "overwrite": 2
}
```

#### 移动文件

**Endpoint:** `file.mv`

```json
{
  "req": "file.mv",
  "reqid": "...",
  "files": ["/vol4/1106/source"],
  "pathTo": "/vol2/1106/archive",
  "overwrite": 2
}
```

#### 重命名

**Endpoint:** `file.rename`

```json
{
  "req": "file.rename",
  "reqid": "...",
  "path": "/vol2/1106/old.txt",
  "newName": "new.txt"
}
```

#### 搜索文件

**Endpoint:** `appcgi.finder.fileSearch`

```json
{
  "req": "appcgi.finder.fileSearch",
  "reqid": "...",
  "key": ".txt",
  "path": ["vol2/1000"],
  "uid": 1000
}
```

**响应（多包）:**
```json
{"data": [{"path": "/vol2/1000/a.txt"}], "result": "doing"}
{"result": "succ"}
```

#### 文件属性

**Endpoint:** `file.prop`

```json
{"req": "file.prop", "reqid": "...", "files": ["/vol2/1106/a.txt"]}
```

#### 文件大小

**Endpoint:** `file.size`

```json
{"req": "file.size", "reqid": "...", "file": "/vol2/1106/a.txt"}
```

#### 下载链接

**Endpoint:** `file.download`

```json
{"req": "file.download", "reqid": "...", "files": ["/vol2/1106/a.txt"]}
```

#### 上传前检查

**Endpoint:** `file.checkUpload`

```json
{
  "req": "file.checkUpload",
  "reqid": "...",
  "path": "/vol2/1106/new.jpg",
  "size": 12345,
  "overwrite": 2
}
```

**响应:**
```json
{
  "result": "succ",
  "uploadName": "new.jpg.~#2",
  "from": 0
}
```

#### 回收站

**Endpoint:** `file.trash.list`
```json
{"req": "file.trash.list", "reqid": "..."}
```

**Endpoint:** `file.trash.restore`
```json
{
  "req": "file.trash.restore",
  "reqid": "...",
  "files": ["/vol2/1106/a.txt"],
  "overwrite": 2
}
```

**Endpoint:** `file.trash.clear`
```json
{"req": "file.trash.clear", "reqid": "..."}
```

#### 共享目录

**Endpoint:** `file.share.list`
```json
{"req": "file.share.list", "reqid": "...", "uid": 1001}
```

**Endpoint:** `file.share.info`
```json
{"req": "file.share.info", "reqid": "...", "path": "/vol1/1000/docs"}
```

**Endpoint:** `file.share.add2`
```json
{
  "req": "file.share.add2",
  "reqid": "...",
  "path": "/vol1/1000/docs",
  "shareName": "docs",
  "permset": [{"owner": 32719, "inherit": 7}]
}
```

**Endpoint:** `file.share.del2`
```json
{
  "req": "file.share.del2",
  "reqid": "...",
  "path": "/vol1/1000/docs"
}
```

#### ACL 操作

**Endpoint:** `file.getAcl`
```json
{"req": "file.getAcl", "reqid": "...", "path": "/vol1/1000/docs", "getProp": true}
```

**Endpoint:** `file.setAcl2`
```json
{
  "req": "file.setAcl2",
  "reqid": "...",
  "path": "/vol1/1000/a.txt",
  "permset": [],
  "sub": 0
}
```

**Endpoint:** `file.chown`
```json
{
  "req": "file.chown",
  "reqid": "...",
  "path": "/vol1/1000/a.txt",
  "uid": 1000
}
```

### 用户管理 (user.*)

#### 用户列表

**Endpoint:** `user.list`

```json
{"req": "user.list", "reqid": "...", "uver": 0}
```

#### 用户信息

**Endpoint:** `user.info`

```json
{"req": "user.info", "reqid": "...", "user": "alice"}
```

#### 创建用户

**Endpoint:** `user.add`

```json
{
  "req": "user.add",
  "reqid": "...",
  "user": "alice",
  "password": "initial_password",
  "groups": ["Users", "Administrators"],
  "comment": "Alice",
  "email": "alice@example.com"
}
```

#### 修改用户

**Endpoint:** `user.mod`

```json
{
  "req": "user.mod",
  "reqid": "...",
  "user": "alice",
  "newName": "alice2",
  "groups": ["Users"],
  "comment": "Updated"
}
```

#### 删除用户

**Endpoint:** `user.del`

```json
{"req": "user.del", "reqid": "...", "user": "alice"}
```

#### 修改密码

**Endpoint:** `user.changePassword`

```json
{
  "req": "user.changePassword",
  "reqid": "...",
  "user": "os_cli",
  "password": "old_password",
  "newPassword": "new_password",
  "removeToken": true
}
```

#### 用户组操作

**Endpoint:** `user.groupList`
```json
{"req": "user.groupList", "reqid": "..."}
```

**Endpoint:** `user.groupInfo`
```json
{"req": "user.groupInfo", "reqid": "...", "group": "Administrators"}
```

**Endpoint:** `user.groupAdd`
```json
{
  "req": "user.groupAdd",
  "reqid": "...",
  "group": "devops",
  "comment": "DevOps Team"
}
```

**Endpoint:** `user.groupMod`
```json
{
  "req": "user.groupMod",
  "reqid": "...",
  "group": "devops",
  "newName": "devops-core",
  "comment": "Core DevOps Team"
}
```

**Endpoint:** `user.groupDel`
```json
{"req": "user.groupDel", "reqid": "...", "group": "devops-core"}
```

**Endpoint:** `user.groupSetUsers`
```json
{
  "req": "user.groupSetUsers",
  "reqid": "...",
  "group": "devops-core",
  "users": ["alice", "bob", "carol"]
}
```

**Endpoint:** `user.groupAddUsers`
```json
{
  "req": "user.groupAddUsers",
  "reqid": "...",
  "group": "devops-core",
  "users": ["dave", "erin"]
}
```

**Endpoint:** `user.groupDelUsers`
```json
{
  "req": "user.groupDelUsers",
  "reqid": "...",
  "group": "devops-core",
  "users": ["frank"]
}
```

### 存储管理 (stor.*)

#### 存储总览

**Endpoint:** `stor.general`

```json
{"req": "stor.general", "reqid": "..."}
```

#### 存储池列表

**Endpoint:** `stor.listStor`

```json
{"req": "stor.listStor", "reqid": "..."}
```

#### 磁盘列表

**Endpoint:** `stor.listDisk`

```json
{"req": "stor.listDisk", "reqid": "..."}
```

#### 可用磁盘

**Endpoint:** `stor.listFreeDisk`

```json
{"req": "stor.listFreeDisk", "reqid": "..."}
```

#### 创建存储池

**Endpoint:** `stor.create`

```json
{
  "req": "stor.create",
  "reqid": "...",
  "level": 5,
  "disks": ["sda", "sdb", "sdc"],
  "fstype": "btrfs",
  "comment": "My Pool",
  "password": "verification_password"
}
```

#### 挂载存储池

**Endpoint:** `stor.mount`

```json
{"req": "stor.mount", "reqid": "...", "uuid": "trim_pool"}
```

#### 卸载存储池

**Endpoint:** `stor.umount`

```json
{"req": "stor.umount", "reqid": "...", "uuid": "trim_pool", "password": "pwd"}
```

#### 添加磁盘

**Endpoint:** `stor.addDisk`

```json
{
  "req": "stor.addDisk",
  "reqid": "...",
  "uuid": "trim_pool",
  "disks": ["sdc", "sdd"],
  "password": "pwd"
}
```

#### 移除磁盘

**Endpoint:** `stor.removeDisk`

```json
{
  "req": "stor.removeDisk",
  "reqid": "...",
  "uuid": "trim_pool",
  "disks": ["sdc"],
  "password": "pwd"
}
```

#### 替换磁盘

**Endpoint:** `stor.replaceDisk`

```json
{
  "req": "stor.replaceDisk",
  "reqid": "...",
  "uuid": "trim_pool",
  "disks": ["sdc"],
  "newDisks": ["sdd"],
  "password": "pwd"
}
```

#### 扩展存储池

**Endpoint:** `stor.extend`

```json
{"req": "stor.extend", "reqid": "...", "uuid": "trim_pool", "password": "pwd"}
```

#### 调整存储池

**Endpoint:** `stor.resize`

```json
{
  "req": "stor.resize",
  "reqid": "...",
  "uuid": "trim_pool",
  "disks": ["sdc"],
  "vdName": "vd1",
  "level": 6,
  "password": "pwd"
}
```

#### 停止存储池

**Endpoint:** `stor.stop`

```json
{"req": "stor.stop", "reqid": "...", "uuid": "trim_pool", "password": "pwd"}
```

#### 磁盘健康

**Endpoint:** `stor.diskHealth`

```json
{"req": "stor.diskHealth", "reqid": "...", "disk": "sda"}
```

#### SMART 信息

**Endpoint:** `stor.diskSmart`

```json
{"req": "stor.diskSmart", "reqid": "...", "disk": "sda"}
```

#### 格式化

**Endpoint:** `stor.format`

```json
{
  "req": "stor.format",
  "reqid": "...",
  "disk": "sdz",
  "fstype": "ext4",
  "partition": 0,
  "password": "pwd"
}
```

#### 弹出

**Endpoint:** `stor.eject`

```json
{"req": "stor.eject", "reqid": "...", "disk": "sdz", "password": "pwd"}
```

### 下载中心 (appcgi.downloadcenter.*)

#### 任务列表

**Endpoint:** `appcgi.downloadcenter.task.query`

```json
{
  "req": "appcgi.downloadcenter.task.query",
  "reqid": "...",
  "init_flag": true,
  "state_filter": 65535
}
```

#### 搜索任务

**Endpoint:** `appcgi.downloadcenter.task.search`

```json
{
  "req": "appcgi.downloadcenter.task.search",
  "reqid": "...",
  "keyword": "ubuntu"
}
```

#### 任务详情

**Endpoint:** `appcgi.downloadcenter.task.getInfo`

```json
{
  "req": "appcgi.downloadcenter.task.getInfo",
  "reqid": "...",
  "task_id": 42
}
```

#### 任务文件

**Endpoint:** `appcgi.downloadcenter.task.getFiles`

```json
{
  "req": "appcgi.downloadcenter.task.getFiles",
  "reqid": "...",
  "task_id": 42
}
```

#### 创建下载任务（URL）

**Endpoint:** `appcgi.downloadcenter.task.addUris`

```json
{
  "req": "appcgi.downloadcenter.task.addUris",
  "reqid": "...",
  "urls": ["https://example.com/file.zip"],
  "save_dir": "/vol1/downloads"
}
```

#### 创建下载任务（种子文件）

**Endpoint:** `appcgi.downloadcenter.task.addPaths`

```json
{
  "req": "appcgi.downloadcenter.task.addPaths",
  "reqid": "...",
  "paths": ["/vol1/torrents/demo.torrent"],
  "save_dir": "/vol1/downloads"
}
```

#### 暂停任务

**Endpoint:** `appcgi.downloadcenter.task.pause`

```json
{
  "req": "appcgi.downloadcenter.task.pause",
  "reqid": "...",
  "task_ids": [42, 43]
}
```

#### 恢复任务

**Endpoint:** `appcgi.downloadcenter.task.resume`

```json
{
  "req": "appcgi.downloadcenter.task.resume",
  "reqid": "...",
  "task_ids": [42, 43]
}
```

#### 重试任务

**Endpoint:** `appcgi.downloadcenter.task.retry`

```json
{
  "req": "appcgi.downloadcenter.task.retry",
  "reqid": "...",
  "task_ids": [42]
}
```

#### 删除任务

**Endpoint:** `appcgi.downloadcenter.task.delete`

```json
{
  "req": "appcgi.downloadcenter.task.delete",
  "reqid": "...",
  "task_ids": [42, 43]
}
```

#### 统计信息

**Endpoint:** `appcgi.downloadcenter.stat.all`

```json
{"req": "appcgi.downloadcenter.stat.all", "reqid": "..."}
```

### 网络管理 (appcgi.network.*)

#### SSH 开关

**Endpoint:** `appcgi.network.ssh.switch`

```json
{"req": "appcgi.network.ssh.switch", "reqid": "...", "enable": true}
```

### 电源管理

#### 重启

**Endpoint:** `appcgi.system.reboot`

```json
{"req": "appcgi.system.reboot", "reqid": "..."}
```

#### 关机

**Endpoint:** `appcgi.system.poweroff`

```json
{"req": "appcgi.system.poweroff", "reqid": "..."}
```

### 相册 (photos.*)

#### 获取相册目录

**Endpoint:** `appcgi.photos.album.getAlbums`

```json
{"req": "appcgi.photos.album.getAlbums", "reqid": "..."}
```

#### 搜索照片

**Endpoint:** `appcgi.photos.search`

```json
{
  "req": "appcgi.photos.search",
  "reqid": "...",
  "keyword": "北京",
  "limit": 20,
  "offset": 0,
  "filter": {"file_type": "photo"}
}
```

#### 照片详情

**Endpoint:** `appcgi.photos.getPhotoInfo`

```json
{"req": "appcgi.photos.getPhotoInfo", "reqid": "...", "photo_id": 8965}
```

#### 照片预览

**Endpoint:** `appcgi.photos.getPreviewUrl`

```json
{"req": "appcgi.photos.getPreviewUrl", "reqid": "...", "photo_id": 8965, "size": "m"}
```

### 影视 (media.*)

#### 媒体库统计

**Endpoint:** `appcgi.media.stats`

```json
{"req": "appcgi.media.stats", "reqid": "..."}
```

#### 搜索影片

**Endpoint:** `appcgi.media.search`

```json
{
  "req": "appcgi.media.search",
  "reqid": "...",
  "keyword": "流浪地球",
  "limit": 20
}
```

#### 影片详情

**Endpoint:** `appcgi.media.info`

```json
{"req": "appcgi.media.info", "reqid": "...", "movie_guid": "<guid>"}
```

#### 播放链接

**Endpoint:** `appcgi.media.play`

```json
{"req": "appcgi.media.play", "reqid": "...", "item_guid": "<guid>"}
```

### 应用中心 (appcgi.appmgr.*)

#### 应用列表

**Endpoint:** `appcgi.appmgr.installedList`

```json
{"req": "appcgi.appmgr.installedList", "reqid": "..."}
```

#### 应用状态

**Endpoint:** `appcgi.appmgr.status`

```json
{"req": "appcgi.appmgr.status", "reqid": "...", "appName": "trim.alist"}
```

#### 安装应用

**Endpoint:** `appcgi.appmgr.install`

```json
{
  "req": "appcgi.appmgr.install",
  "reqid": "...",
  "appName": "trim.alist",
  "version": "3.0.13",
  "sourceID": 265,
  "volumeID": 2
}
```

#### 启动应用

**Endpoint:** `appcgi.appmgr.start`

```json
{"req": "appcgi.appmgr.start", "reqid": "...", "appName": "trim.alist"}
```

#### 停止应用

**Endpoint:** `appcgi.appmgr.stop`

```json
{"req": "appcgi.appmgr.stop", "reqid": "...", "appName": "trim.alist"}
```

#### 卸载应用

**Endpoint:** `appcgi.appmgr.uninstall`

```json
{"req": "appcgi.appmgr.uninstall", "reqid": "...", "appName": "trim.alist"}
```

### Docker 管理 (appcgi.dockermgr.*)

#### 镜像列表

**Endpoint:** `appcgi.dockermgr.imageList`

```json
{"req": "appcgi.dockermgr.imageList", "reqid": "..."}
```

#### 容器列表

**Endpoint:** `appcgi.dockermgr.containerList`

```json
{"req": "appcgi.dockermgr.containerList", "reqid": "..."}
```

#### Compose 列表

**Endpoint:** `appcgi.dockermgr.composeList`

```json
{"req": "appcgi.dockermgr.composeList", "reqid": "..."}
```

#### 网络列表

**Endpoint:** `appcgi.dockermgr.networkList`

```json
{"req": "appcgi.dockermgr.networkList", "reqid": "..."}
```

### 日志中心 (appcgi.logmgr.*)

#### 日志列表

**Endpoint:** `appcgi.logmgr.list`

```json
{
  "req": "appcgi.logmgr.list",
  "reqid": "...",
  "page": 1,
  "pageSize": 20,
  "level": 0,
  "module": 0
}
```

#### 日志模块

**Endpoint:** `appcgi.logmgr.modules`

```json
{"req": "appcgi.logmgr.modules", "reqid": "..."}
```

## 错误码

### 通用错误码

| 错误码 | 描述 |
|--------|------|
| 0 | 成功 |
| 65534 | 通用失败 |
| 65537 | 密码验证失败 |
| 17 | 文件已存在 |
| 4386 | 磁盘空间不足 |
| 404 | 资源不存在 |
| 409 | 冲突 |

### 2FA 相关错误码

| 错误码 | 描述 |
|--------|------|
| 135168 | 验证码错误 |
| 102570104 | 验证码错误 |
| 102570109 | 临时凭据过期 |

### 存储相关错误码

| 错误码 | 描述 |
|--------|------|
| 328496 | 上传续传冲突 |
| 4100 | 上传检查失败 |

## 文件上传

### HTTP 上传流程

1. 调用 `file.checkUpload` 检查目标路径
2. 使用 `POST /upload` 上传文件

### HTTP Headers

| Header | 说明 |
|--------|------|
| `Trim-Path` | URI 编码的上传路径 |
| `Trim-From` | 续传起点（无续传时为 0） |
| `Trim-Overwrite` | 冲突策略（0=跳过, 1=替换, 2=重命名） |
| `Trim-Mtim` | 文件修改时间（Unix 秒） |
| `Trim-Token` | 当前 session token |

### Multipart 字段

- 字段名：`trim-upload-file`

## 注意事项

1. **路径格式**：文件路径必须使用 `/vol{v}/...` 格式
2. **存储标识**：存储池使用 uuid 或 `trim_*`，磁盘使用纯设备名
3. **写操作确认**：危险写操作需要 `--yes` 或密码验证
4. **多包响应**：某些端点返回多包，需要等待终态包
5. **签名请求**：当 secret 可用时，非直通请求需要 HMAC 签名
6. **会话恢复**：优先使用短期令牌，失败时回退到长期令牌，最后才用密码登录

## 示例：完整认证流程

```javascript
// 1. 连接 WebSocket
const ws = new WebSocket('wss://192.168.1.100:5667/websocket?type=main');

// 2. 登录
ws.send(JSON.stringify({
  req: 'user.login',
  reqid: generateReqId(),
  user: 'admin',
  password: 'password',
  stay: 1,
  deviceName: 'fnOS CLI',
  deviceType: 'CLI',
  did: 'my-device-id'
}));

// 3. 保存 token, longToken, secret, backId

// 4. 后续请求（带签名）
const signature = hmacSha256(secret, JSON.stringify(body));
ws.send(signature + JSON.stringify(body));
```

---

*文档生成时间：2026-08-10*  
*基于 trim-cli 技能 v0.1.0*
