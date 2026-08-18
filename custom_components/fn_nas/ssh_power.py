"""SSH power control for fnOS (migrated from v1).

fnOS sometimes refuses the WebSocket ``appcgi.system.poweroff`` call with error
code 266240 — the device-side policy layer blocks the API shutdown when there
are unfinished 虚拟机/Docker/任务, or when API shutdown is disabled. The SSH
path (``sudo shutdown -h now`` / ``sudo reboot``) is reliably honored, so the
power buttons use it as a primary method or as an automatic fallback.

This is a focused, one-shot implementation: open a single connection, run the
privileged command, close. No persistent pool is needed for occasional power
actions (unlike v1, which used a pool for the polling path that no longer
exists in the WS-based v2).
"""

from __future__ import annotations

import logging
import re

_LOGGER = logging.getLogger(__name__)

# Matches ``ip link show`` / ``ip -o link show`` output. The ``-o`` (oneline)
# variant folds each interface's header and its ``link/ether`` line onto a
# single logical line (joined by a backslash), so we must NOT require a
# literal newline between the interface name and the MAC. ``[\s\S]*?`` lazily
# spans any characters (including newlines) so both formats parse correctly.
_MAC_RE = re.compile(
    r"^\d+:\s+(\S+?):[\s\S]*?link/\S+\s+([0-9a-fA-F:]{17})",
    re.MULTILINE,
)


class SshPowerError(Exception):
    """Raised when an SSH power command cannot be issued."""


async def send_power_command(
    host: str,
    port: int,
    username: str,
    password: str,
    sudo_password: str | None,
    command: str,
    connect_timeout: int = 10,
) -> None:
    """Open a one-shot SSH connection and run a privileged power command.

    Mirrors the v1 behaviour: if the login user is root the command runs
    directly; otherwise it is piped through ``sudo -S`` using ``sudo_password``
    (falling back to the login ``password`` when no separate sudo password is
    configured).

    Raises :class:`SshPowerError` on any connection/permission/execution failure
    with a message safe to surface to the user.
    """
    try:
        import asyncssh
    except ImportError as err:  # asyncssh not installed in the environment
        raise SshPowerError(
            "未安装 asyncssh 依赖，无法通过 SSH 关机/重启。请在 Home Assistant "
            "环境中安装 asyncssh 后重试（HACS 会自动安装）。"
        ) from err

    conn = None
    try:
        conn = await asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None,
            connect_timeout=connect_timeout,
        )

        # Decide how to elevate. Root login -> run directly.
        is_root = False
        try:
            res = await conn.run("id -u", timeout=5)
            is_root = (res.stdout or "").strip() == "0"
        except Exception:  # noqa: BLE001 - non-fatal, treat as non-root
            is_root = False

        if is_root:
            full_command = command
            run_kwargs: dict = {}
        else:
            pw = sudo_password or password
            full_command = f"sudo -S {command}"
            run_kwargs = {"input": (pw or "") + "\n"} if pw else {}

        result = await conn.run(full_command, timeout=15, **run_kwargs)
        if result.exit_status != 0:
            stderr = (result.stderr or "").strip()
            raise SshPowerError(
                f"SSH 执行命令失败 (exit={result.exit_status}): {stderr or '无输出'}"
            )
        _LOGGER.info("SSH 电源命令已发送: %s (host=%s)", command, host)
    except SshPowerError:
        raise
    except Exception as err:  # noqa: BLE001
        raise SshPowerError(f"SSH 连接/执行失败: {err}") from err
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _parse_macs(output: str) -> dict[str, str]:
    """Parse ``ip link`` output into ``{mac: "iface - mac"}``.

    Filters the loopback device and null MACs. Mirrors the v1 logic.
    """
    macs: dict[str, str] = {}
    for iface, mac in _MAC_RE.findall(output):
        if iface == "lo" or mac == "00:00:00:00:00:00":
            continue
        macs[mac] = f"{iface} - {mac}"
    return macs


async def ssh_get_macs(
    host: str,
    port: int,
    username: str,
    password: str,
    sudo_password: str | None = None,
    connect_timeout: int = 10,
) -> dict[str, str]:
    """Fetch NIC MAC addresses over SSH (v1 auto-detect for WoL).

    Runs ``ip -o link show`` on the NAS and parses every interface MAC.
    ``ip link show`` is readable without elevation, so no ``sudo`` is needed.
    Returns ``{mac: "iface - mac"}``. Raises :class:`SshPowerError` on any
    connection/execution failure with a message safe to surface to the user.
    """
    try:
        import asyncssh
    except ImportError as err:  # asyncssh not installed in the environment
        raise SshPowerError(
            "未安装 asyncssh 依赖，无法通过 SSH 自动获取 MAC。请在 Home Assistant "
            "环境中安装 asyncssh 后重试（HACS 会自动安装），或手动填写 MAC 地址。"
        ) from err

    conn = None
    try:
        conn = await asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None,
            connect_timeout=connect_timeout,
        )
        # ``ip link show`` is readable for ordinary users — no sudo needed.
        result = await conn.run("ip -o link show", timeout=10)
        if result.exit_status != 0:
            stderr = (result.stderr or "").strip()
            raise SshPowerError(
                f"获取网卡信息失败 (exit={result.exit_status}): {stderr or '无输出'}"
            )
        return _parse_macs(result.stdout or "")
    except SshPowerError:
        raise
    except Exception as err:  # noqa: BLE001
        raise SshPowerError(f"SSH 连接/执行失败: {err}") from err
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

