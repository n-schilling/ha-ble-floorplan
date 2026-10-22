"""Setup, unload, removal and the card's registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE, MODE_YAML
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.const import CALIBRATION_STORAGE_KEY, DOMAIN, STORAGE_KEY
from custom_components.ble_floorplan.frontend import (
    CARD_PATH,
    DATA_FRONTEND,
    async_card_url,
    async_register_frontend,
)

from .conftest import ScannerDevices


async def test_setup_and_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The entry loads with the stored plan and unloads cleanly."""
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.store.plan.trackers[0].key == "tag"
    assert hass.states.get("sensor.tag_room") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    room = hass.states.get("sensor.tag_room")
    assert room is not None and room.state == STATE_UNAVAILABLE


async def test_unload_stops_a_calibration_run(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A run that is going when the entry unloads is stopped and saved."""
    calibration = entry.runtime_data.calibration
    run = await entry.runtime_data.coordinator.async_start_calibration("tag", 1.0, 1.0, 0.0)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not run.running
    assert calibration.active is None


async def test_remove_deletes_storage(
    hass: HomeAssistant, entry: MockConfigEntry, storage: dict[str, Any]
) -> None:
    """Removing the entry removes the stored plan and the calibration runs."""
    await entry.runtime_data.calibration.async_start("tag", 1.0, 1.0, 0.0, 1000.0)
    await entry.runtime_data.calibration.async_stop(1010.0)
    assert STORAGE_KEY in storage
    assert CALIBRATION_STORAGE_KEY in storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert STORAGE_KEY not in storage
    assert CALIBRATION_STORAGE_KEY not in storage


async def test_card_url_carries_version(hass: HomeAssistant, bluetooth: None) -> None:
    """Browsers fetch the card anew with every release."""
    url = await async_card_url(hass)
    assert url.startswith(f"{CARD_PATH}?v=")
    assert url.split("v=")[1][0].isdigit()


async def test_frontend_registered_once(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The static path is served; a second registration does nothing."""
    assert hass.data[DATA_FRONTEND].startswith(CARD_PATH)
    with patch.object(hass.http, "async_register_static_paths", AsyncMock()) as register:
        await async_register_frontend(hass)
    register.assert_not_called()


def _lovelace(mode: str, resources: Any) -> MagicMock:
    data = MagicMock()
    data.resource_mode = mode
    data.resources = resources
    return data


def _collection(items: list[dict[str, Any]]) -> MagicMock:
    collection = MagicMock(spec=ResourceStorageCollection)
    collection.async_get_info = AsyncMock()
    collection.async_items = MagicMock(return_value=items)
    collection.async_create_item = AsyncMock()
    collection.async_update_item = AsyncMock()
    return collection


async def test_frontend_extra_js_and_resource_created(
    hass: HomeAssistant,
    bluetooth: None,
    storage: dict[str, Any],
    clock: Callable[[float], None],
    scanner_devices: ScannerDevices,
    config_entry: MockConfigEntry,
) -> None:
    """With the frontend loaded the card is added to every page and to the dashboard resources."""
    collection = _collection([{"id": "1", "url": "/local/other.js", "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    hass.data[DATA_EXTRA_MODULE_URL] = MagicMock()
    config_entry.add_to_hass(hass)
    with patch("custom_components.ble_floorplan.frontend.add_extra_js_url") as add_url:
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    url = hass.data[DATA_FRONTEND]
    add_url.assert_called_once_with(hass, url)
    collection.async_get_info.assert_awaited_once()
    collection.async_create_item.assert_awaited_once_with({"res_type": "module", "url": url})
    collection.async_update_item.assert_not_awaited()


async def test_frontend_resource_updated(hass: HomeAssistant, bluetooth: None) -> None:
    """An entry of an earlier version is pointed to this one; a current one is left alone."""
    url = await async_card_url(hass)
    collection = _collection([{"id": "7", "url": f"{CARD_PATH}?v=0.0.1", "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    await async_register_frontend(hass)
    collection.async_update_item.assert_awaited_once_with("7", {"url": url})
    collection.async_create_item.assert_not_awaited()

    hass.data.pop(DATA_FRONTEND)
    collection = _collection([{"id": "7", "url": url, "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    await async_register_frontend(hass)
    collection.async_update_item.assert_not_awaited()
    collection.async_create_item.assert_not_awaited()


async def test_frontend_resource_skipped(hass: HomeAssistant, bluetooth: None) -> None:
    """Resources in YAML are the user's; a collection of another kind is left alone."""
    collection = _collection([])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_YAML, collection)
    await async_register_frontend(hass)
    collection.async_create_item.assert_not_awaited()

    hass.data.pop(DATA_FRONTEND)
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, MagicMock())
    await async_register_frontend(hass)
    assert DATA_FRONTEND in hass.data
    assert DOMAIN in hass.data[DATA_FRONTEND]
