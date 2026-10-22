"""The position engine: RSSI to distance, weighted trilateration, smoothing, rooms.

The trilateration and the time-based smoothing are ports of the card's
JavaScript; with the robust weights, the jump rule, the speed limit and the
room hysteresis off, the tests check them against its numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
import statistics

from .geometry import Point, closest_on_outline
from .model import Floorplan

# At most this many scanners lose weight for contradicting the others
ROBUST_PASSES = 2
# Robust weights need this many scanners: three leave no way to tell which one is wrong
ROBUST_MIN_SCANNERS = 4


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


def _gauss_newton(
    measurements: Sequence[Measurement], weights: Sequence[float], x: float, y: float
) -> Point:
    """Minimize sum w_i (|p - p_i| - d_i)^2 from the start point x, y.

    Walls dampen the signal, so measured distances are rather too long; a
    residual that says "nearer than measured" counts a quarter. A slight
    damping keeps two scanners from being singular.
    """
    wsum = sum(weights)
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
    return (x, y)


def _solve(measurements: Sequence[Measurement], weights: Sequence[float]) -> Point:
    """Return the weighted least-squares position, starting from the weighted centroid."""
    wsum = sum(weights)
    x = sum(m.x * w for m, w in zip(measurements, weights, strict=True)) / wsum
    y = sum(m.y * w for m, w in zip(measurements, weights, strict=True)) / wsum
    if len(measurements) > 1:
        x, y = _gauss_newton(measurements, weights, x, y)
    return (x, y)


def _residual(point: Point, m: Measurement) -> float:
    return abs(math.hypot(point[0] - m.x, point[1] - m.y) - m.distance)


def _rms(point: Point, measurements: Sequence[Measurement]) -> float:
    return math.sqrt(sum(_residual(point, m) ** 2 for m in measurements) / len(measurements))


def _robust_weights(
    measurements: Sequence[Measurement], weights: list[float], k: float
) -> list[float]:
    """Lower the weight of a scanner the others contradict.

    Each scanner in turn is left out and the others solved alone. The scanner
    whose circle misses the others' solution by more than k, while the others
    agree with each other at least twice as well, loses weight in proportion.
    With fewer than four scanners the others cannot agree or disagree, so
    nothing changes.
    """
    for _ in range(ROBUST_PASSES):
        worst: tuple[float, int] | None = None
        for i, m in enumerate(measurements):
            others = [o for j, o in enumerate(measurements) if j != i]
            other_weights = [w for j, w in enumerate(weights) if j != i]
            point = _solve(others, other_weights)
            miss = _residual(point, m)
            if miss > k and miss > 2 * _rms(point, others) and (worst is None or miss > worst[0]):
                worst = (miss, i)
        if worst is None:
            break
        miss, i = worst
        weights = [w * (k / miss) ** 2 if j == i else w for j, w in enumerate(weights)]
    return weights


def trilaterate(measurements: Sequence[Measurement], plan: Floorplan) -> Point | None:
    """Return the weighted least-squares position, or None without measurements.

    Weights are 1 / d^2: near scanners count more. With robust_residual set and
    four or more scanners, a scanner whose circle the others contradict loses
    weight, so one scanner that swings cannot drag the position. The result is
    kept in the plan's extent and, when clamping is on, moved into the closest
    room.
    """
    if not measurements:
        return None
    weights = [1.0 / max(m.distance, 0.5) ** 2 for m in measurements]
    k = plan.settings.robust_residual
    if k > 0 and len(measurements) >= ROBUST_MIN_SCANNERS:
        weights = _robust_weights(measurements, weights, k)
    x, y = _solve(measurements, weights)
    width, height = plan.extent
    x = min(max(x, 0.0), width)
    y = min(max(y, 0.0), height)
    return plan.clamp(x, y)


@dataclass(slots=True)
class _Smoothed:
    x: float
    y: float
    time: float
    # A raw position far from the shown one, waiting to be confirmed
    candidate: Point | None = None
    since: float = 0.0


class Smoother:
    """Time-based smoothing per tracker, with a jump rule and a speed limit.

    The shown position approaches the raw position with a time constant
    (smoothing_seconds), independent of how often it is computed. Moves below
    min_move around the shown position are ignored altogether. A raw position
    farther than jump_distance away is followed only once it stayed there for
    jump_confirm_seconds; meanwhile the shown position holds. Once followed,
    the step is as large as if the raw position had been followed all along,
    but never faster than max_speed.
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
        settings = plan.settings
        x, y = prev.x, prev.y
        move = math.hypot(raw[0] - prev.x, raw[1] - prev.y)
        if settings.jump_distance > 0 and move > settings.jump_distance:
            if (
                prev.candidate is None
                or math.hypot(raw[0] - prev.candidate[0], raw[1] - prev.candidate[1])
                > settings.jump_distance
            ):
                prev.candidate = raw
                prev.since = now
            if now - prev.since < settings.jump_confirm_seconds:
                return (x, y)
        prev.candidate = None
        if move > settings.min_move:
            dt = now - prev.time
            a = 1 - math.exp(-dt / max(settings.smoothing_seconds, 0.1))
            sx = a * (raw[0] - prev.x)
            sy = a * (raw[1] - prev.y)
            limit = settings.max_speed * dt
            if settings.max_speed > 0 and math.hypot(sx, sy) > limit:
                scale = limit / math.hypot(sx, sy)
                sx *= scale
                sy *= scale
            x += sx
            y += sy
        x, y = plan.clamp(x, y)
        prev.x, prev.y, prev.time = x, y, now
        return (x, y)

    def reset(self, key: str) -> None:
        """Forget the tracker, so the next position is taken as is."""
        self._state.pop(key, None)


@dataclass(slots=True)
class _RoomState:
    room: str | None
    # Whether another room (or none) is waiting to be confirmed, and which
    pending: bool = False
    candidate: str | None = None
    since: float = 0.0


class RoomTracker:
    """The room per tracker, with hysteresis.

    The first room is taken as is. Afterwards the room changes only when the
    position lay in another room for room_hold_seconds, and at least
    room_margin away from that room's walls the whole time: a position that
    hovers around a wall stays in the room it came from.
    """

    def __init__(self) -> None:
        """Initialize the tracker."""
        self._state: dict[str, _RoomState] = {}

    def room(self, key: str, x: float, y: float, now: float, plan: Floorplan) -> str | None:
        """Return the room of the tracker for the position at now."""
        room = plan.room_of(x, y)
        name = room.name if room is not None else None
        state = self._state.get(key)
        if state is None:
            self._state[key] = _RoomState(name)
            return name
        settings = plan.settings
        deep = room is None or closest_on_outline(room.corners, x, y)[1] >= settings.room_margin
        if name == state.room or not deep:
            state.pending = False
            return state.room
        if not state.pending or state.candidate != name:
            state.pending = True
            state.candidate = name
            state.since = now
        if now - state.since >= settings.room_hold_seconds:
            state.room = name
            state.pending = False
        return state.room

    def reset(self, key: str) -> None:
        """Forget the tracker, so the next room is taken as is."""
        self._state.pop(key, None)
