"""Setup, unload, removal and the card's registration."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, DATA_PANELS
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE, MODE_YAML
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan import frontend
from custom_components.ble_floorplan.const import (
    CALIBRATION_STORAGE_KEY,
    DOMAIN,
    HISTORY_STORAGE_KEY,
    PANEL_ELEMENT,
    PANEL_URL_PATH,
    STORAGE_KEY,
)
from custom_components.ble_floorplan.coordinator import FloorplanCoordinator
from custom_components.ble_floorplan.frontend import (
    CARD_PATH,
    DATA_FRONTEND,
    PANEL_PATH,
    async_about,
    async_card_url,
    async_register_frontend,
    async_register_panel,
)
from custom_components.ble_floorplan.history import HistoryStore
from custom_components.ble_floorplan.model import with_settings

from .conftest import ScannerDevices

PACKAGE = Path(__file__).resolve().parent.parent / "custom_components" / "ble_floorplan"


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


async def test_unload_fits_the_tracker_of_the_run(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A run that a reload ends saves the tracker's values, as a stop on the page does."""
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_start_calibration("tag", 1.0, 1.0, 0.0)
    with patch.object(
        FloorplanCoordinator, "async_fit_tracker", AsyncMock(return_value=None)
    ) as fit:
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    fit.assert_awaited_once_with("tag")


@pytest.mark.parametrize(
    "key", [STORAGE_KEY, CALIBRATION_STORAGE_KEY, HISTORY_STORAGE_KEY], ids=["plan", "runs", "days"]
)
async def test_unreadable_storage_stops_the_setup(
    hass: HomeAssistant,
    bluetooth: None,
    storage: dict[str, Any],
    clock: Callable[[float], None],
    scanner_devices: ScannerDevices,
    config_entry: MockConfigEntry,
    key: str,
) -> None:
    """A file that does not load stops the setup with its name; the file stays as it is."""
    broken = {"rooms": None} if key == STORAGE_KEY else {"runs": None, "days": None}
    storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": broken}
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert config_entry.reason is not None and f".storage/{key}" in config_entry.reason
    assert storage[key]["data"] == broken


async def test_timeline_pruned_only_when_its_days_change(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Saving the plan prunes the timeline only when the number of days changed."""
    store = entry.runtime_data.store
    with patch.object(HistoryStore, "async_prune", AsyncMock()) as prune:
        await store.async_save(with_settings(store.plan, {"max_speed": 2}))
        await hass.async_block_till_done()
        prune.assert_not_awaited()
        await store.async_save(with_settings(store.plan, {"history_days": 3}))
        await hass.async_block_till_done()
        prune.assert_awaited_once()
        assert prune.await_args is not None and prune.await_args.args[1] == 3
        await store.async_save(with_settings(store.plan, {"history_days": 3, "max_speed": 1}))
        await hass.async_block_till_done()
        prune.assert_awaited_once()


async def test_page_shows_version_and_commit(
    hass: HomeAssistant, bluetooth: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page shows the version of the manifest, and the commit of a test deployment."""
    version = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))["version"]
    monkeypatch.setattr(frontend, "BUILD_FILE", str(tmp_path / "BUILD"))
    assert await async_about(hass) == {"version": version, "commit": None}
    (tmp_path / "BUILD").write_text("0123456789ab\n", encoding="utf-8")
    assert await async_about(hass) == {"version": version, "commit": "0123456789ab"}


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


async def test_panel_for_administrators(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The panel is in the sidebar of administrators, its module carries the version."""
    panel = hass.data[DATA_PANELS][PANEL_URL_PATH]
    assert panel.require_admin
    assert panel.sidebar_title == "BLE Floorplan"
    assert panel.sidebar_icon == "mdi:floor-plan"
    custom = panel.config["_panel_custom"]
    assert custom["name"] == PANEL_ELEMENT
    assert custom["module_url"] == (await async_card_url(hass)).replace(CARD_PATH, PANEL_PATH)
    assert not custom["embed_iframe"]


async def test_panel_stays_through_a_reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A reload keeps the panel, a page that shows it stays; a second registration does nothing."""
    panel = hass.data[DATA_PANELS][PANEL_URL_PATH]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DATA_PANELS][PANEL_URL_PATH] is panel
    await async_register_panel(hass)
    assert hass.data[DATA_PANELS][PANEL_URL_PATH] is panel


async def test_remove_takes_the_panel_away(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Removing the entry takes the panel off the sidebar."""
    assert PANEL_URL_PATH in hass.data[DATA_PANELS]
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert PANEL_URL_PATH not in hass.data[DATA_PANELS]


async def test_card_url_carries_a_content_hash(hass: HomeAssistant, bluetooth: None) -> None:
    """Browsers fetch the card anew with every change of a script, also within a version."""
    url = await async_card_url(hass)
    assert url.startswith(f"{CARD_PATH}?v=")
    digest = url.split("v=")[1]
    assert len(digest) == 12
    assert all(c in "0123456789abcdef" for c in digest)


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
    collection.async_delete_item = AsyncMock()
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


async def test_remove_takes_the_resource_away_and_a_new_entry_brings_it_back(
    hass: HomeAssistant,
    bluetooth: None,
    storage: dict[str, Any],
    clock: Callable[[float], None],
    scanner_devices: ScannerDevices,
    config_entry: MockConfigEntry,
) -> None:
    """Removing the entry removes the card's dashboard resource; a new entry adds it again."""
    items: list[dict[str, Any]] = [{"id": "1", "url": "/local/other.js", "type": "module"}]
    collection = _collection(items)
    hass.data[LOVELACE_DATA] = _lovelace(MODE_STORAGE, collection)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    url = hass.data[DATA_FRONTEND]
    items.append({"id": "2", "url": url, "type": "module"})
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    collection.async_delete_item.assert_awaited_once_with("2")

    items.pop()
    collection.async_create_item.reset_mock()
    again = MockConfigEntry(domain=DOMAIN, title="BLE Floorplan", unique_id=DOMAIN, data={})
    again.add_to_hass(hass)
    assert await hass.config_entries.async_setup(again.entry_id)
    await hass.async_block_till_done()
    collection.async_create_item.assert_awaited_once_with({"res_type": "module", "url": url})


async def test_remove_leaves_yaml_resources_alone(hass: HomeAssistant, bluetooth: None) -> None:
    """Resources in YAML are the user's, also when the entry goes."""
    collection = _collection([{"id": "2", "url": f"{CARD_PATH}?v=1", "type": "module"}])
    hass.data[LOVELACE_DATA] = _lovelace(MODE_YAML, collection)
    await frontend.async_remove_resource(hass)
    collection.async_delete_item.assert_not_awaited()
