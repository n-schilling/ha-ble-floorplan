"""The WebSocket commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.const import (
    WS_CALIBRATION_APPLY,
    WS_CALIBRATION_DELETE,
    WS_CALIBRATION_LIST,
    WS_CALIBRATION_SOLVE,
    WS_CALIBRATION_START,
    WS_CALIBRATION_STOP,
    WS_GET_FLOORPLAN,
    WS_SET_FLOORPLAN,
    WS_SET_SCANNER,
    WS_SET_SETTINGS,
    WS_SET_TRACKER,
    WS_SUBSCRIBE,
)

from . import (
    FLOORPLAN,
    SCANNER_LIVING,
    TAG,
    FakeScanner,
    make_plan,
    rssi_exact,
    scanner_device,
    synthetic_run,
)
from .conftest import ScannerDevices

CATALOG_MESSAGES: list[dict[str, Any]] = [
    {"type": "ble_floorplan/candidates"},
    {"type": "ble_floorplan/add_scanner", "source": "AA:BB:CC:DD:EE:04"},
    {"type": "ble_floorplan/add_tracker", "address": "AA:BB:CC:DD:EE:30", "name": "Keys"},
    {"type": "ble_floorplan/remove_scanner", "key": "living"},
    {"type": "ble_floorplan/remove_tracker", "key": "tag"},
    {"type": "ble_floorplan/get_layout"},
    {"type": "ble_floorplan/set_layout", "yaml": ""},
]

CALIBRATION_MESSAGES: list[dict[str, Any]] = [
    {"type": WS_CALIBRATION_START, "tracker": "tag", "x": 1, "y": 1},
    {"type": WS_CALIBRATION_STOP},
    {"type": WS_CALIBRATION_LIST},
    {"type": WS_CALIBRATION_DELETE, "run_id": "x"},
    {"type": WS_CALIBRATION_SOLVE},
    {"type": WS_CALIBRATION_APPLY, "trackers": {"tag": -50}},
]


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
        {"type": WS_SET_TRACKER, "key": "tag", "height": 1},
        {"type": WS_SET_SETTINGS, "settings": {}},
        {"type": WS_SET_FLOORPLAN, "floorplan": {}},
        *CALIBRATION_MESSAGES,
        *CATALOG_MESSAGES,
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
        "pair_offsets": {},
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

    # Offset and pairs alone: the position stays
    await client.send_json_auto_id(
        {
            "type": WS_SET_SCANNER,
            "key": "living",
            "rssi_offset": -2.5,
            "pair_offsets": {"tag": 1.5, "phone": -1},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["x"] == 2.5
    assert msg["result"]["rssi_offset"] == -2.5
    assert msg["result"]["pair_offsets"] == {"tag": 1.5, "phone": -1.0}
    plan = entry.runtime_data.store.plan
    assert plan.pair_offset("living", "tag") == 1.5
    # A pair set to null is removed; an unknown tracker is refused
    await client.send_json_auto_id(
        {"type": WS_SET_SCANNER, "key": "living", "pair_offsets": {"tag": None}}
    )
    msg = await client.receive_json()
    assert msg["result"]["pair_offsets"] == {"phone": -1.0}
    await client.send_json_auto_id(
        {"type": WS_SET_SCANNER, "key": "living", "pair_offsets": {"nope": 1}}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {"code": "not_found", "message": "no tracker nope"}
    assert entry.runtime_data.store.plan.pair_offsets == {"living": {"phone": -1.0}}


async def test_set_tracker(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Height, reference power (null for the default) and the pairs of a tracker; no reload."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_SET_TRACKER,
            "key": "tag",
            "height": 0.9,
            "ref_power": -58,
            "pair_offsets": {"living": 2, "kitchen": -3},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {
        "key": "tag",
        "name": "Tag",
        "address": TAG,
        "height": 0.9,
        "ref_power": -58.0,
        "pair_offsets": {"living": 2.0, "kitchen": -3.0},
    }
    plan = entry.runtime_data.store.plan
    tag = plan.tracker("tag")
    assert tag is not None and tag.height == 0.9 and tag.ref_power == -58.0
    assert plan.pair_offsets == {"living": {"tag": 2.0}, "kitchen": {"tag": -3.0}}
    await hass.async_block_till_done()
    assert hass.states.get("sensor.tag_room") is not None

    await client.send_json_auto_id(
        {"type": WS_SET_TRACKER, "key": "tag", "ref_power": None, "pair_offsets": {"kitchen": None}}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert "ref_power" not in msg["result"]
    assert msg["result"]["pair_offsets"] == {"living": 2.0}
    assert entry.runtime_data.store.plan.pair_offsets == {"living": {"tag": 2.0}}

    await client.send_json_auto_id({"type": WS_SET_TRACKER, "key": "nope", "height": 1})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"
    await client.send_json_auto_id(
        {"type": WS_SET_TRACKER, "key": "tag", "pair_offsets": {"nope": 1}}
    )
    msg = await client.receive_json()
    assert msg["error"] == {"code": "not_found", "message": "no scanner nope"}


async def test_set_settings(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Part of the settings changes, the rest stays; bad values are refused as a whole."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_SET_SETTINGS, "settings": {"room_margin": 0.6, "max_speed": 0}}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["room_margin"] == 0.6
    assert msg["result"]["max_speed"] == 0.0
    assert msg["result"]["attenuation"] == 3.0
    settings = entry.runtime_data.store.plan.settings
    assert (settings.room_margin, settings.max_speed, settings.smoothing_seconds) == (
        0.6,
        0.0,
        20.0,
    )

    await client.send_json_auto_id(
        {"type": WS_SET_SETTINGS, "settings": {"attenuation": 9, "room_margin": 1}}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_format"
    assert entry.runtime_data.store.plan.settings.room_margin == 0.6
    await client.send_json_auto_id({"type": WS_SET_SETTINGS, "settings": {"nope": 1}})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "invalid_format"


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


@pytest.mark.parametrize(
    "message",
    [
        {"type": WS_SET_SCANNER, "key": "living", "x": 1, "y": 1},
        {"type": WS_SET_TRACKER, "key": "tag", "height": 1},
        {"type": WS_SET_SETTINGS, "settings": {}},
        {"type": WS_SET_FLOORPLAN, "floorplan": {}},
        *CALIBRATION_MESSAGES,
        *CATALOG_MESSAGES,
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


async def test_calibration_start_and_stop(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    clock: Callable[[float], None],
) -> None:
    """One run at a time, at the tracker's height unless given; stop ends it."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_CALIBRATION_STOP})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "no_calibration"

    await client.send_json_auto_id(
        {"type": WS_CALIBRATION_START, "tracker": "nope", "x": 1, "y": 1}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"

    clock(1000.0)
    await client.send_json_auto_id({"type": WS_CALIBRATION_START, "tracker": "tag", "x": 2, "y": 3})
    msg = await client.receive_json()
    assert msg["success"], msg
    run = msg["result"]
    assert run["running"]
    assert (run["tracker"], run["x"], run["y"], run["height"]) == ("tag", 2.0, 3.0, 0.3)
    assert run["duration"] is None
    assert run["counts"] == {}
    assert entry.runtime_data.calibration.active is not None

    await client.send_json_auto_id({"type": WS_CALIBRATION_START, "tracker": "tag", "x": 1, "y": 1})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "calibration_running"

    clock(1090.0)
    await client.send_json_auto_id({"type": WS_CALIBRATION_STOP})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["id"] == run["id"]
    assert msg["result"]["duration"] == 90.0
    assert not msg["result"]["running"]

    await client.send_json_auto_id(
        {"type": WS_CALIBRATION_START, "tracker": "phone", "x": 1, "y": 1, "height": 1.4}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["height"] == 1.4


async def test_calibration_list_and_delete(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Summaries by default, the samples on request; delete needs an existing run."""
    client = await hass_ws_client(hass)
    calibration = entry.runtime_data.calibration
    run = await calibration.async_start("tag", 2.0, 2.0, 0.3, 1000.0)
    calibration.add_sample("living", 1001.0, -60)
    await calibration.async_stop(1010.0)
    active = await calibration.async_start("phone", 5.0, 5.0, 1.0, 1020.0)

    await client.send_json_auto_id({"type": WS_CALIBRATION_LIST})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["active"] == active.id
    assert [r["id"] for r in msg["result"]["runs"]] == [run.id, active.id]
    assert msg["result"]["runs"][0]["counts"] == {"living": 1}
    assert "samples" not in msg["result"]["runs"][0]

    await client.send_json_auto_id({"type": WS_CALIBRATION_LIST, "samples": True})
    msg = await client.receive_json()
    assert msg["result"]["runs"][0]["samples"] == {"living": [[1.0, -60]]}

    await client.send_json_auto_id({"type": WS_CALIBRATION_DELETE, "run_id": "nope"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"

    await client.send_json_auto_id({"type": WS_CALIBRATION_DELETE, "run_id": active.id})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"] == {"active": None, "runs": [run.summary()]}
    assert calibration.active is None


async def test_calibration_solve(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """The proposal from the finished runs; an error when they do not determine anything."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_CALIBRATION_SOLVE})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "calibration_failed"
    assert "no finished run" in msg["error"]["message"]

    plan = entry.runtime_data.store.plan
    offsets = {"living": 1.0, "kitchen": -1.0, "bedroom": 0.0}
    entry.runtime_data.calibration.runs.extend(
        [
            synthetic_run(plan, "r1", "tag", 2.0, 2.0, -58.0, offsets, 2.8),
            synthetic_run(plan, "r2", "tag", 7.0, 3.0, -58.0, offsets, 2.8),
        ]
    )
    await client.send_json_auto_id({"type": WS_CALIBRATION_SOLVE})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["attenuation"] is None
    assert msg["result"]["trackers"]["tag"]["runs"] == 2
    assert msg["result"]["rms"]["new"] > 0

    await client.send_json_auto_id({"type": WS_CALIBRATION_SOLVE, "attenuation": True})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["attenuation"] == {"old": 3.0, "new": 2.8}
    assert msg["result"]["trackers"]["tag"]["new"] == -58.0
    assert msg["result"]["scanners"]["living"]["new"] == 1.0
    assert msg["result"]["rms"]["new"] == 0.0
    # Nothing was written
    assert entry.runtime_data.store.plan == plan


async def test_calibration_apply(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """Apply writes the values into the plan and reloads; not while a run goes; known keys only."""
    client = await hass_ws_client(hass)
    calibration = entry.runtime_data.calibration
    await calibration.async_start("tag", 2.0, 2.0, 0.3, 1000.0)
    await client.send_json_auto_id({"type": WS_CALIBRATION_APPLY, "trackers": {"tag": -58}})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "calibration_running"
    await calibration.async_stop(1010.0)

    await client.send_json_auto_id({"type": WS_CALIBRATION_APPLY, "scanners": {"nope": 1}})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"] == {"code": "not_found", "message": "no scanner nope"}
    assert entry.runtime_data.store.plan == make_plan()

    await client.send_json_auto_id(
        {
            "type": WS_CALIBRATION_APPLY,
            "attenuation": 2.8,
            "trackers": {"tag": -58},
            "scanners": {"living": 1, "kitchen": -1},
            "pairs": {"kitchen": {"tag": 2.5}},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["settings"]["attenuation"] == 2.8
    assert msg["result"]["trackers"][0]["ref_power"] == -58.0
    assert msg["result"]["scanners"][1]["rssi_offset"] == -1.0
    assert msg["result"]["pair_offsets"] == {"kitchen": {"tag": 2.5}}
    await hass.async_block_till_done()
    plan = entry.runtime_data.store.plan
    assert plan.pair_offset("kitchen", "tag") == 2.5
    assert plan.settings.attenuation == 2.8
    assert hass.states.get("sensor.tag_room") is not None
    # The runs survived the reload
    assert len(entry.runtime_data.calibration.runs) == 1


async def test_subscribe_calibration(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """The runs are in the snapshot, sent on every change, and with the positions while one goes."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SUBSCRIBE})
    msg = await client.receive_json()
    assert msg["success"]
    msg = await client.receive_json()
    assert msg["event"]["calibration"] == {"active": None, "runs": []}

    clock(1000.0)
    run = await entry.runtime_data.coordinator.async_start_calibration("tag", 2.0, 2.0, 0.3)
    msg = await client.receive_json()
    assert msg["event"] == {"calibration": {"active": run.id, "runs": [run.summary()]}}

    scanner_devices[TAG] = [scanner_device(scanners["living"], TAG, -60, 1001.0)]
    clock(1002.0)
    await entry.runtime_data.coordinator.async_refresh()
    msg = await client.receive_json()
    assert msg["event"]["positions"]["tag"]["room"] == "Living room"
    assert msg["event"]["calibration"]["runs"][0]["counts"] == {"living": 1}

    await entry.runtime_data.coordinator.async_stop_calibration()
    msg = await client.receive_json()
    assert msg["event"]["calibration"]["active"] is None
    assert msg["event"]["calibration"]["runs"][0]["duration"] == 2.0

    scanner_devices[TAG] = [scanner_device(scanners["living"], TAG, -61, 1003.0)]
    clock(1004.0)
    await entry.runtime_data.coordinator.async_refresh()
    msg = await client.receive_json()
    assert "calibration" not in msg["event"]
    assert "positions" in msg["event"]


async def test_subscribe_follows_a_reload(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """After a reload the subscription gets a snapshot of the new entry and its positions."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SUBSCRIBE})
    msg = await client.receive_json()
    subscription = msg["id"]
    await client.receive_json()
    old_coordinator = entry.runtime_data.coordinator

    await client.send_json_auto_id(
        {"type": WS_SET_FLOORPLAN, "floorplan": make_plan(settings={"max_distance": 9}).as_dict()}
    )
    # The save reaches the old listener, the reload sends a new snapshot
    events = [await client.receive_json() for _ in range(3)]
    kinds = [set(e["event"]) for e in events if e["type"] == "event"]
    assert {"floorplan"} in kinds
    assert {"floorplan", "positions", "calibration"} in kinds
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator is not old_coordinator

    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(1.0, -60, 0.8, 0.3), 1000.0)  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await entry.runtime_data.coordinator.async_refresh()
    msg = await client.receive_json()
    assert msg["event"]["positions"]["tag"]["room"] == "Living room"

    await client.send_json_auto_id({"type": "unsubscribe_events", "subscription": subscription})
    msg = await client.receive_json()
    assert msg["success"]
    # Gone from the rebind list as well: a reload reaches nobody
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await client.send_json_auto_id({"type": WS_GET_FLOORPLAN})
    msg = await client.receive_json()
    assert msg["success"]
