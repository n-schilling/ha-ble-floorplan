"""The position engine: RSSI to distance, weighted trilateration, smoothing.

Ports of the card's JavaScript; the tests check them against its numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
import statistics

from .geometry import Point
from .model import Floorplan


@dataclass(frozen=True, slots=True)
class Measurement:
    """A scanner's position on the plan and its distance to the tracker, in metres."""

    x: float
    y: float
    distance: float


def rssi_to_distance(
    rssi: float, ref_power: float, rssi_offset: float, attenuation: float
) -> float:
    """Return the distance in metres from the log-distance path loss model."""
    return float(10 ** ((ref_power + rssi_offset - rssi) / (10 * attenuation)))


def floor_distance(distance: float, scanner_z: float, tracker_height: float) -> float:
    """Project a line-of-sight distance onto the floor, from the height difference."""
    return math.sqrt(max(distance * distance - (scanner_z - tracker_height) ** 2, 0.0))


def median(values: Sequence[float]) -> float:
    """Return the median of the values."""
    return float(statistics.median(values))


def trilaterate(measurements: Sequence[Measurement], plan: Floorplan) -> Point | None:
    """Return the weighted least-squares position, or None without measurements.

    Minimizes sum w_i (|x - p_i| - d_i)^2 with w_i = 1 / d_i^2 by Gauss-Newton:
    near scanners count more. Walls dampen the signal, so measured distances are
    rather too long; a residual that says "nearer than measured" counts a quarter.
    A slight damping keeps two scanners from being singular. The result is kept
    in the plan's extent and, when clamping is on, moved into the closest room.
    """
    if not measurements:
        return None
    weights = [1.0 / max(m.distance, 0.5) ** 2 for m in measurements]
    wsum = sum(weights)
    x = sum(m.x * w for m, w in zip(measurements, weights, strict=True)) / wsum
    y = sum(m.y * w for m, w in zip(measurements, weights, strict=True)) / wsum
    if len(measurements) > 1:
        for _ in range(40):
            a11 = a12 = a22 = b1 = b2 = 0.0
            for m, w in zip(measurements, weights, strict=True):
                dx = x - m.x
                dy = y - m.y
                r = max(math.hypot(dx, dy), 1e-3)
                jx = dx / r
                jy = dy / r
                res = r - m.distance
                wi = w * 0.25 if res < 0 else w
                a11 += wi * jx * jx
                a12 += wi * jx * jy
                a22 += wi * jy * jy
                b1 += wi * jx * res
                b2 += wi * jy * res
            a11 += 1e-3 * wsum
            a22 += 1e-3 * wsum
            det = a11 * a22 - a12 * a12
            if abs(det) < 1e-12:
                break
            sx = (a22 * b1 - a12 * b2) / det
            sy = (a11 * b2 - a12 * b1) / det
            x -= sx
            y -= sy
            if math.hypot(sx, sy) < 1e-3:
                break
    width, height = plan.extent
    x = min(max(x, 0.0), width)
    y = min(max(y, 0.0), height)
    return plan.clamp(x, y)


@dataclass(slots=True)
class _Smoothed:
    x: float
    y: float
    time: float


class Smoother:
    """Time-based smoothing per tracker.

    The shown position approaches the raw position with a time constant
    (smoothing_seconds), independent of how often it is computed. Moves below
    min_move around the shown position are ignored altogether.
    """

    def __init__(self) -> None:
        """Initialize the smoother."""
        self._state: dict[str, _Smoothed] = {}

    def smooth(self, key: str, raw: Point, now: float, plan: Floorplan) -> Point:
        """Return the smoothed position of the tracker for the raw position at now."""
        prev = self._state.get(key)
        if prev is None:
            self._state[key] = _Smoothed(raw[0], raw[1], now)
            return raw
        x, y = prev.x, prev.y
        if math.hypot(raw[0] - prev.x, raw[1] - prev.y) > plan.settings.min_move:
            dt = now - prev.time
            a = 1 - math.exp(-dt / max(plan.settings.smoothing_seconds, 0.1))
            x += a * (raw[0] - prev.x)
            y += a * (raw[1] - prev.y)
        x, y = plan.clamp(x, y)
        self._state[key] = _Smoothed(x, y, now)
        return (x, y)

    def reset(self, key: str) -> None:
        """Forget the tracker, so the next position is taken as is."""
        self._state.pop(key, None)
