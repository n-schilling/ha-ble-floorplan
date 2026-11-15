"""Scanner quality: reception, fidelity with the shift it suggests, contribution, findings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import math
import random
from typing import Any

from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.const import WS_SCANNER_QUALITY
from custom_components.ble_floorplan.model import Floorplan
from custom_components.ble_floorplan.quality import Heard, QualityTracker, contribution

from . import TAG, FakeScanner, make_plan, rssi_exact, scanner_device
from .conftest import ScannerDevices

NOW = 1793016000.0  # on the full hour


def _plan(*keys: str, **moved: float) -> Floorplan:
    """The example plan with scanners of the keys, all where the first one stands; moved[key] is its x instead."""
    base = make_plan()
    first = base.scanners[0]
    return replace(
        base,
        scanners=tuple(
            replace(first, key=k, source=f"AA:BB:CC:DD:EE:{i + 0x20:02X}", x=moved.get(k, first.x))
            for i, k in enumerate(keys)
        ),
        pair_offsets={},
    )


def _quality(*keys: str, now: float = NOW) -> QualityTracker:
    """A tracker gathering for scanners of the keys, from now."""
    quality = QualityTracker()
    quality.begin(now)
    quality.setup(_plan(*keys))
    return quality


# Four scanners in the corners of a room of 10 x 8 m and one in its middle: where they truly stand
TRUE = {"a": (0.0, 0.0), "b": (10.0, 0.0), "c": (10.0, 8.0), "d": (0.0, 8.0), "e": (4.0, 3.0)}


def _feed(
    quality: QualityTracker,
    plan_at: dict[str, tuple[float, float]],
    noise: dict[str, float] | None = None,
    count: int = 400,
) -> None:
    """Trackers all over the room; distances from where the scanners truly stand, held against the plan."""
    rng = random.Random(3)
    for _ in range(count):
        p = (rng.uniform(1, 9), rng.uniform(1, 7))
        heard = []
        for key, (x, y) in TRUE.items():
            d = math.dist(p, (x, y)) + rng.gauss(0, (noise or {}).get(key, 0.0))
            heard.append(Heard(key, *plan_at[key], max(d, 0.1)))
        quality.misses(heard, p)


def test_fidelity_good_and_shift() -> None:
    """Exact circles fit; a scanner that stands 1.5 m right of where the plan has it is found there.

    Only where trackers lie all around it: in a corner the shift looks like an offset.
    """
    quality = QualityTracker()
    quality.begin(1793016000.0)
    _feed(quality, TRUE)
    good = quality.fidelity("a")
    assert good["state"] == "good"
    assert good["spread"] < 0.1
    assert good["shift"] is None
    # All around and exact: no shift worth naming
    assert quality.fidelity("e")["shift"] is None
    moved = QualityTracker()
    moved.begin(1793016000.0)
    _feed(moved, {**TRUE, "b": (8.5, 0.0), "e": (2.5, 3.0)})
    assert moved.fidelity("b")["shift"] is None
    shifted = moved.fidelity("e")
    assert shifted["shift"] is not None
    assert shifted["shift"]["dx"] > 1.0
    assert abs(shifted["shift"]["dy"]) < 0.5
    assert shifted["state"] in ("fair", "poor")


def test_fidelity_noise_and_few() -> None:
    """A scanner whose distances scatter is poor; too few misses tell nothing; one scanner too few is skipped."""
    quality = QualityTracker()
    quality.begin(1793016000.0)
    _feed(quality, TRUE, {"c": 5.0})
    noisy = quality.fidelity("c")
    assert noisy["state"] == "poor"
    assert noisy["outliers"] > 0.2
    few = QualityTracker()
    few.begin(1793016000.0)
    _feed(few, TRUE, count=10)
    assert few.fidelity("a")["state"] == "unknown"
    few.misses([Heard("a", 0, 0, 1), Heard("b", 1, 0, 1), Heard("c", 0, 1, 1)], (0.5, 0.5))
    # On top of a scanner: no direction, no miss
    few.misses([Heard(k, x, y, 1.0) for k, (x, y) in TRUE.items()], (0.1, 0.1))


def test_rate_and_hours() -> None:
    """Reception against the best scanner of each tracker; old hours drop out."""
    quality = _quality("esp", "shelly", "pi")
    assert quality.since("esp") == NOW
    assert quality.since("nobody") is None
    for _ in range(100):
        quality.count("tag", "esp")
    for _ in range(30):
        quality.count("tag", "shelly")
    for _ in range(50):
        quality.count("tag", "pi")
    # A tracker heard too little does not count
    for _ in range(10):
        quality.count("phone", "shelly")
    assert quality.rate("esp") == {"value": 1.0, "trackers": 1, "state": "good"}
    assert quality.rate("pi")["state"] == "fair"
    assert quality.rate("shelly")["state"] == "poor"
    assert quality.rate("nobody")["state"] == "unknown"
    assert quality.summary("shelly")["state"] == "poor"
    assert quality.summary("nobody")["state"] == "unknown"
    quality.begin(NOW + 25 * 3600)
    assert quality.rate("esp")["state"] == "unknown"
    # The start moves up with the hours that still count
    assert quality.since("esp") == NOW + 2 * 3600


def test_start_per_scanner() -> None:
    """Each scanner counts from its own start: new, moved or recalibrated ones start afresh, gone ones are dropped.

    Its reception is held against the others only over the full hours since its start.
    """
    quality = _quality("esp", "old")
    for _ in range(100):
        quality.count("tag", "esp")
        quality.count("tag", "old")
    # Half an hour on: a scanner comes in, one moves
    quality.begin(NOW + 1800)
    plan = _plan("esp", "old", "new", old=5.0)
    quality.setup(plan)
    assert quality.since("esp") == NOW
    assert quality.since("old") == NOW + 1800
    assert quality.since("new") == NOW + 1800
    assert quality.rate("old")["state"] == "unknown"
    # In the hour it started, only what the others took after it counts against it
    for _ in range(100):
        quality.count("tag", "esp")
    for _ in range(80):
        quality.count("tag", "new")
    assert quality.rate("new") == {"value": 0.8, "trackers": 1, "state": "good"}
    # The next hour: both counted alike
    quality.begin(NOW + 3600)
    quality.setup(plan)
    for _ in range(100):
        quality.count("tag", "esp")
    for _ in range(50):
        quality.count("tag", "new")
    assert quality.rate("new")["value"] == 0.65
    assert quality.rate("esp")["value"] == 1.0
    # A changed pair correction is a new setup; the same plan again changes nothing
    quality.begin(NOW + 4000)
    quality.setup(plan)
    assert quality.since("new") == NOW + 1800
    quality.setup(replace(plan, pair_offsets={"new": {"tag": 2.0}}))
    assert quality.since("new") == NOW + 4000
    # Nothing since: the hours before tell of the old setup
    assert quality.rate("new")["state"] == "unknown"
    assert quality.since("esp") == NOW
    # Gone from the plan: forgotten
    quality.setup(_plan("esp"))
    assert quality.since("new") is None
    assert all(k[1] == "esp" for h in quality._hours.values() for k in h.counts)


def test_contribution() -> None:
    """Without a scanner cells get worse; paused, unknown or a plan without rooms tell nothing."""
    plan = make_plan()
    part = contribution(plan, "kitchen")
    assert part["worse"] > 0
    assert part["state"] in ("good", "fair")
    assert contribution(plan, "nope")["state"] == "unknown"
    paused = replace(plan, scanners=tuple(replace(s, paused=True) for s in plan.scanners))
    assert contribution(paused, "kitchen")["state"] == "unknown"
    assert contribution(replace(plan, rooms=()), "kitchen")["state"] == "unknown"
    # A second scanner right beside one adds hardly any precision; the first one alone does
    kitchen = plan.scanner("kitchen")
    assert kitchen is not None
    twin = replace(kitchen, key="twin", source="AA:BB:CC:DD:EE:0E", x=kitchen.x + 0.1)
    doubled = replace(plan, scanners=(*plan.scanners, twin))
    assert contribution(doubled, "twin")["worse"] < part["worse"]
    # Far off the plan: no cell needs it
    far = replace(plan.scanners[1], key="far", source="AA:BB:CC:DD:EE:0F", x=80.0, y=80.0)
    assert contribution(replace(plan, scanners=(*plan.scanners, far)), "far")["state"] == "poor"


def test_findings() -> None:
    """The findings name the trouble, the most telling first; good when there is none."""
    quality = _quality(*TRUE)
    good = {"worse": 10, "cells": 50, "share": 0.2, "state": "good"}
    poor = {"worse": 0, "cells": 50, "share": 0.0, "state": "poor"}
    assert quality.report("a", good)["findings"] == ["few_data"]
    _feed(quality, {**TRUE, "e": (2.5, 3.0)}, {"c": 5.0})
    for key in TRUE:
        for _ in range(100 if key != "d" else 20):
            quality.count("tag", key)
    report = quality.report("a", good)
    assert report["findings"] == ["good"]
    assert report["since"] == NOW
    assert report["hours"] == 0.0
    quality.begin(NOW + 5400)
    assert quality.report("a", good)["hours"] == 1.5
    assert quality.report("e", good)["findings"][0] == "plan_position"
    assert quality.report("c", good)["findings"] == ["site"]
    # Seldom heard: on a Shelly that is the device, elsewhere the place
    assert quality.report("d", poor)["findings"] == ["reception", "redundant"]
    assert quality.report("d", poor, shelly=True)["findings"] == ["device", "redundant"]
    assert quality.report("nobody", good)["hours"] is None


async def test_coordinator_counts(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """Every new advertisement counts for its scanner."""
    coordinator = entry.runtime_data.coordinator
    for t in range(3):
        scanner_devices[TAG] = [
            scanner_device(scanners[k], TAG, rssi_exact(3.0, -60), 1000.0 + t)  # type: ignore[arg-type]
            for k in ("living", "kitchen", "bedroom")
        ]
        clock(1000.5 + t)
        await coordinator.async_refresh()
    counts = next(iter(coordinator.quality._hours.values())).counts
    assert counts[("tag", "living")] == 3


async def test_ws_scanner_quality(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """With a key the full report, without one the cheap part of each scanner."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SCANNER_QUALITY, "key": "kitchen"})
    msg: dict[str, Any] = await client.receive_json()
    assert msg["success"], msg
    assert set(msg["result"]) == {"since", "hours", "rate", "fidelity", "contribution", "findings"}
    await client.send_json_auto_id({"type": WS_SCANNER_QUALITY})
    msg = await client.receive_json()
    assert set(msg["result"]) == {"living", "kitchen", "bedroom"}
    await client.send_json_auto_id({"type": WS_SCANNER_QUALITY, "key": "nope"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"


async def test_kept_in_storage(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Written along the way and on an unload, loaded again; a shorter setting drops old hours."""
    from freezegun import freeze_time

    from custom_components.ble_floorplan.const import QUALITY_STORAGE_KEY

    now = 1793016000.0
    quality = QualityTracker(hass)
    await quality.async_load(now, 24)
    assert quality.since("esp") is None
    with freeze_time("2026-11-14 12:00:00"):
        quality.begin(now)
        quality.setup(_plan("esp", *TRUE))
        for _ in range(5):
            quality.count("tag", "esp")
        _feed(quality, TRUE, count=20)
        quality.begin(now + 3600, 24)
        quality.count("tag", "esp")
        # One that comes in later: what the others took before it in that hour is kept aside
        quality.setup(_plan("esp", "late", *TRUE))
        await quality.async_save()
    stored = hass_storage[QUALITY_STORAGE_KEY]["data"]
    assert stored["scanners"]["esp"]["since"] == now
    assert stored["scanners"]["late"] == {
        "since": now + 3600,
        "basis": stored["scanners"]["esp"]["basis"],
        "base": {"tag|esp": 1},
    }
    assert len(stored["hours"]) == 2

    again = QualityTracker(hass)
    await again.async_load(now + 3600, 24)
    assert again.since("esp") == now
    assert again._starts["late"].base == {("tag", "esp"): 1}
    assert sum(h.counts.get(("tag", "esp"), 0) for h in again._hours.values()) == 6
    assert sum(h.misses["a"][0] for h in again._hours.values() if "a" in h.misses) == 20
    # One hour kept: the older one goes, the start moves up with it
    again.begin(now + 3600, 1)
    assert len(again._hours) == 1
    assert again.since("esp") == (int(now // 3600) + 1) * 3600.0
    # Loaded with the same plan: the setup is the same, nothing starts afresh
    again.setup(_plan("esp", *TRUE))
    assert again.since("esp") == (int(now // 3600) + 1) * 3600.0
    assert sum(h.counts.get(("tag", "esp"), 0) for h in again._hours.values()) == 1
    # Too old by the time it loads: nothing left
    late = QualityTracker(hass)
    await late.async_load(now + 48 * 3600, 24)
    assert late._hours == {}
    await late.async_remove()
    assert QUALITY_STORAGE_KEY not in hass_storage
    # The one start of all scanners from before is not used
    hass_storage[QUALITY_STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": QUALITY_STORAGE_KEY,
        "data": {"since": now, "hours": {}},
    }
    older = QualityTracker(hass)
    await older.async_load(now, 24)
    assert older.since("esp") is None
    # Without hass nothing is stored
    await QualityTracker().async_save()
    await QualityTracker().async_remove()


async def test_written_after_a_while(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """The delayed write carries what came in."""
    from datetime import timedelta

    from pytest_homeassistant.common import async_fire_time_changed

    from homeassistant.util import dt as dt_util

    from custom_components.ble_floorplan.const import QUALITY_STORAGE_KEY

    quality = QualityTracker(hass)
    await quality.async_load(1793016000.0, 24)
    quality.begin(1793016000.0)
    quality.count("tag", "esp")
    quality.begin(1793016001.0)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=301))
    await hass.async_block_till_done()
    assert hass_storage[QUALITY_STORAGE_KEY]["data"]["hours"]
