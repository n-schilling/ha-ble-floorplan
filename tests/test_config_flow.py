"""The config flow: one entry, nothing to ask; the options flow: the position sensors."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.ble_floorplan.const import CONF_POSITION_SENSORS, DOMAIN, NAME


async def test_user_flow(hass: HomeAssistant, bluetooth: None) -> None:
    """A form to confirm, then the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {}
    entry = result["result"]
    assert entry.unique_id == DOMAIN
    assert entry.state is config_entries.ConfigEntryState.LOADED


async def test_single_instance(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A second entry is refused."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_toggle_position_sensors(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Turning the option on adds the position sensors after the reload, off removes them."""
    registry = er.async_get(hass)
    for enabled in (True, False):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POSITION_SENSORS: enabled}
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options == {CONF_POSITION_SENSORS: enabled}
        assert entry.state is config_entries.ConfigEntryState.LOADED
        assert (registry.async_get("sensor.tag_position_x") is not None) is enabled
        assert (registry.async_get("sensor.phone_position_y") is not None) is enabled
    assert registry.async_get("sensor.tag_room") is not None
