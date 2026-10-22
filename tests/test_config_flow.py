"""The config flow: one entry, nothing to ask."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ble_floorplan.const import DOMAIN, NAME


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
