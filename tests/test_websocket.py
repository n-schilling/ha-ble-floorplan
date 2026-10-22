"""The WebSocket commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.const import (
    WS_GET_FLOORPLAN,
    WS_IMPORT,
    WS_SET_FLOORPLAN,
    WS_SET_SCANNER,
    WS_SUBSCRIBE,
)
from custom_components.ble_floorplan.importer import ImportProblem

from . import FLOORPLAN, SCANNER_LIVING, TAG, FakeScanner, make_plan, rssi_exact, scanner_device
from .conftest import ScannerDevices


async def test_get_floorplan(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """The plan and the positions."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_GET_FLOORPLAN})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["floorplan"] == make_plan().as_dict()
    assert msg["result"]["positions"]["tag"]["x"] is None
    assert set(msg["result"]["positions"]) == {"tag", "phone"}


async def test_not_loaded(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Every command answers not_loaded once the entry is unloaded."""
    client = await hass_ws_client(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    for message in (
        {"type": WS_GET_FLOORPLAN},
        {"type": WS_SUBSCRIBE},
        {"type": WS_SET_SCANNER, "key": "living", "x": 1, "y": 1},
        {"type": WS_SET_FLOORPLAN, "floorplan": {}},
        {"type": WS_IMPORT, "rooms": [], "scanners": [], "trackers": []},
    ):
        await client.send_json_auto_id(message)
        msg = await client.receive_json()
        assert not msg["success"], message
        assert msg["error"]["code"] == "not_loaded"


async def test_subscribe(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """A snapshot first, then positions on every refresh and the plan on every save."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SUBSCRIBE})
    msg = await client.receive_json()
    assert msg["success"]
    subscription = msg["id"]
    msg = await client.receive_json()
    assert msg["type"] == "event"
    assert msg["event"]["floorplan"]["scanners"][0]["key"] == "living"
    assert msg["event"]["positions"]["tag"]["room"] is None

    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(1.0, -60, 0.8, 0.3), 1000.0)  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await entry.runtime_data.coordinator.async_refresh()
    msg = await client.receive_json()
    assert msg["event"]["positions"]["tag"]["room"] == "Living room"
    assert msg["event"]["positions"]["tag"]["readings"]["living"]["used"]
    assert "floorplan" not in msg["event"]

    await entry.runtime_data.store.async_save(make_plan(settings={"max_distance": 9}))
    msg = await client.receive_json()
    assert msg["event"]["floorplan"]["settings"]["max_distance"] == 9.0
    assert "positions" not in msg["event"]

    await client.send_json_auto_id({"type": "unsubscribe_events", "subscription": subscription})
    msg = await client.receive_json()
    assert msg["success"]
    # No listeners left: a save reaches nobody
    await entry.runtime_data.store.async_save(make_plan())
    await client.send_json_auto_id({"type": WS_GET_FLOORPLAN})
    msg = await client.receive_json()
    assert msg["success"]


async def test_set_scanner(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Move, lift, and an unknown key."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SET_SCANNER, "key": "living", "x": 2.5, "y": 3})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"] == {
        "key": "living",
        "name": "Living room scanner",
        "source": SCANNER_LIVING,
        "x": 2.5,
        "y": 3.0,
        "z": 0.8,
        "rssi_offset": 0.0,
    }
    living = entry.runtime_data.store.plan.scanner("living")
    assert living is not None and (living.x, living.y, living.z) == (2.5, 3.0, 0.8)

    await client.send_json_auto_id(
        {"type": WS_SET_SCANNER, "key": "living", "x": 2.5, "y": 3, "z": 1.7}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["z"] == 1.7

    await client.send_json_auto_id({"type": WS_SET_SCANNER, "key": "nope", "x": 1, "y": 1})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_set_floorplan(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """A new plan is stored and the entry reloaded, so a new tracker gets its sensors."""
    client = await hass_ws_client(hass)
    plan = {
        **FLOORPLAN,
        "trackers": [{"key": "keys", "name": "Keys", "address": "AA:BB:CC:DD:EE:30"}],
    }
    await client.send_json_auto_id({"type": WS_SET_FLOORPLAN, "floorplan": plan})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["trackers"] == [
        {"key": "keys", "name": "Keys", "address": "AA:BB:CC:DD:EE:30", "height": 0.0}
    ]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.keys_room") is not None
    assert hass.states.get("sensor.tag_room") is None

    await client.send_json_auto_id(
        {"type": WS_SET_FLOORPLAN, "floorplan": {"rooms": [{"name": "A"}]}}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"
    assert "room" in msg["error"]["message"]


async def test_import(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """The card's configuration becomes the plan; problems leave the plan as it is."""
    client = await hass_ws_client(hass)
    message = {
        "type": WS_IMPORT,
        "title": "Card title",
        "positions_entity": "input_text.x",
        "rotation": 90,
        "rooms": [{"name": "Living room", "x": 0, "y": 0, "w": 6, "h": 5}],
        "scanners": [
            {"key": "living", "name": "Living", "source": SCANNER_LIVING, "default": [1, 1]}
        ],
        "trackers": [{"prefix": "tag", "name": "Tag", "address": TAG}],
        "positions": {"living": [2, 2]},
        "max_distance": 12,
    }
    await client.send_json_auto_id(message)
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["scanners"][0]["x"] == 2.0
    assert msg["result"]["settings"]["max_distance"] == 12.0
    assert msg["result"]["trackers"] == [
        {"key": "tag", "name": "Tag", "address": TAG, "height": 0.0}
    ]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.phone_room") is None

    with patch(
        "custom_components.ble_floorplan.websocket.build_floorplan",
        side_effect=ImportProblem("scanner x: no"),
    ):
        await client.send_json_auto_id(message)
        msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {"code": "import_failed", "message": "scanner x: no"}

    await client.send_json_auto_id({**message, "rooms": [{"name": "Broken"}]})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"
    assert entry.runtime_data.store.plan.settings.max_distance == 12.0


@pytest.mark.parametrize(
    "message",
    [
        {"type": WS_SET_SCANNER, "key": "living", "x": 1, "y": 1},
        {"type": WS_SET_FLOORPLAN, "floorplan": {}},
        {"type": WS_IMPORT, "rooms": [], "scanners": [], "trackers": []},
    ],
)
async def test_admin_only(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
    message: dict[str, Any],
) -> None:
    """Changing the plan needs an administrator."""
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(message)
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
