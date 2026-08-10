"""Config flow for the fn_nas (飞牛NAS) integration using the WSS API."""

from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult

from .wss_client import FnWssClient, FnWssError
from .const import (
    DOMAIN,
    CONF_PORT,
    CONF_SCHEME,
    CONF_TLS_INSECURE,
    CONF_IGNORE_DISKS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEME,
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
                return self.async_create_entry(title=info["title"], data=user_input)

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
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict) -> FlowResult:
        return await self.async_step_user(entry_data)
