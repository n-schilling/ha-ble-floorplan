"""Config flow for BLE Floorplan: one entry, nothing to ask; one option."""

from __future__ import annotations

from typing import Any

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback

from .const import CONF_POSITION_SENSORS, DEFAULT_POSITION_SENSORS, DOMAIN, NAME


class BleFloorplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm the setup; the floor plan itself is imported or edited later."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title=NAME, data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Return the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlowWithReload):
    """Whether every tracker gets a sensor per coordinate; the reload adds or removes them."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the option."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_POSITION_SENSORS: bool(user_input[CONF_POSITION_SENSORS])}
            )
        current = self.config_entry.options.get(CONF_POSITION_SENSORS, DEFAULT_POSITION_SENSORS)
        schema = probatio.Schema({probatio.Required(CONF_POSITION_SENSORS, default=current): bool})
        return self.async_show_form(step_id="init", data_schema=schema)
