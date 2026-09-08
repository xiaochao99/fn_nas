"""Config flow for the fn_nas (飞牛NAS) integration using the WSS API."""

from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .wss_client import FnWssClient, FnWssError
from .const import (
    DOMAIN,
    CONF_PORT,
    CONF_SCHEME,
    CONF_TLS_INSECURE,
    CONF_IGNORE_DISKS,
    CONF_SSH_PORT,
    CONF_MAC,
    CONF_DEVICE_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEME,
    DEFAULT_SSH_PORT,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass, data: dict) -> dict:
    """Validate the user input by connecting to fnOS over WSS."""
    client = FnWssClient(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        port=data.get(CONF_PORT),
        scheme=data.get(CONF_SCHEME, DEFAULT_SCHEME),
        tls_insecure=data.get(CONF_TLS_INSECURE, False),
        timeout=15,
        device_id=data.get(CONF_DEVICE_ID) or None,
    )
    try:
        info = await client.get_system_info()
    except FnWssError as err:
        raise err
    finally:
        await client.close()
    title = data[CONF_HOST]
    if isinstance(info.get("model"), list):
        title = "-".join(str(x) for x in info["model"]) or title
    return {"title": title}


class FlynasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for fn_nas."""

    VERSION = 3

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except FnWssError as err:
                _LOGGER.warning("fnOS WSS validation failed: %s", err)
                err_str = str(err)
                if "认证" in err_str or err.errno in (65534, 65537):
                    errors["base"] = "invalid_auth"
                elif "wrong version number" in err_str or "SSL" in err_str:
                    errors["base"] = "wrong_scheme"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating fnOS connection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                # Best-effort Wake-on-LAN MAC auto-detect over SSH. The 关机/重启
                # buttons always use SSH, so the same credentials/port work here.
                # Normalise None (SSH unreachable / failed) to an empty dict so
                # the branching below stays type-safe.
                macs = await self._detect_macs(user_input) or {}
                if len(macs) == 1:
                    # Single NIC — auto-fill and finish; the 开机 (WoL) entity
                    # appears immediately.
                    user_input[CONF_MAC] = next(iter(macs))
                    return self.async_create_entry(title=info["title"], data=user_input)
                # 0 or >1 NICs:
                #   * multiple NICs -> dropdown picker;
                #   * none/empty    -> manual text field (optional blank).
                # Either way the user resolves the MAC at add time, so the WoL
                # entity shows up without a later trip to "Configure".
                self._setup_data = user_input
                self._setup_title = info["title"]
                self._detected_macs = macs
                return await self.async_step_select_mac()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(
                    CONF_SCHEME, default=DEFAULT_SCHEME
                ): vol.In(["auto", "ws", "wss"]),
                vol.Optional(CONF_PORT): int,
                vol.Optional(CONF_TLS_INSECURE, default=False): bool,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): int,
                vol.Optional(CONF_IGNORE_DISKS, default=""): str,
                # SSH port — used for the 关机/重启 buttons (always SSH) and for
                # auto-detecting the WoL MAC at setup time. sudo password is not
                # collected: when the login user is not root, the integration
                # falls back to the login password for sudo.
                vol.Optional(
                    CONF_SSH_PORT, default=DEFAULT_SSH_PORT
                ): int,
                # Device ID — a fixed identifier for the login device. If
                # provided, the same device ID is used for all login requests,
                # preventing fnOS from creating a new device entry on each
                # reconnect. Leave empty to use a random ID (default behavior).
                vol.Optional(CONF_DEVICE_ID, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_select_mac(self, user_input: dict | None = None) -> FlowResult:
        macs = getattr(self, "_detected_macs", None) or {}
        if user_input is not None:
            setup = dict(self._setup_data)
            setup[CONF_MAC] = user_input[CONF_MAC]
            return self.async_create_entry(title=self._setup_title, data=setup)

        # No MACs to choose from — either an empty set was detected or the
        # transient state was lost between requests. Fall back to a manual
        # text field (optionally blank) so the wizard can still finish.
        if not macs:
            schema = vol.Schema(
                {
                    vol.Optional(CONF_MAC, default=""): str,
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_MAC, default=next(iter(macs))): vol.In(macs),
                }
            )
        return self.async_show_form(step_id="select_mac", data_schema=schema)

    async def _detect_macs(self, data: dict) -> dict | None:
        """Auto-detect NIC MACs over SSH for Wake-on-LAN.

        Returns ``{mac: "iface - mac"}`` on success (may be empty if no NIC was
        parsed), or ``None`` when SSH is unreachable / fails — so setup can
        continue without WoL. Best-effort: never blocks the add wizard on
        failure.
        """
        try:
            from .ssh_power import ssh_get_macs

            return await ssh_get_macs(
                host=data[CONF_HOST],
                port=data.get(CONF_SSH_PORT, DEFAULT_SSH_PORT),
                username=data[CONF_USERNAME],
                password=data[CONF_PASSWORD],
            )
        except Exception as err:  # noqa: BLE001 - best-effort
            _LOGGER.debug("添加集成时 MAC 自动探测 (SSH) 失败: %s", err)
            return None

    async def async_step_reauth(self, entry_data: dict) -> FlowResult:
        return await self.async_step_user(entry_data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow — lets integrations change the WoL MAC.

    The MAC is auto-detected over SSH at add time (single NIC auto-filled,
    multiple NICs offer a picker). This flow is the fallback for when SSH was
    unavailable during setup, or for re-picking the NIC, or manual entry.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # Newer Home Assistant defines `config_entry` as a read-only property on
        # the OptionsFlow base class, so we cannot assign it directly here.
        # Store the entry privately and re-expose it via our own property below.
        super().__init__()
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry this options flow belongs to."""
        return self._config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        data: dict = {
            **self.config_entry.data,
            **(self.config_entry.options or {}),
        }
        current_mac = data.get(CONF_MAC, "")

        if user_input is not None:
            chosen = user_input.get(CONF_MAC)
            return self.async_create_entry(
                title="", data={CONF_MAC: (chosen or current_mac) or ""}
            )

        # Try to auto-detect MACs over SSH; on success offer a dropdown,
        # otherwise fall back to a free-text field. Best-effort: never blocks
        # the options UI on failure.
        macs: dict[str, str] = {}
        try:
            from .ssh_power import ssh_get_macs

            macs = await ssh_get_macs(
                host=data[CONF_HOST],
                port=data.get(CONF_SSH_PORT, DEFAULT_SSH_PORT),
                username=data[CONF_USERNAME],
                password=data[CONF_PASSWORD],
            )
        except Exception as err:  # noqa: BLE001 - auto-detect is best-effort
            _LOGGER.debug("Options-flow MAC 自动探测 (SSH) 失败: %s", err)

        if macs:
            # Keep the current value selectable even if not in the detected set.
            options = dict(macs)
            if current_mac and current_mac not in options:
                options[current_mac] = f"{current_mac} (当前)"
            mac_schema = vol.In(options)
            # Ensure the default is always a valid choice for the dropdown.
            default_mac = current_mac if current_mac in options else next(iter(options))
        else:
            mac_schema = str
            default_mac = current_mac or ""

        schema = vol.Schema(
            {
                vol.Optional(CONF_MAC, default=default_mac): mac_schema,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"host": data.get(CONF_HOST, "")},
        )
