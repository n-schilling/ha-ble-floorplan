"""Coverage: the model with probe scanners, the measurement per cell, the commands."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import math
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.const import (
    COVERAGE_CELL,
    COVERAGE_GOOD_RSSI,
    COVERAGE_STORAGE_KEY,
    WS_COVERAGE_MEASURED,
    WS_COVERAGE_MODEL,
    WS_COVERAGE_RESET,
)
from custom_components.ble_floorplan.coordinator import Reading, TrackerPosition
from custom_components.ble_floorplan.coverage import (
    FAIR,
    GOOD,
    POOR,
    CoverageStore,
    Probe,
    cell_of,
    grid,
    hdop,
    level,
    model,
    sample,
)
from custom_components.ble_floorplan.model import with_settings

from . import SCANNERS, TAG, FakeScanner, make_plan, rssi_exact, scanner_device
from .conftest import ScannerDevices

# 2026-10-26 12:00 UTC
NOON = datetime(2026, 10, 26, 12, tzinfo=UTC).timestamp()
DAY = "2026-10-26"


def _stored(data: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "minor_version": 1, "key": COVERAGE_STORAGE_KEY, "data": data}


def _position(
    x: float | None, y: float = 1.0, readings: dict[str, Reading] | None = None, key: str = "tag"
) -> TrackerPosition:
    if x is None:
        return TrackerPosition(key, TAG, None, None, None, None, None, None, 0)
    return TrackerPosition(key, TAG, x, y, x, y, "Living room", "living", 3, readings or {})


def _readings(**rssi: float | None) -> dict[str, Reading]:
    """Readings of the example's scanners; the distance is the true one to (2, 1)."""
    plan = make_plan()
    out = {}
    for key, value in rssi.items():
        scanner = plan.scanner(key)
        assert scanner is not None
        if value is None:
            out[key] = Reading(None, None, False)
        else:
            out[key] = Reading(value, math.hypot(scanner.x - 2, scanner.y - 1), True)
    return out


def test_hdop() -> None:
    """Even around the point it is small, in a line or alone there is none."""
    even = [(math.cos(a), math.sin(a)) for a in (0, 2 * math.pi / 3, 4 * math.pi / 3)]
    assert hdop(0, 0, even) == pytest.approx(math.sqrt(4 / 3))
    assert hdop(0, 0, [(1, 0), (2, 0), (-1, 0)]) is None
    assert hdop(0, 0, [(1, 0)]) is None
    # A scanner right at the point says nothing about the direction
    assert hdop(0, 0, [(0, 0), (1, 0), (0, 1)]) == pytest.approx(math.sqrt(2))
    # Three in a near line: much worse than around
    assert hdop(0, 0, [(1, 0), (2, 0.1), (-1, 0.05)]) > 5


def test_level() -> None:
    """Three good ones around: good; two: fair; one or three in a line: as said."""
    assert level(3, 1.2) == GOOD
    assert level(4, 2.0) == GOOD
    assert level(3, 2.5) == FAIR
    assert level(3, None) == FAIR
    assert level(2, 1.0) == FAIR
    assert level(1, None) == POOR
    assert level(0, None) == POOR


def test_grid() -> None:
    """Every cell whose centre lies in a room, zone or outdoor area; the plan is 10 x 11 m."""
    plan = make_plan()
    cells = grid(plan)
    assert len(cells) == 20 * 22 - 4 * 2  # the bedroom's notch at 0..2 / 8..9 is no room
    assert (0, 0) in cells
    assert (1, 17) not in cells
    assert (19, 21) in cells  # the balcony
    assert cell_of(0.49, 0.5) == (0, 1)


def test_model_without_tracker() -> None:
    """The default reference power, a tracker 1 m high, and no pair corrections."""
    plan = make_plan(settings={"ref_power_default": -55})
    result = model(plan)
    assert result["cell"] == COVERAGE_CELL
    assert result["good_rssi"] == COVERAGE_GOOD_RSSI
    assert result["probe_offset"] == 0
    cells = {(c[0], c[1]): c for c in result["cells"]}
    assert all(len(c) == 5 for c in cells.values())
    # Next to the living room scanner: all three are in reach of -85 dBm?
    x, y = 1.25, 1.25
    expected = sum(
        1
        for s in plan.scanners
        if -55 + s.rssi_offset - 30 * math.log10(math.hypot(math.hypot(s.x - x, s.y - y), s.z - 1))
        >= COVERAGE_GOOD_RSSI
    )
    assert cells[(2, 2)][3] == expected
    assert cells[(2, 2)][2] == GOOD
    rooms = {r["name"]: r["cells"] for r in result["rooms"]}
    assert set(rooms) == {"Living room", "Kitchen", "Bedroom", "Hall", "Dining", "Balcony"}
    assert sum(sum(c) for c in rooms.values()) == len(cells)


def test_model_weak_scanners_and_probes() -> None:
    """Weak scanners leave a poor plan; a probe in the middle makes cells better there."""
    scanners = [{**s, "rssi_offset": -25} for s in SCANNERS]
    plan = make_plan(scanners=scanners)
    plain = model(plan)
    assert {c[2] for c in plain["cells"]} == {POOR}
    assert model(make_plan(scanners=[]))["probe_offset"] == 0
    probes = [Probe(5, 5), Probe(5, 2, 2.0), Probe(2, 7)]
    result = model(plan, None, probes)
    assert result["probe_offset"] == -25
    cells = {(c[0], c[1]): c for c in result["cells"]}
    assert all(len(c) == 6 for c in cells.values())
    # Without the probes poor, with them better: the last value is the level without
    better = [c for c in cells.values() if c[2] > c[5]]
    assert better
    assert all(c[5] == POOR for c in cells.values())


def test_model_of_a_tracker() -> None:
    """The tracker's own reference power, height and pair corrections count."""
    plan = make_plan(pair_offsets={"living": {"tag": -40}})
    tag = plan.tracker("tag")
    assert tag is not None
    cells = {(c[0], c[1]): c for c in model(plan, tag)["cells"]}
    default = {(c[0], c[1]): c for c in model(plan)["cells"]}
    # Right at the living room scanner: muted for the tag, heard for the default
    assert cells[(2, 2)][3] < default[(2, 2)][3]


def test_sample() -> None:
    """Good scanners from the RSSI, the miss of the circles, the level at the position."""
    plan = make_plan()
    assert sample(plan, _position(None)) is None
    # Living near and loud, kitchen loud, bedroom too quiet, nothing else
    readings = _readings(living=-60, kitchen=-80, bedroom=-90)
    got = sample(plan, _position(2.0, 1.0, readings))
    assert got is not None
    cell, stats = got
    assert cell == "4,2"
    assert stats[0] == 1
    assert stats[1] == 2
    assert stats[2] == FAIR
    assert stats[3] == pytest.approx(0.0)
    # A scanner that did not go in counts for nothing
    readings = {**_readings(living=-60), "kitchen": Reading(None, None, False)}
    assert sample(plan, _position(2.0, 1.0, readings)) == ("4,2", [1, 1, POOR, 0.0])
    # No scanner used: no miss
    assert sample(plan, _position(2.0, 1.0, {})) == ("4,2", [1, 0, POOR, 0.0])
    # The circle misses by a metre
    off = {"living": Reading(-60, 2.0, True)}
    assert sample(plan, _position(2.0, 1.0, off))[1][3] == pytest.approx(1.0)  # type: ignore[index]


async def test_record_and_measured(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Samples add up per tracker, day and cell; cells need 30 s; rooms are weighted by time."""
    plan = make_plan()
    coverage = CoverageStore(hass)
    await coverage.async_load(NOON, 7)
    good = _readings(living=-60, kitchen=-70, bedroom=-70)
    # Off: nothing
    coverage.record(plan, {"tag": _position(2.0, 1.0, good)}, NOON, 0)
    # Not seen: nothing, not even a day
    coverage.record(plan, {"tag": _position(None)}, NOON, 7)
    assert coverage.days == {}
    for i in range(40):
        coverage.record(
            plan,
            {
                "tag": _position(2.0, 1.0, good),
                "phone": _position(8.0, 3.0, _readings(kitchen=-60), key="phone"),
            },
            NOON + i,
            7,
        )
    # Too short for a cell of its own
    for i in range(10):
        coverage.record(plan, {"tag": _position(2.0, 6.0, good)}, NOON + i, 7)
    assert set(coverage.days[DAY]) == {"tag", "phone"}
    result = coverage.measured(plan)
    assert result["days"] == [DAY]
    cells = {(c[0], c[1]): c for c in result["cells"]}
    assert set(cells) == {(4, 2), (16, 6)}
    assert cells[(4, 2)][2:] == [GOOD, 3.0, 0.0, 40]
    # The kitchen's distance was meant for (2, 1): its circle misses (8, 3) by 4.76 m
    assert cells[(16, 6)][2:] == [POOR, 1.0, 4.76, 40]
    rooms = {r["name"]: r for r in result["rooms"]}
    assert rooms["Living room"] == {"name": "Living room", "level": 2.0, "good": 3.0, "seconds": 40}
    assert rooms["Kitchen"]["level"] == 0.0
    only = coverage.measured(plan, "phone")
    assert [(c[0], c[1]) for c in only["cells"]] == [(16, 6)]
    # A fair cell between: half good, half poor samples
    mixed = CoverageStore(hass)
    for i in range(20):
        mixed.record(plan, {"tag": _position(5.0, 4.0, good)}, NOON + i, 7)
        mixed.record(plan, {"tag": _position(5.0, 4.0, _readings(living=-60))}, NOON + i, 7)
    assert mixed.measured(plan)["cells"][0][2] == FAIR
    # A cell in no named room counts in no room
    unnamed = CoverageStore(hass)
    for i in range(30):
        unnamed.record(plan, {"tag": _position(1.0, 8.6, good)}, NOON + i, 7)
    assert (
        unnamed.measured(make_plan(rooms=[{"name": "", "x": 0, "y": 0, "w": 10, "h": 11}]))["rooms"]
        == []
    )


async def test_delayed_write_prune_and_reset(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """Written a minute after the first sample; old days go; a reset forgets all."""
    freezer.move_to(datetime.fromtimestamp(NOON, UTC))
    hass_storage[COVERAGE_STORAGE_KEY] = _stored(
        {"cell": COVERAGE_CELL, "days": {"2026-10-01": {"tag": {"0,0": [1, 1, 0, 0.0]}}}}
    )
    plan = make_plan()
    coverage = CoverageStore(hass)
    await coverage.async_load(NOON, 7)
    assert coverage.days == {}
    assert hass_storage[COVERAGE_STORAGE_KEY]["data"]["days"] == {}
    coverage.record(plan, {"tag": _position(2.0)}, NOON, 7)
    coverage.record(plan, {"tag": _position(2.0)}, NOON + 1, 7)
    freezer.tick(61)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass_storage[COVERAGE_STORAGE_KEY]["data"]["days"] == {
        DAY: {"tag": {"4,2": [2, 0, 0, 0.0]}}
    }
    # Nothing old to prune: no write
    hass_storage[COVERAGE_STORAGE_KEY]["data"] = "untouched"
    await coverage.async_prune(NOON, 7)
    assert hass_storage[COVERAGE_STORAGE_KEY]["data"] == "untouched"
    # 0 days: all go
    await coverage.async_prune(NOON, 0)
    assert coverage.days == {}
    coverage.record(plan, {"tag": _position(2.0)}, NOON, 7)
    await coverage.async_reset()
    assert coverage.days == {}
    assert hass_storage[COVERAGE_STORAGE_KEY]["data"] == {"cell": COVERAGE_CELL, "days": {}}
    await coverage.async_remove()
    assert COVERAGE_STORAGE_KEY not in hass_storage


async def test_unreadable_or_other_cell(
    hass: HomeAssistant, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A store that cannot be read starts anew with a warning, one of another cell size quietly."""
    hass_storage[COVERAGE_STORAGE_KEY] = _stored({"cell": 0.5, "days": {DAY: {"tag": []}}})
    coverage = CoverageStore(hass)
    await coverage.async_load(NOON, 7)
    assert coverage.days == {}
    assert "The coverage cannot be read" in caplog.text
    hass_storage[COVERAGE_STORAGE_KEY] = _stored(
        {"cell": 1.0, "days": {DAY: {"tag": {"0,0": [1, 1, 0, 0.0]}}}}
    )
    other = CoverageStore(hass)
    await other.async_load(NOON, 7)
    assert other.days == {}


async def test_close(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Closed, nothing more is recorded; an unload writes at once."""
    plan = make_plan()
    coverage = CoverageStore(hass)
    await coverage.async_load(NOON, 7)
    coverage.record(plan, {"tag": _position(2.0)}, NOON, 7)
    await coverage.async_close()
    assert hass_storage[COVERAGE_STORAGE_KEY]["data"]["days"][DAY]["tag"]["4,2"][0] == 1
    coverage.record(plan, {"tag": _position(2.0)}, NOON + 1, 7)
    assert coverage.days[DAY]["tag"]["4,2"][0] == 1


async def test_coordinator_records(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
    hass_storage: dict[str, Any],
) -> None:
    """With the timeline on, every computation adds a sample; a stop ends the recording."""
    runtime = entry.runtime_data
    await runtime.coordinator.async_refresh()
    assert runtime.coverage.days == {}
    await runtime.store.async_save(with_settings(runtime.store.plan, {"history_days": 7}))
    plan = runtime.store.plan
    tag = plan.tracker("tag")
    assert tag is not None
    devices = []
    for key, name in (("living", "living"), ("kitchen", "kitchen"), ("bedroom", "bedroom")):
        s = plan.scanner(key)
        assert s is not None
        d = math.hypot(s.x - 3, s.y - 2)
        devices.append(
            scanner_device(scanners[name], TAG, round(rssi_exact(d, -60, s.z, tag.height)), 1001.0)
        )
    scanner_devices[TAG] = devices
    clock(1002.0)
    await runtime.coordinator.async_refresh()
    (day,) = runtime.coverage.days.values()
    assert sum(stats[0] for stats in day["tag"].values()) == 1
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    clock(1003.0)
    await runtime.coordinator.async_refresh()
    assert sum(stats[0] for stats in day["tag"].values()) == 1
    # A shorter timeline prunes the coverage too
    await runtime.store.async_save(with_settings(runtime.store.plan, {"history_days": 0}))
    await hass.async_block_till_done()
    assert runtime.coverage.days == {}


async def test_remove_deletes_the_coverage(
    hass: HomeAssistant, entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Removing the entry removes the stored coverage."""
    await entry.runtime_data.coverage.async_reset()
    assert COVERAGE_STORAGE_KEY in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert COVERAGE_STORAGE_KEY not in hass_storage


async def test_commands(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """The model with a tracker and probes, the measurement, the reset."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_COVERAGE_MODEL, "tracker": "tag", "probes": [{"x": 5, "y": 5, "z": 2}]}
    )
    msg = await client.receive_json()
    assert msg["success"]
    assert len(msg["result"]["cells"][0]) == 6
    await client.send_json_auto_id({"type": WS_COVERAGE_MODEL})
    msg = await client.receive_json()
    assert len(msg["result"]["cells"][0]) == 5
    await client.send_json_auto_id({"type": WS_COVERAGE_MODEL, "probes": [{"x": 1, "y": 1}] * 6})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "invalid_format"
    await client.send_json_auto_id({"type": WS_COVERAGE_MODEL, "tracker": "nobody"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"

    plan = entry.runtime_data.store.plan
    for i in range(30):
        entry.runtime_data.coverage.record(plan, {"tag": _position(2.0)}, NOON + i, 7)
    await client.send_json_auto_id({"type": WS_COVERAGE_MEASURED, "tracker": "tag"})
    msg = await client.receive_json()
    assert msg["result"]["recording"] is False
    assert msg["result"]["cells"] == [[4, 2, POOR, 0.0, 0.0, 30]]
    await client.send_json_auto_id({"type": WS_COVERAGE_MEASURED, "tracker": "nobody"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"
    await client.send_json_auto_id({"type": WS_COVERAGE_RESET})
    msg = await client.receive_json()
    assert msg["success"]
    await client.send_json_auto_id({"type": WS_COVERAGE_MEASURED})
    msg = await client.receive_json()
    assert msg["result"]["cells"] == []


async def test_commands_need_an_admin_and_the_entry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """Only administrators; not_loaded once the entry is unloaded."""
    messages = (
        {"type": WS_COVERAGE_MODEL},
        {"type": WS_COVERAGE_MEASURED},
        {"type": WS_COVERAGE_RESET},
    )
    user = await hass_ws_client(hass, hass_read_only_access_token)
    for message in messages:
        await user.send_json_auto_id(message)
        msg = await user.receive_json()
        assert msg["error"]["code"] == "unauthorized"
    client = await hass_ws_client(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    for message in messages:
        await client.send_json_auto_id(message)
        msg = await client.receive_json()
        assert msg["error"]["code"] == "not_loaded"


async def test_edge_cells(hass: HomeAssistant) -> None:
    """A cell over the outer wall counts for the room inside it, in the model and the measurement."""
    plan = make_plan(rooms=[{"name": "Wide", "x": 0, "y": 0, "w": 10.2, "h": 1}])
    cells = {(c[0], c[1]) for c in model(plan)["cells"]}
    assert (20, 0) in cells
    assert sum(model(plan)["rooms"][0]["cells"]) == len(cells) == 21 * 2
    coverage = CoverageStore(hass)
    for i in range(30):
        coverage.record(plan, {"tag": _position(10.1, 0.5)}, NOON + i, 7)
    result = coverage.measured(plan)
    assert result["cells"][0][:2] == [20, 1]
    assert (20, 1) in cells
    assert [r["name"] for r in result["rooms"]] == ["Wide"]
