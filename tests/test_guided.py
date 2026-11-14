"""Guided calibration: progress per scanner, ending by itself, and where runs are missing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.calibration import (
    CalibrationRun,
    CalibrationStore,
    guide,
    scanner_progress,
    setup_matches,
)
from custom_components.ble_floorplan.const import WS_CALIBRATION_START

from . import TAG, FakeScanner, make_plan, scanner_device
from .conftest import ScannerDevices

SETUP = {"living": (1.0, 1.0, 0.8), "kitchen": (9.0, 1.0, 2.0), "bedroom": (1.0, 8.0, 0.5)}


def _run(
    tracker: str = "tag",
    x: float = 2.0,
    y: float = 2.0,
    scanners: dict[str, tuple[float, float, float]] | None = SETUP,
    duration: float | None = 60.0,
) -> CalibrationRun:
    return CalibrationRun(
        "id", tracker, x, y, 0.3, "2026-11-14T10:00:00+00:00", duration, {}, scanners
    )


def test_scanner_progress() -> None:
    """Done with enough samples or a well-known mean; weak when it hears too seldom."""
    assert scanner_progress([], 10.0) == {"count": 0, "error": None, "state": "collecting"}
    assert scanner_progress([(1.0, -60)], 10.0)["error"] is None
    steady = [(float(i), -60.0 + (i % 2)) for i in range(15)]
    progress = scanner_progress(steady, 20.0)
    assert progress["state"] == "done"
    assert progress["error"] is not None and progress["error"] < 0.2
    noisy = [(float(i), -60.0 + 20 * (i % 2)) for i in range(15)]
    assert scanner_progress(noisy, 20.0)["state"] == "collecting"
    assert scanner_progress(noisy + noisy, 40.0)["state"] == "done"
    # Four samples in 60 s: too seldom to wait for
    assert scanner_progress(noisy[:4], 60.0)["state"] == "weak"
    # The same four early in the run still count as collecting
    assert scanner_progress(noisy[:4], 30.0)["state"] == "collecting"


async def test_tick_ends_a_run(hass: HomeAssistant) -> None:
    """A run ends by itself after the shortest time once every scanner is done or weak."""
    store = CalibrationStore(hass)
    await store.async_load()
    assert store.tick(1000.0) is False

    # Without auto_stop: only the length is noted
    await store.async_start("tag", 2.0, 2.0, 0.3, 1000.0)
    for i in range(40):
        store.add_sample("living", 1000.0 + i, -60)
    assert store.tick(1100.0) is False
    assert store.progress()["elapsed"] == 100.0
    assert store.progress()["max_seconds"] is None
    await store.async_stop(1100.0)

    await store.async_start("tag", 2.0, 2.0, 0.3, 2000.0, auto_stop=True)
    assert store.progress()["max_seconds"] == 300.0
    for i in range(40):
        store.add_sample("living", 2000.0 + i, -60 + (i % 2))
    # Enough samples, but not yet the shortest time
    assert store.tick(2040.0) is False
    # A scanner still collecting holds the run up
    for i in range(10):
        store.add_sample("kitchen", 2000.0 + 4 * i, -75 + 2 * (i % 2))
    assert store.tick(2046.0) is False
    # A scanner that hears too seldom does not
    store.add_sample("bedroom", 2010.0, -90)
    for i in range(10):
        store.add_sample("kitchen", 2041.0 + i, -75 + 2 * (i % 2))
    assert store.progress()["scanners"]["kitchen"]["state"] == "done"
    assert store.tick(2060.0) is True
    await store.async_stop(2060.0)

    # Nothing done at all: the run ends at the latest after the longest time
    await store.async_start("tag", 2.0, 2.0, 0.3, 3000.0, auto_stop=True)
    assert store.tick(3100.0) is False
    assert store.tick(3300.0) is True


async def test_stopped_kept_until_the_next_start(hass: HomeAssistant) -> None:
    """What a stop saved stays in the event until a new run or a clear."""
    store = CalibrationStore(hass)
    await store.async_load()
    run = await store.async_start("tag", 2.0, 2.0, 0.3, 1000.0)
    await store.async_stop(1010.0, notify=False)
    store.note_stopped(run, None, True)
    assert store.as_event()["stopped"] == {"run": run.id, "auto": True, "fit": None}
    await store.async_start("tag", 2.0, 2.0, 0.3, 1020.0)
    assert "stopped" not in store.as_event()
    await store.async_stop(1030.0, notify=False)
    store.note_stopped(run, None, False)
    await store.async_clear()
    assert "stopped" not in store.as_event()


def test_setup_matches() -> None:
    """Same scanners within 5 cm; moved, added or removed is another setup; unknown tells nothing."""
    plan = make_plan()
    assert setup_matches(_run(), plan) is True
    assert setup_matches(_run(scanners=None), plan) is None
    assert setup_matches(_run(scanners={**SETUP, "living": (1.04, 1.0, 0.8)}), plan) is True
    assert setup_matches(_run(scanners={**SETUP, "living": (1.2, 1.0, 0.8)}), plan) is False
    assert setup_matches(_run(scanners={**SETUP, "living": (1.0, 1.0, 1.8)}), plan) is False
    assert setup_matches(_run(scanners={"living": SETUP["living"]}), plan) is False


def test_guide() -> None:
    """Per tracker every room with walls and the runs that count there."""
    plan = make_plan()
    runs = [
        _run(x=2.0, y=2.0),  # Living room
        _run(x=4.0, y=1.0),  # The Dining zone lies in the living room: counts for it
        _run(x=8.0, y=2.0, scanners=None),  # Kitchen, setup unknown: counts
        _run(x=8.0, y=7.0, scanners={**SETUP, "kitchen": (5.0, 5.0, 2.0)}),  # Hall, moved since
        _run(x=1.0, y=6.0, duration=None),  # Bedroom, still going
        _run(tracker="phone", x=1.0, y=6.0),  # Bedroom, for the phone
        _run(x=20.0, y=20.0),  # Outside the plan
    ]
    result = guide(plan, runs)
    assert result["tag"] == [
        {"room": "Living room", "floor": "", "runs": 2},
        {"room": "Kitchen", "floor": "", "runs": 1},
        {"room": "Bedroom", "floor": "", "runs": 0},
        {"room": "Hall", "floor": "", "runs": 0},
        {"room": "Balcony", "floor": "", "runs": 0},
    ]
    assert {r["room"]: r["runs"] for r in result["phone"]}["Bedroom"] == 1
    # A room in two parts is listed once
    split = replace(plan, rooms=(*plan.rooms, replace(plan.rooms[0], x=20.0)))
    assert [r["room"] for r in guide(split, [])["tag"]].count("Living room") == 1


async def test_coordinator_ends_a_run_by_itself(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """With auto_stop the refresh stops the run once it has enough and saves the tracker's values."""
    coordinator = entry.runtime_data.coordinator
    calibration = entry.runtime_data.calibration
    clock(1000.0)
    run = await coordinator.async_start_calibration("tag", 2.0, 2.0, 0.3, auto_stop=True)
    for t in range(1, 61):
        scanner_devices[TAG] = [
            scanner_device(scanners["living"], TAG, -60 + (t % 2), 1000.0 + t),
            scanner_device(scanners["kitchen"], TAG, -75 + (t % 2), 1000.0 + t),
        ]
        clock(1000.5 + t)
        await coordinator.async_refresh()
        if calibration.active is None:
            break
    assert calibration.active is None
    assert run.duration is not None and 45.0 <= run.duration < 60.0
    stopped = calibration.as_event()["stopped"]
    assert stopped["run"] == run.id
    assert stopped["auto"] is True
    assert stopped["fit"] is not None


async def test_ws_start_with_auto_stop(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """calibration/start takes auto_stop; without it the run goes until stopped."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_CALIBRATION_START, "tracker": "tag", "x": 2, "y": 2, "auto_stop": True}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert entry.runtime_data.calibration.auto_stop is True
