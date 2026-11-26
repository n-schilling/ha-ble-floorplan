"""The interface others build on, pinned: a change here is a breaking change.

Automations, dashboards and scripts use the entity IDs, unique IDs, translation
keys, attributes and WebSocket commands; the card finds its entities by the
translation keys. README, section Interface, describes the same; change both
together and mark the change in CHANGELOG.
"""

from __future__ import annotations

from collections.abc import Callable

from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.components.websocket_api import DOMAIN as WS_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.ble_floorplan import const
from custom_components.ble_floorplan.binary_sensor import UnreachableSensor
from custom_components.ble_floorplan.const import WS_GET_FLOORPLAN, WS_SUBSCRIBE
from custom_components.ble_floorplan.sensor import TrackersHomeSensor

from . import TAG, FakeScanner, rssi_exact, scanner_device
from .conftest import ScannerDevices

# What Home Assistant adds to the attributes of every entity
BASE = {
    "friendly_name",
    "icon",
    "device_class",
    "state_class",
    "source_type",
    "tracking_type",
    "in_zones",
}


async def test_entities(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Entity IDs, unique IDs and translation keys of the integration's device and of a tracker."""
    registry = er.async_get(hass)
    entities = {
        item.entity_id: (item.unique_id, item.translation_key, item.disabled_by is None)
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert entities == {
        "binary_sensor.ble_floorplan_scanners_unreachable": ("unreachable", "unreachable", True),
        "sensor.ble_floorplan_active_scanners": ("active_scanners", "active_scanners", True),
        "sensor.ble_floorplan_trackers_home": ("trackers_home", "trackers_home", True),
        "sensor.tag_room": ("tag_room", "room", True),
        "device_tracker.tag_presence": ("tag_presence", "presence", True),
        "sensor.phone_room": ("phone_room", "room", True),
        "device_tracker.phone_presence": ("phone_presence", "presence", True),
    }


async def test_attributes(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """The attributes automations and the card read, and which of them stay out of the history."""
    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0)  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    def attributes(entity_id: str) -> set[str]:
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        return set(state.attributes) - BASE

    assert attributes("sensor.ble_floorplan_trackers_home") == {"tracker_list"}
    home = hass.states.get("sensor.ble_floorplan_trackers_home")
    assert home is not None
    assert set(home.attributes["tracker_list"][0]) == {"name", "room_entity", "presence_entity"}
    assert attributes("binary_sensor.ble_floorplan_scanners_unreachable") == {"scanners"}
    assert attributes("sensor.ble_floorplan_active_scanners") == {
        "total",
        "paused",
        "active",
        "inactive",
    }
    assert attributes("sensor.tag_room") == {"area_id"}
    assert attributes("sensor.phone_room") == set()
    assert attributes("device_tracker.tag_presence") == set()
    # Names and entity IDs are for dashboards and automations now, not for the history
    assert TrackersHomeSensor._unrecorded_attributes == frozenset({"tracker_list"})
    assert UnreachableSensor._unrecorded_attributes == frozenset({"scanners"})


async def test_commands(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The WebSocket commands, as the README lists them."""
    commands = {name for name in hass.data[WS_DOMAIN] if name.startswith("ble_floorplan/")}
    assert commands == {value for name, value in vars(const).items() if name.startswith("WS_")}
    assert commands == {
        f"ble_floorplan/{name}"
        for name in (
            "get_floorplan",
            "subscribe",
            "set_scanner",
            "set_tracker",
            "set_settings",
            "candidates",
            "scanner_system",
            "scanner_quality",
            "ignore",
            "add_scanner",
            "add_tracker",
            "remove_scanner",
            "remove_tracker",
            "get_layout",
            "set_layout",
            "set_floorplan",
            "calibration/start",
            "calibration/stop",
            "calibration/list",
            "calibration/delete",
            "calibration/clear",
            "calibration/solve",
            "calibration/apply",
            "calibration/fit",
            "history",
            "coverage/model",
            "coverage/measured",
            "coverage/reset",
        )
    }


async def test_what_every_user_gets(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """The two commands open to every user, and what they give a user who is no administrator."""
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": WS_GET_FLOORPLAN})
    result = (await client.receive_json())["result"]
    assert set(result) == {"floorplan", "positions", "offline"}
    assert set(result["floorplan"]) == {"rooms", "openings", "scanners", "trackers"}
    assert set(result["floorplan"]["scanners"][0]) == {"key", "name", "x", "y", "z"}
    assert set(result["floorplan"]["trackers"][0]) == {"key", "name"}
    assert set(result["positions"]["tag"]) == {
        "key",
        "x",
        "y",
        "room",
        "present",
        "floor",
        "level",
    }
    await client.send_json_auto_id({"type": WS_SUBSCRIBE})
    assert (await client.receive_json())["success"]
    assert set((await client.receive_json())["event"]) == {"floorplan", "positions", "offline"}


def test_stores() -> None:
    """The stored formats: a changed one raises its version and comes with a migration."""
    assert {
        name: getattr(const, name) for name in vars(const) if name.endswith("_STORAGE_VERSION")
    } | {"STORAGE_VERSION": const.STORAGE_VERSION} == {
        "STORAGE_VERSION": 1,
        "CALIBRATION_STORAGE_VERSION": 1,
        "HISTORY_STORAGE_VERSION": 1,
        "COVERAGE_STORAGE_VERSION": 1,
        "QUALITY_STORAGE_VERSION": 1,
    }
    assert {name: getattr(const, name) for name in vars(const) if name.endswith("STORAGE_KEY")} == {
        "STORAGE_KEY": "ble_floorplan.floorplan",
        "CALIBRATION_STORAGE_KEY": "ble_floorplan.calibration",
        "HISTORY_STORAGE_KEY": "ble_floorplan.history",
        "COVERAGE_STORAGE_KEY": "ble_floorplan.coverage",
        "QUALITY_STORAGE_KEY": "ble_floorplan.quality",
    }
