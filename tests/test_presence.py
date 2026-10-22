"""Presence per tracker, the count of active scanners, rooms linked to areas."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from custom_components.ble_floorplan.catalog import LayoutProblem, with_areas
from custom_components.ble_floorplan.const import DOMAIN, WS_SET_FLOORPLAN, WS_SET_LAYOUT

from . import FLOORPLAN, ROOMS, TAG, FakeScanner, make_plan, rssi_exact, scanner_device
from .conftest import ScannerDevices


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_presence(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """Unknown after the start, home when seen, away after away_seconds without a sighting."""
    state = hass.states.get("device_tracker.tag_presence")
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes["source_type"] == "bluetooth_le"
    registry = er.async_get(hass)
    entity = registry.async_get("device_tracker.tag_presence")
    assert entity is not None
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "tag"), entry.entry_id)
    assert device is not None and entity.device_id == device.id

    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0)  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await _refresh(hass, entry)
    assert hass.states.get("device_tracker.tag_presence").state == STATE_HOME  # type: ignore[union-attr]
    # Not seen since 1000: still home within away_seconds, then away
    clock(1100.0)
    await _refresh(hass, entry)
    assert hass.states.get("device_tracker.tag_presence").state == STATE_HOME  # type: ignore[union-attr]
    clock(1200.0)
    await _refresh(hass, entry)
    assert hass.states.get("device_tracker.tag_presence").state == STATE_NOT_HOME  # type: ignore[union-attr]
    # The phone was never seen: away once away_seconds passed since the start
    assert hass.states.get("device_tracker.phone_presence").state == STATE_NOT_HOME  # type: ignore[union-attr]
    assert entry.runtime_data.coordinator.data["tag"].as_dict()["present"] is False


async def test_active_scanners(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanners: dict[str, FakeScanner],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Scanners of the plan that received anything within a minute; polled."""
    scanners["kitchen"].idle = 300.0
    other = FakeScanner("AA:BB:CC:DD:EE:99", "Elsewhere")
    with patch(
        "custom_components.ble_floorplan.sensor.async_current_scanners",
        return_value=[scanners["living"], scanners["kitchen"], other],
    ):
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        state = hass.states.get("sensor.ble_floorplan_active_scanners")
        assert state is not None
        assert state.state == "1"
        assert state.attributes["total"] == 3
        assert state.attributes["active"] == ["Living room scanner"]
        assert state.attributes["inactive"] == ["Kitchen plug", "Bedroom proxy"]
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "hub"), entry.entry_id)
    assert device is not None and device.name == "BLE Floorplan"


async def test_areas(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A room names its area by id or name; unknown areas are refused."""
    areas = ar.async_get(hass)
    living = areas.async_create("Wohnbereich")
    kitchen = areas.async_create("Kochen")
    rooms = [
        {**ROOMS[0], "area": living.id},
        {**ROOMS[1], "area": "Kochen"},
        *ROOMS[2:],
    ]
    plan = with_areas(hass, make_plan(rooms=rooms))
    assert plan.rooms[0].area == living.id
    assert plan.rooms[1].area == kitchen.id
    assert plan.area_of("Kitchen") == kitchen.id
    assert plan.area_of("Hall") is None
    assert plan.area_of(None) is None
    assert plan.as_dict()["rooms"][0]["area"] == living.id
    with pytest.raises(LayoutProblem, match="no area Garage"):
        with_areas(hass, make_plan(rooms=[{**ROOMS[0], "area": "Garage"}]))
    with pytest.raises(LayoutProblem, match=r"\(no name\)"):
        with_areas(hass, make_plan(rooms=[{"x": 0, "y": 0, "w": 1, "h": 1, "area": "Garage"}]))


async def test_area_commands_and_attribute(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """Layout and plan commands resolve areas; the room sensor names the area of its room."""
    living = ar.async_get(hass).async_create("Wohnbereich")
    client = await hass_ws_client(hass)
    layout = "rooms:\n  - {name: Living room, x: 0, y: 0, w: 6, h: 5, area: Wohnbereich}\n"
    await client.send_json_auto_id({"type": WS_SET_LAYOUT, "yaml": layout})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert f"area: {living.id}" in msg["result"]["yaml"]
    await client.send_json_auto_id(
        {
            "type": WS_SET_LAYOUT,
            "yaml": "rooms:\n  - {name: A, x: 0, y: 0, w: 1, h: 1, area: Nope}\n",
        }
    )
    msg = await client.receive_json()
    assert msg["error"]["code"] == "invalid_format"
    bad: dict[str, Any] = {**FLOORPLAN, "rooms": [{**ROOMS[0], "area": "Nope"}]}
    await client.send_json_auto_id({"type": WS_SET_FLOORPLAN, "floorplan": bad})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "invalid_format"
    assert "no area Nope" in msg["error"]["message"]

    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0)  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await _refresh(hass, entry)
    room = hass.states.get("sensor.tag_room")
    assert room is not None and room.state == "Living room"
    assert room.attributes["area_id"] == living.id
