"""Config flow for Agilent 33120A."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_TERMINATION,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_TERMINATION,
    DOMAIN,
)
from .transport import Transport

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_TERMINATION, default=DEFAULT_TERMINATION): vol.In(["50", "INF"]),
        vol.Required(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(int, vol.Range(min=1, max=30)),
    }
)


class Agilent33120AConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow handler."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            idn, error = await self._probe(host, port)
            if error:
                errors["base"] = error
            else:
                unique_id = f"{host}:{port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"33120A @ {host}", data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def _probe(self, host: str, port: int) -> tuple[str | None, str | None]:
        transport = Transport(host, port)
        try:
            await asyncio.wait_for(transport.connect(), timeout=5.0)
            await transport.send("*CLS")
            idn = await asyncio.wait_for(transport.query("*IDN?"), timeout=5.0)
            if "33120A" not in idn:
                return None, "wrong_device"
            return idn, None
        except asyncio.TimeoutError:
            return None, "no_response_check_baud_and_cable"
        except OSError:
            return None, "cannot_connect"
        finally:
            await transport.disconnect()
