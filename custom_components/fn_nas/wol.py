"""Wake-on-LAN power-on for fnOS (complements the SSH/WSS power-off).

SSH can only shut a machine down; powering it back on requires a Wake-on-LAN
magic packet sent over a UDP broadcast. This is a self-contained,
dependency-free implementation (it does not require the HA ``wake_on_lan``
integration to be set up).

The magic packet is 102 bytes: six 0xFF bytes followed by 16 repetitions of the
target MAC address.
"""

from __future__ import annotations

import logging
import socket

_LOGGER = logging.getLogger(__name__)


def _parse_mac(mac: str) -> bytes:
    """Parse a MAC string into 6 bytes.

    Accepts ``01:23:45:67:89:ab``, ``01-23-45-67-89-ab`` or ``0123456789ab``.
    """
    cleaned = mac.strip().lower()
    for sep in (":", "-"):
        if sep in cleaned:
            cleaned = cleaned.replace(sep, "")
    if len(cleaned) != 12 or any(c not in "0123456789abcdef" for c in cleaned):
        raise ValueError(f"无效的 MAC 地址: {mac}")
    return bytes.fromhex(cleaned)


def _build_magic_packet(mac: str) -> bytes:
    """Build a Wake-on-LAN magic packet from a MAC string."""
    mac_bytes = _parse_mac(mac)
    return b"\xff" * 6 + mac_bytes * 16


def send_magic_packet(
    mac: str,
    broadcast: str = "255.255.255.255",
    port: int = 9,
    count: int = 3,
) -> None:
    """Broadcast a Wake-on-LAN magic packet to ``mac``.

    ``count`` frames are sent back-to-back (default 3, 0.1 s apart): a single
    frame is routinely dropped by NICs still spinning up from a powered-off
    state, so a short burst dramatically improves the wake-up hit rate.

    Sending is done on a blocking socket, so callers should run this off the
    event loop (see :func:`async_send_magic_packet`).
    """
    import time

    packet = _build_magic_packet(mac)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for i in range(count):
            sock.sendto(packet, (broadcast, port))
            if i < count - 1:
                time.sleep(0.1)
        _LOGGER.info(
            "已发送 %d 个 Wake-on-LAN 魔术包到 %s (%s:%s)", count, mac, broadcast, port
        )
    finally:
        sock.close()


async def async_send_magic_packet(
    hass,
    mac: str,
    broadcast: str = "255.255.255.255",
    port: int = 9,
) -> None:
    """Async wrapper that sends the magic packet off the event loop."""
    await hass.async_add_executor_job(send_magic_packet, mac, broadcast, port)
