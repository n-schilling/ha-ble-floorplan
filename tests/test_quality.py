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
from custom_components.ble_floorplan.quality import Heard, QualityTracker, contribution

from . import TAG, FakeScanner, make_plan, rssi_exact, scanner_device
from .conftest import ScannerDevices

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
    quality = QualityTracker()
    quality.begin(1793016000.0)
    assert quality.since == 1793016000.0
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
    quality.begin(1793016000.0 + 25 * 3600)
    assert quality.rate("esp")["state"] == "unknown"


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
    # Far off the plan: no cell needs it
    far = replace(plan.scanners[1], key="far", source="AA:BB:CC:DD:EE:0F", x=80.0, y=80.0)
    assert contribution(replace(plan, scanners=(*plan.scanners, far)), "far")["state"] == "poor"


def test_findings() -> None:
    """The findings name the trouble, the most telling first; good when there is none."""
    quality = QualityTracker()
    quality.begin(1793016000.0)
    good = {"worse": 10, "cells": 50, "share": 0.2, "state": "good"}
    poor = {"worse": 0, "cells": 50, "share": 0.0, "state": "poor"}
    assert quality.report("a", good)["findings"] == ["few_data"]
    _feed(quality, {**TRUE, "e": (2.5, 3.0)}, {"c": 5.0})
    for key in TRUE:
        for _ in range(100 if key != "d" else 20):
            quality.count("tag", key)
    report = quality.report("a", good)
    assert report["findings"] == ["good"]
    assert report["hours"] == 1
    assert quality.report("e", good)["findings"][0] == "plan_position"
    assert quality.report("c", good)["findings"] == ["site"]
    assert quality.report("d", poor)["findings"] == ["device", "redundant"]


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
