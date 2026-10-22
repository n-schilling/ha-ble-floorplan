"""The sensors of a tracker and the cleanup of trackers that are gone."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH

from custom_components.ble_floorplan.const import DOMAIN, NAME
from custom_components.ble_floorplan.engine import Measurement, trilaterate

from . import TAG, FakeScanner, rssi_exact, scanner_device
from .conftest import ScannerDevices


async def test_entities_and_device(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Three sensors per tracker on a device named after it; unknown while not seen."""
    for entity_id in (
        "sensor.tag_room",
        "sensor.tag_position_x",
        "sensor.tag_position_y",
        "sensor.phone_room",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state == STATE_UNKNOWN
    room = hass.states.get("sensor.tag_room")
    assert room is not None
    assert room.attributes["friendly_name"] == "Tag Room"
    registry = er.async_get(hass)
    x_entry = registry.async_get("sensor.tag_position_x")
    assert x_entry is not None
    assert x_entry.entity_category == "diagnostic"
    assert x_entry.unique_id == "tag_position_x"
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier((DOMAIN, "tag"), entry.entry_id)
    assert device is not None
    assert device.name == "Tag"
    assert (CONNECTION_BLUETOOTH, TAG) in device.connections
    phone = devices.async_get_device_by_identifier((DOMAIN, "phone"), entry.entry_id)
    assert phone is not None
    assert phone.connections == set()
    assert entry.title == NAME


async def test_values(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """Room with its attributes, the coordinates in metres."""
    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0),  # type: ignore[arg-type]
        scanner_device(scanners["kitchen"], TAG, rssi_exact(6.5, -60, 2.0, 0.3), 1000.0),  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    room = hass.states.get("sensor.tag_room")
    assert room is not None
    assert room.state == "Living room"
    attributes: dict[str, Any] = dict(room.attributes)
    assert attributes["nearest_scanner"] == "Living room scanner"
    assert attributes["scanner_count"] == 2
    assert attributes["distances"] == {
        "Living room scanner": 2.0,
        "Kitchen plug": 6.5,
        "Bedroom proxy": None,
    }
    assert attributes["x"] == pytest.approx(room.attributes["x"])
    x = hass.states.get("sensor.tag_position_x")
    y = hass.states.get("sensor.tag_position_y")
    assert x is not None and y is not None
    assert x.attributes["unit_of_measurement"] == "m"
    assert float(x.state) == pytest.approx(attributes["x"], abs=0.01)
    assert float(y.state) == pytest.approx(attributes["y"], abs=0.01)
    expected = trilaterate(
        [Measurement(1, 1, 2.0), Measurement(9, 1, 6.5)], entry.runtime_data.store.plan
    )
    assert expected is not None
    assert float(x.state) == pytest.approx(expected[0], abs=0.01)


async def test_stale_entities_removed(
    hass: HomeAssistant,
    bluetooth: None,
    storage: dict[str, Any],
    clock: Callable[[float], None],
    scanner_devices: ScannerDevices,
    config_entry: MockConfigEntry,
) -> None:
    """Entities and devices of a tracker that left the plan are removed at setup."""
    config_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    old_device = devices.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, "old")}, name="Old"
    )
    entities = er.async_get(hass)
    entities.async_get_or_create(
        "sensor", DOMAIN, "old_room", config_entry=config_entry, device_id=old_device.id
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert entities.async_get_entity_id("sensor", DOMAIN, "old_room") is None
    assert devices.async_get_device_by_identifier((DOMAIN, "old"), config_entry.entry_id) is None
    assert entities.async_get_entity_id("sensor", DOMAIN, "tag_room") == "sensor.tag_room"
