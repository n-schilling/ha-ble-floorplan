"""The timeline: which points go into a track, the stores per day, the command."""

from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.const import HISTORY_STORAGE_KEY, WS_HISTORY, WS_SET_SETTINGS
from custom_components.ble_floorplan.coordinator import TrackerPosition
from custom_components.ble_floorplan.history import HistoryStore, day_of, day_start
from custom_components.ble_floorplan.model import with_settings

from . import TAG, FakeScanner, rssi_exact, scanner_device
from .conftest import ScannerDevices

# 2026-10-26 12:00 UTC
NOON = datetime(2026, 10, 26, 12, tzinfo=UTC).timestamp()
DAY = "2026-10-26"
INDEX = HISTORY_STORAGE_KEY
TODAY_KEY = f"{HISTORY_STORAGE_KEY}.{DAY}"


def _at(
    x: float | None, y: float | None = 1.0, room: str | None = "Living room"
) -> TrackerPosition:
    """The tag at x / y in the room; not seen when x is None."""
    if x is None:
        return TrackerPosition("tag", TAG, None, None, None, None, None, None, 0)
    return TrackerPosition("tag", TAG, x, y, x, y, room, "living", 3)


class _Wall:
    """The wall clock of the integration, without freezegun: it would replace the engine's clock."""

    def __init__(self) -> None:
        self.t = NOON

    def utcnow(self) -> datetime:
        return datetime.fromtimestamp(self.t, UTC)


@pytest.fixture
def wall() -> Generator[_Wall]:
    """Unix time NOON for the integration; set `t` to move it."""
    clock = _Wall()
    with (
        patch("custom_components.ble_floorplan.dt_util", clock),
        patch("custom_components.ble_floorplan.coordinator.dt_util", clock),
        patch("custom_components.ble_floorplan.history.dt_util", clock),
    ):
        yield clock


def _stored(key: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "minor_version": 1, "key": key, "data": data}


def test_days() -> None:
    """Days are UTC dates; a day starts at midnight UTC."""
    assert day_of(NOON) == DAY
    assert day_start(DAY) == NOON - 12 * 3600
    assert day_of(day_start(DAY) - 1) == "2026-10-25"


async def test_points(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Seen again, gone, another room, or moved far enough after long enough."""
    history = HistoryStore(hass)
    await history.async_load(NOON, 7)
    # Off: nothing at all
    await history.async_record({"tag": _at(1.0)}, NOON, 0)
    assert await history.async_day(DAY) == {}
    # Not seen at the start says nothing
    await history.async_record({"tag": _at(None)}, NOON, 7)
    assert await history.async_day(DAY) == {}
    assert history.days == [DAY]
    assert hass_storage[INDEX]["data"] == {"days": [DAY]}
    steps = [
        (1.0, _at(1.004, 1.0)),  # seen: a point, rounded
        (2.0, _at(1.2)),  # too close
        (2.5, _at(1.5)),  # far enough, too soon
        (3.5, _at(1.5)),  # far enough, long enough
        (4.0, _at(1.6, room="Kitchen")),  # another room at once
        (5.0, _at(1.6, room="")),  # a room without a name is none
        (6.0, _at(None)),  # gone
        (7.0, _at(None)),  # still gone
        (8.0, _at(5.0)),  # back
    ]
    for dt, position in steps:
        await history.async_record({"tag": position}, NOON + dt, 7)
    assert (await history.async_day(DAY))["tag"] == [
        (NOON + 1, 1.0, 1.0, "Living room"),
        (NOON + 3.5, 1.5, 1.0, "Living room"),
        (NOON + 4, 1.6, 1.0, "Kitchen"),
        (NOON + 5, 1.6, 1.0, None),
        (NOON + 6, None, None, None),
        (NOON + 8, 5.0, 1.0, "Living room"),
    ]


async def test_delayed_write(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """Today's track is written a minute after the first new point."""
    freezer.move_to(datetime.fromtimestamp(NOON, UTC))
    history = HistoryStore(hass)
    await history.async_load(NOON, 7)
    await history.async_record({"tag": _at(1.0)}, NOON, 7)
    assert TODAY_KEY not in hass_storage
    freezer.tick(30)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert TODAY_KEY not in hass_storage
    await history.async_record({"tag": _at(3.0)}, NOON + 30, 7)
    freezer.tick(31)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    data = hass_storage[TODAY_KEY]["data"]
    assert data["saved"] == NOON + 61
    assert data["tracks"] == {
        "tag": [[NOON, 1.0, 1.0, "Living room"], [NOON + 30, 3.0, 1.0, "Living room"]]
    }


async def test_new_day(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """At midnight the old day is written, the new one starts where the trackers were."""
    history = HistoryStore(hass)
    await history.async_load(NOON, 7)
    midnight = day_start("2026-10-27")
    phone = TrackerPosition("phone", None, None, None, None, None, None, None, 0)
    await history.async_record({"tag": _at(2.0), "phone": phone}, midnight - 10, 7)
    await history.async_record({"tag": _at(2.0), "phone": phone}, midnight + 10, 7)
    assert hass_storage[TODAY_KEY]["data"]["tracks"]["tag"] == [
        [midnight - 10, 2.0, 1.0, "Living room"]
    ]
    assert history.days == [DAY, "2026-10-27"]
    assert await history.async_day("2026-10-27") == {"tag": [(midnight, 2.0, 1.0, "Living room")]}
    # The old day comes from storage now
    assert await history.async_day(DAY) == {"tag": [(midnight - 10, 2.0, 1.0, "Living room")]}


async def test_prune(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Days older than the timeline keeps go; days that are only listed are skipped."""
    old = ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"]
    hass_storage[INDEX] = _stored(INDEX, {"days": [*old, DAY]})
    for day in old:
        key = f"{HISTORY_STORAGE_KEY}.{day}"
        hass_storage[key] = _stored(key, {"saved": NOON, "tracks": {"tag": [[NOON, 1, 1, None]]}})
    del hass_storage[f"{HISTORY_STORAGE_KEY}.2026-10-20"]
    history = HistoryStore(hass)
    # Seven days back from noon reach into the 19th
    await history.async_load(NOON, 7)
    assert history.days == ["2026-10-19", "2026-10-20", DAY]
    assert f"{HISTORY_STORAGE_KEY}.2026-10-18" not in hass_storage
    assert hass_storage[INDEX]["data"] == {"days": ["2026-10-19", "2026-10-20", DAY]}
    assert await history.async_day("2026-10-19") == {"tag": [(NOON, 1, 1, None)]}
    assert await history.async_day("2026-10-20") == {}
    assert await history.async_day("2026-10-21") == {}
    # Nothing to drop: no write
    hass_storage[INDEX]["data"] = "untouched"
    await history.async_prune(NOON, 7)
    assert hass_storage[INDEX]["data"] == "untouched"
    # Off drops today as well
    hass_storage[INDEX]["data"] = {"days": history.days}
    await history.async_record({"tag": _at(1.0)}, NOON, 7)
    await history.async_prune(NOON, 0)
    assert history.days == []
    assert await history.async_day(DAY) == {}


async def test_restart(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """After a restart today goes on; a tracker seen at the last write gets a gap there."""
    hass_storage[INDEX] = _stored(INDEX, {"days": [DAY]})
    hass_storage[TODAY_KEY] = _stored(
        TODAY_KEY,
        {
            "saved": NOON + 60,
            "tracks": {
                "tag": [[NOON, 1.0, 1.0, "Living room"]],
                "phone": [[NOON, None, None, None]],
                "keys": [],
            },
        },
    )
    history = HistoryStore(hass)
    await history.async_load(NOON + 600, 7)
    await history.async_record({"tag": _at(1.0)}, NOON + 600, 7)
    assert (await history.async_day(DAY))["tag"] == [
        (NOON, 1.0, 1.0, "Living room"),
        (NOON + 60, None, None, None),
        (NOON + 600, 1.0, 1.0, "Living room"),
    ]
    assert (await history.async_day(DAY))["phone"] == [(NOON, None, None, None)]


async def test_close(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Closing ends the seen tracks with a gap and stops recording."""
    history = HistoryStore(hass)
    await history.async_load(NOON, 7)
    history.close(NOON)
    await history.async_record({"tag": _at(1.0)}, NOON, 7)
    assert await history.async_day(DAY) == {}
    history = HistoryStore(hass)
    await history.async_load(NOON, 7)
    phone = TrackerPosition("phone", None, None, None, None, None, None, None, 0)
    await history.async_record({"tag": _at(1.0), "phone": phone}, NOON, 7)
    await history.async_close(NOON + 5)
    await history.async_record({"tag": _at(3.0)}, NOON + 10, 7)
    assert hass_storage[TODAY_KEY]["data"]["tracks"] == {
        "tag": [[NOON, 1.0, 1.0, "Living room"], [NOON + 5, None, None, None]]
    }
    # Nothing seen: nothing to add
    again = HistoryStore(hass)
    await again.async_load(NOON, 7)
    await again.async_record({"phone": phone}, NOON, 7)
    again.close(NOON + 1)
    assert await again.async_day(DAY) == {
        "tag": [(NOON, 1.0, 1.0, "Living room"), (NOON + 5, None, None, None)]
    }


async def test_remove(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Removing drops every day and the index."""
    history = HistoryStore(hass)
    await history.async_load(NOON, 7)
    await history.async_record({"tag": _at(1.0)}, NOON, 7)
    await history.async_close(NOON)
    assert TODAY_KEY in hass_storage
    await HistoryStore(hass).async_remove()
    assert TODAY_KEY not in hass_storage
    assert INDEX not in hass_storage


async def test_recorded_by_the_coordinator(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
    wall: _Wall,
) -> None:
    """Every refresh feeds the timeline; the command returns a day; off drops it all."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SET_SETTINGS, "settings": {"history_days": 7}})
    assert (await client.receive_json())["success"]
    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0),  # type: ignore[arg-type]
        scanner_device(scanners["kitchen"], TAG, rssi_exact(6.5, -60, 2.0, 0.3), 1000.0),  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await entry.runtime_data.coordinator.async_refresh()
    await client.send_json_auto_id({"type": WS_HISTORY, "day": DAY})
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert result["day"] == DAY
    assert result["days"] == [DAY]
    assert "phone" not in result["tracks"]
    [point] = result["tracks"]["tag"]
    assert point[0] == NOON
    assert point[3] == "Living room"
    # Off: the days are gone
    await client.send_json_auto_id({"type": WS_SET_SETTINGS, "settings": {"history_days": 0}})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert entry.runtime_data.history.days == []
    assert INDEX in hass_storage


async def test_stop_and_unload(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
    hass_storage: dict[str, Any],
    wall: _Wall,
) -> None:
    """Home Assistant stopping or the entry unloading ends the tracks with a gap."""
    runtime = entry.runtime_data
    await runtime.store.async_save(with_settings(runtime.store.plan, {"history_days": 7}))
    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0),  # type: ignore[arg-type]
        scanner_device(scanners["kitchen"], TAG, rssi_exact(6.5, -60, 2.0, 0.3), 1000.0),  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await runtime.coordinator.async_refresh()
    history = runtime.history
    assert len((await history.async_day(DAY))["tag"]) == 1
    wall.t = NOON + 5
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert (await history.async_day(DAY))["tag"][-1] == (NOON + 5, None, None, None)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass_storage[TODAY_KEY]["data"]["tracks"]["tag"][-1] == [NOON + 5, None, None, None]
