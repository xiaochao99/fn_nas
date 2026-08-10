"""fnOS WebSocket (WSS) monitoring client — CORRECTED PROTOCOL + DATA PARSING.

KEY FINDINGS (verified against real fnOS API 2026-07-21):
- Protocol: flat JSON, "req" field (NOT "endpoint"), params at top level
- Error: check "result":"succ" (NOT "errno")
- Disk list: appcgi.resmon.disk → data.disk[] → {name, temp}
- SMART data: raw smartctl JSON, fields are model_name, serial_number,
  user_capacity.bytes, temperature.current, power_on_time.hours, etc.
- Memory endpoint: appcgi.resmon.mem (NOT .memory)
- CPU: resp.data.cpu.busy.all, resp.data.cpu.core
- Storage pools: stor.general → array[] (NOT individual disks)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import ssl
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT_WS = 5666
DEFAULT_PORT_WSS_IP = 5667
DEFAULT_PORT_WSS_DOMAIN = 443

_DIRECT_ENDPOINTS = {"user.login", "user.authToken", "user.tokenLogin"}

_FNOS_ERRORS = {
    65534: "认证/权限失败",
    65537: "密码验证失败",
    404: "资源不存在",
    409: "状态冲突",
}


class FnWssAuthError(Exception):
    """Authentication failed and could not be recovered (need re-login)."""


class FnWssError(Exception):
    """A fnOS business/transport error."""

    def __init__(self, errno: int, errmsg: str | None):
        self.errno = errno
        self.errmsg = errmsg
        super().__init__(f"[{errno}] {errmsg or _FNOS_ERRORS.get(errno, 'unknown error')}")


class FnWssConnectionClosed(FnWssError):
    """The WebSocket was closed by the server (or never opened)."""

    def __init__(self, errmsg: str = "connection closed by server"):
        super().__init__(0, errmsg)


def _looks_like_ip(host: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_private(host: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


class FnWssClient:
    """Async fnOS WebSocket API client."""

    def __init__(
        self,
        host: str,
        *,
        username: str,
        password: str,
        port: int | None = None,
        scheme: str | None = None,
        tls_insecure: bool = False,
        timeout: float = 15.0,
    ) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._tls_insecure = tls_insecure
        self._timeout = timeout
        self._scheme, self._port = self._resolve_endpoint(scheme, port)

        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

        self._token: str | None = None
        self._long_token: str | None = None
        self._secret: str | None = None
        self._back_id: str | None = None
        self._uid: int | None = None
        self._username_logged: str | None = None

        self._seq = 0
        self._reqid_prefix = secrets.token_hex(8)

    # ── endpoint resolution ──────────────────────────────────────────────

    def _resolve_endpoint(self, scheme: str | None, port: int | None) -> tuple[str, int]:
        is_loopback = self._host in ("localhost", "127.0.0.1", "::1")
        is_private = _looks_like_ip(self._host) and _is_private(self._host)
        if scheme in (None, "auto"):
            scheme = "ws" if (is_loopback or is_private) else "wss"
        if not port:
            if scheme == "ws":
                port = DEFAULT_PORT_WS
            elif is_loopback or is_private:
                port = DEFAULT_PORT_WSS_IP
            else:
                port = DEFAULT_PORT_WSS_DOMAIN
        return scheme, port

    @property
    def ws_url(self) -> str:
        return f"{self._scheme}://{self._host}:{self._port}/websocket?type=main"

    # ── session persistence ──────────────────────────────────────────────

    @property
    def session(self) -> dict[str, Any]:
        return {
            "token": self._token,
            "long_token": self._long_token,
            "secret": self._secret,
            "back_id": self._back_id,
            "uid": self._uid,
            "username": self._username_logged,
            "host": self._host,
            "port": self._port,
            "scheme": self._scheme,
        }

    def load_session(self, data: dict[str, Any]) -> None:
        self._token = data.get("token")
        self._long_token = data.get("long_token")
        self._secret = data.get("secret")
        self._back_id = data.get("back_id")
        self._uid = data.get("uid")
        self._username_logged = data.get("username")
        if data.get("port") and data.get("scheme"):
            self._port = data["port"]
            self._scheme = data["scheme"]

    # ── connection ───────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        if self.is_connected:
            return
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        ssl_ctx: bool | ssl.SSLContext = True
        if self._scheme == "wss":
            ssl_ctx = False if self._tls_insecure else True
        try:
            self._ws = await self._session.ws_connect(
                self.ws_url, ssl=ssl_ctx, timeout=self._timeout
            )
        except Exception as err:
            raise FnWssError(0, f"connection failed: {err}") from err

    async def disconnect(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def close(self) -> None:
        await self.disconnect()
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ── authentication ───────────────────────────────────────────────────

    async def ensure_authenticated(self) -> None:
        if self._secret and self._token:
            try:
                resp = await self._raw_call(
                    "user.authToken",
                    {"token": self._token, "main": True, "active": True},
                    signed=False,
                )
                self._update_session(resp)
                return
            except (FnWssError, FnWssConnectionClosed):
                pass
        if self._long_token:
            try:
                resp = await self._raw_call(
                    "user.tokenLogin",
                    {
                        "token": self._long_token,
                        "deviceName": "fnOS-HA",
                        "deviceType": "API",
                    },
                    signed=False,
                )
                self._update_session(resp)
                return
            except (FnWssError, FnWssConnectionClosed):
                pass
        await self.login()

    async def login(self) -> dict[str, Any]:
        resp = await self._raw_call(
            "user.login",
            {
                "user": self._username,
                "password": self._password,
                "stay": 1,
                "deviceName": "fnOS-HA",
                "deviceType": "API",
            },
            signed=False,
        )
        self._update_session(resp)
        return resp

    def _update_session(self, resp: dict[str, Any]) -> None:
        mapping = (
            ("token", "token"),
            ("longToken", "long_token"),
            ("long_token", "long_token"),
            ("secret", "secret"),
            ("backId", "back_id"),
            ("uid", "uid"),
            ("username", "username"),
        )
        for src, dst in mapping:
            if resp.get(src) is not None:
                setattr(self, f"_{dst}", resp[src])

    # ── request core ────────────────────────────────────────────────────

    def _make_reqid(self) -> str:
        bid = str(self._back_id or "00000000")[:8]
        seq = format(self._seq, "08x")
        self._seq = (self._seq + 1) % 0xFFFFFFFF
        return f"{self._reqid_prefix}{bid}{seq}"

    def _sign(self, body: dict[str, Any]) -> str:
        key = base64.b64decode(self._secret)
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        sig = hmac.new(key, raw.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(sig).decode("ascii") + raw

    @staticmethod
    def _parse_json(data) -> dict[str, Any]:
        try:
            return json.loads(data)
        except (ValueError, TypeError) as err:
            raise FnWssError(0, f"invalid JSON response: {err}") from err

    async def _receive_json(self) -> dict[str, Any]:
        while True:
            try:
                msg = await self._ws.receive(timeout=self._timeout)
            except asyncio.TimeoutError as err:
                raise FnWssError(0, f"receive timeout ({self._timeout}s)") from err
            except Exception as err:
                raise FnWssError(0, f"receive error: {err}") from err

            if msg.type == aiohttp.WSMsgType.TEXT:
                return self._parse_json(msg.data)
            if msg.type == aiohttp.WSMsgType.BINARY:
                return self._parse_json(msg.data.decode("utf-8"))
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                raise FnWssConnectionClosed(
                    f"server closed (code={msg.data})" if hasattr(msg, 'data') and msg.data else "connection closed"
                )
            if msg.type == aiohttp.WSMsgType.ERROR:
                raise FnWssError(0, f"websocket error: {self._ws.exception()}")

    async def _raw_call(
        self, req: str, params: dict[str, Any] | None = None, *, signed: bool = True
    ) -> dict[str, Any]:
        """Send a fnOS flat-JSON request.

        Format: {"reqid":"...","req":"endpoint.name","param1":"val1",...}
        """
        body: dict[str, Any] = {
            "reqid": self._make_reqid(),
            "req": req,
        }
        if params:
            body.update(params)

        if signed and not self._secret:
            raise FnWssAuthError("request requires secret but none available — need login first")

        if signed:
            payload = self._sign(body)
        else:
            payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

        try:
            if isinstance(payload, str):
                await self._ws.send_str(payload)
            elif isinstance(payload, bytes):
                await self._ws.send_bytes(payload)
            else:
                await self._ws.send_str(payload)
        except Exception as err:
            raise FnWssError(0, f"send failed: {err}") from err

        resp = await self._receive_json()

        result = resp.get("result")
        if result is not None and result != "succ":
            errmsg = resp.get("errmsg") or resp.get("errorMsg") or f"result={result}"
            errno = resp.get("errno", -1)
            raise FnWssError(errno, errmsg)
        return resp

    async def _obtain_secret(self) -> None:
        await self.connect()
        await self.login()
        if not self._secret:
            _LOGGER.warning("fnOS WSS: login succeeded but no 'secret' field in response")

    async def _send_signed(self, req: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._ws is None or self._ws.closed:
            await self.connect()
            if not self._secret:
                await self._obtain_secret()
        return await self._raw_call(req, params, signed=True)

    async def call(
        self,
        req: str,
        *,
        retry_on_disconnect: bool = True,
        **params: Any,
    ) -> dict[str, Any]:
        """Send a signed business request, transparently recovering from faults.

        Two recoverable conditions are handled:
        * the server closed the socket (reconnect and retry once by default), and
        * the session secret expired/invalid (re-login to refresh the secret and
          retry once). Without this, a session timeout would make every poll fail
          after the NAS has been idle for a while.
        """
        if not self._secret:
            await self._obtain_secret()
            if not self._secret:
                raise FnWssError(0, "no session secret; cannot sign request")

        async def _attempt() -> dict[str, Any]:
            try:
                return await self._send_signed(req, params or None)
            except FnWssConnectionClosed:
                if not retry_on_disconnect:
                    raise
                _LOGGER.debug("fnOS WSS: reconnecting for %s", req)
                return await self._send_signed(req, params or None)

        try:
            resp = await _attempt()
        except FnWssError as err:
            if err.errno in (65534, 65537) or "认证" in str(err) or "登录" in str(err):
                _LOGGER.debug(
                    "fnOS WSS: session error on %s (%s); re-authenticating", req, err
                )
                await self._obtain_secret()
                resp = await _attempt()
            else:
                raise
        return resp

    # ── convenience methods ──────────────────────────────────────────────

    async def get_system_info(self) -> dict[str, Any]:
        return await self.call("appcgi.sysinfo.getTrimMachineType")

    async def reboot(self) -> dict[str, Any]:
        """Restart fnOS through the system power-management endpoint."""
        return await self.call("appcgi.system.reboot", retry_on_disconnect=False)

    async def poweroff(self) -> dict[str, Any]:
        """Shut down fnOS through the system power-management endpoint."""
        return await self.call("appcgi.system.poweroff", retry_on_disconnect=False)

    async def get_cpu(self) -> dict[str, Any]:
        return await self.call("appcgi.resmon.cpu")

    async def get_memory(self) -> dict[str, Any]:
        return await self.call("appcgi.resmon.mem")

    async def get_storage_space(self) -> dict[str, Any]:
        return await self.call("stor.calcSpace")

    async def get_storage_overview(self) -> dict[str, Any]:
        return await self.call("stor.general")

    async def get_disk_list(self) -> list[dict[str, Any]]:
        """Get list of all physical disks via appcgi.resmon.disk."""
        resp = await self.call("appcgi.resmon.disk")
        _LOGGER.debug("fnOS WSS appcgi.resmon.disk → %s", resp)
        return resp.get("data", {}).get("disk", [])

    async def get_disk_smart(self, dev_name: str) -> dict[str, Any]:
        """Get raw smartctl JSON SMART data for a physical disk.

        Key fields in smart dict:
        - model_name, serial_number
        - temperature.current, power_on_time.hours
        - smart_status.passed, user_capacity.bytes
        - rotation_rate (0=SSD), device.protocol

        When the disk is in standby/sleep, returns
        ``{"diskStandby": 1, "result": "succ"}`` with no SMART fields.
        """
        return await self.call("stor.diskSmart", disk=dev_name)

    async def get_disk_info(self, dev_name: str) -> dict[str, Any]:
        """Get basic disk identity (model, serial, size) even when standby.

        ``stor.diskSmart`` returns only ``diskStandby: 1`` for sleeping disks.
        ``stor.disk`` is a lighter call that may still provide model/serial
        without waking the drive.
        """
        return await self.call("stor.disk", disk=dev_name)

    _MODEL_KEYS = ("model_name", "model", "device_model", "product", "vendor")
    _SERIAL_KEYS = ("serial_number", "serial", "sn")

    # Candidate field names in SMART / disk-list responses. The fnOS firmware
    # is inconsistent across disk types (HDD vs SATA SSD vs NVMe) — the actual
    # key for "model" / "serial" can vary. Try each in order.
    _MODEL_KEYS = (
        "model_name", "model", "model_family", "device_model", "product",
        "vendor", "manufacturer",
    )
    _SERIAL_KEYS = (
        "serial_number", "serial", "sn", "device_serial",
    )

    async def get_all_disk_info(self) -> list[dict[str, Any]]:
        """Get complete info for all physical disks.

        Uses appcgi.resmon.disk for temperature (fast, single call).
        Uses stor.diskSmart per disk for model/serial/SMART status.
        Disks are named by serial number (fallback to device name).
        """
        disk_list = await self.get_disk_list()
        disks: list[dict[str, Any]] = []

        def _first(source: dict, keys: tuple[str, ...]) -> Any:
            for k in keys:
                val = source.get(k)
                if val:
                    return val
            return None

        for item in disk_list:
            dev = item.get("name")
            if not dev:
                continue

            # Fallbacks from the disk list itself, used when SMART is missing
            # the field (or SMART query fails entirely).
            list_model = _first(item, self._MODEL_KEYS)
            list_serial = _first(item, self._SERIAL_KEYS)

            entry: dict[str, Any] = {
                "dev": dev,
                "name": dev,  # stable internal identifier
                "display_name": list_serial or dev,
                "temp": item.get("temp"),  # primary: resmon.disk (always works)
                "model": list_model,
                "serial": list_serial,
                "size": None,
                "protocol": None,
                "smart_ok": None,
                "power_on_hours": None,
                "rotation": None,
                "wear_level": None,
                "is_system": False,
            }

            smart_resp: dict[str, Any] | None = None
            try:
                smart_resp = await self.get_disk_smart(dev)
                # SMART payloads come in two shapes: wrapped in "smart"/"data",
                # or a bare smartctl JSON with fields at the top level. Fall back
                # to the whole response so a bare payload (e.g. some SSDs) still
                # yields model_name / serial_number.
                smart = (
                    smart_resp.get("smart")
                    or smart_resp.get("data")
                    or smart_resp
                ) or {}

                serial = _first(smart, self._SERIAL_KEYS)
                if serial:
                    entry["serial"] = serial
                    entry["display_name"] = serial

                smart_model = _first(smart, self._MODEL_KEYS)
                if smart_model:
                    entry["model"] = smart_model

                # Disk in standby returns ``{diskStandby:1, result:"succ"}``
                # with no SMART fields at all. Try a lighter API that may still
                # give model / serial / size without waking the drive.
                if (
                    smart is smart_resp
                    and smart_resp.get("diskStandby") == 1
                    and not (smart_model and serial)
                ):
                    _LOGGER.debug("fnOS disk %s is in standby; trying stor.disk", dev)
                    try:
                        info_resp = await self.get_disk_info(dev)
                        info = (
                            info_resp.get("data")
                            or info_resp.get("disk")
                            or info_resp
                        ) or {}
                        if not smart_model:
                            smart_model = _first(info, self._MODEL_KEYS)
                            if smart_model:
                                entry["model"] = smart_model
                        if not serial:
                            serial = _first(info, self._SERIAL_KEYS)
                            if serial:
                                entry["serial"] = serial
                                entry["display_name"] = serial
                        # May also provide size
                        if entry["size"] is None:
                            cap = info.get("size") or info.get("capacity")
                            if isinstance(cap, (int, float)):
                                entry["size"] = cap
                    except FnWssError as err:
                        _LOGGER.debug(
                            "fnOS disk %s stor.disk fallback also failed: %s", dev, err
                        )

                capacity = smart.get("user_capacity")
                if isinstance(capacity, dict):
                    entry["size"] = capacity.get("bytes")
                elif isinstance(capacity, (int, float)):
                    entry["size"] = capacity

                # SMART temperature is secondary - resmon.disk temp is preferred
                # because it's realtime and always available
                if entry["temp"] is None:
                    temp = smart.get("temperature")
                    if isinstance(temp, dict):
                        entry["temp"] = temp.get("current")
                    elif isinstance(temp, (int, float)):
                        entry["temp"] = temp

                status = smart.get("smart_status")
                if isinstance(status, dict):
                    entry["smart_ok"] = status.get("passed")

                power = smart.get("power_on_time")
                if isinstance(power, dict):
                    entry["power_on_hours"] = power.get("hours")

                entry["rotation"] = smart.get("rotation_rate")

                device_info = smart.get("device")
                if isinstance(device_info, dict):
                    entry["protocol"] = device_info.get("protocol")

                # NVMe wear level (Percentage Used)
                nvme_health = smart.get("nvme_smart_health_information_log")
                if isinstance(nvme_health, dict) and nvme_health.get("percentage_used") is not None:
                    entry["wear_level"] = nvme_health["percentage_used"]

                # SATA SSD wear level: try ATA SMART attributes
                if entry["wear_level"] is None:
                    ata_table = smart.get("ata_smart_attributes", {}).get("table", [])
                    for attr in ata_table:
                        # Common wear-level attributes across SSD vendors
                        if attr.get("id") in (177, 202, 230, 231, 233):
                            raw = attr.get("raw", {})
                            val = raw.get("value") if isinstance(raw, dict) else attr.get("value")
                            if val is not None:
                                entry["wear_level"] = val
                                break

            except FnWssError as err:
                _LOGGER.warning(
                    "fnOS SMART query FAILED for %s: %s  "
                    "(resmon item keys: %s)",
                    dev,
                    err,
                    sorted(item.keys()) if isinstance(item, dict) else None,
                )
            else:
                missing = []
                if not entry.get("model"):
                    missing.append("model")
                if not entry.get("serial"):
                    missing.append("serial")
                if missing:
                    is_standby = (
                        smart is smart_resp
                        and isinstance(smart_resp, dict)
                        and smart_resp.get("diskStandby") == 1
                    )
                    _LOGGER.log(
                        logging.DEBUG if is_standby else logging.WARNING,
                        "fnOS disk %s %s missing %s; "
                        "smart keys=%s  resmon keys=%s  smart_resp=%s",
                        dev,
                        "(standby)" if is_standby else "SMART ok but",
                        ", ".join(missing),
                        sorted(smart.keys()) if isinstance(smart, dict) else None,
                        sorted(item.keys()) if isinstance(item, dict) else None,
                        smart_resp,
                    )

            disks.append(entry)

        return disks
