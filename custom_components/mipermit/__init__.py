"""MiPermit integration for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from .const import DOMAIN, SERVICE_GET_PERMITS, SERVICE_ACTIVATE_PERMIT, CONF_CDP_URL
from .browser import MiPermitBrowser

_LOGGER = logging.getLogger(__name__)

GET_PERMITS_SCHEMA = vol.Schema(
    {
        vol.Required("operator"): str,
    }
)

ACTIVATE_PERMIT_SCHEMA = vol.Schema(
    {
        vol.Required("operator"): str,
        vol.Required("registration"): str,
        vol.Required("permit_type"): str,
        vol.Required("duration"): vol.All(int, vol.Range(min=1, max=100)),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MiPermit from a config entry."""

    async def handle_get_permits(call: ServiceCall) -> dict:
        """Handle the get_permits service call."""
        browser = MiPermitBrowser(
            hass,
            entry.data["username"],
            entry.data["password"],
            entry.data[CONF_CDP_URL],
        )
        return await browser.get_active_permits(call.data["operator"])

    async def handle_activate_permit(call: ServiceCall) -> dict:
        """Handle the activate_permit service call."""
        browser = MiPermitBrowser(
            hass,
            entry.data["username"],
            entry.data["password"],
            entry.data[CONF_CDP_URL],
        )
        return await browser.activate_permit(
            call.data["operator"],
            call.data["registration"],
            call.data["permit_type"],
            call.data["duration"],
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PERMITS,
        handle_get_permits,
        schema=GET_PERMITS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVATE_PERMIT,
        handle_activate_permit,
        schema=ACTIVATE_PERMIT_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.services.async_remove(DOMAIN, SERVICE_GET_PERMITS)
    hass.services.async_remove(DOMAIN, SERVICE_ACTIVATE_PERMIT)
    return True
