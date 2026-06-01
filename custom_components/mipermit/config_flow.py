"""Config flow for MiPermit integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries

from .const import DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_CDP_URL, DEFAULT_CDP_URL
from .exceptions import InvalidCredentials, CannotConnect
from .browser import MiPermitBrowser

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_CDP_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CDP_URL, default=DEFAULT_CDP_URL): str,
    }
)


class MiPermitConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the MiPermit config flow."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialise the config flow."""
        self._credentials: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: collect MiPermit credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._credentials = user_input
            # Move to CDP URL step
            return await self.async_step_cdp()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_cdp(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: collect the Browserless CDP WebSocket URL and validate."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cdp_url = user_input[CONF_CDP_URL]
            data = {**self._credentials, CONF_CDP_URL: cdp_url}

            try:
                browser = MiPermitBrowser(
                    self.hass,
                    data[CONF_USERNAME],
                    data[CONF_PASSWORD],
                    cdp_url,
                )
                await browser.validate_login()
            except InvalidCredentials:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during MiPermit config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(data[CONF_USERNAME])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"MiPermit ({data[CONF_USERNAME]})",
                    data=data,
                )

        return self.async_show_form(
            step_id="cdp",
            data_schema=STEP_CDP_DATA_SCHEMA,
            errors=errors,
        )
