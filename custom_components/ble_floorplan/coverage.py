"""Coverage: where the scanners can place a tracker well, and where not.

Two maps on a grid of COVERAGE_CELL metres over the rooms:

The model predicts, for every cell, the RSSI each scanner would receive from
a tracker there, with the path loss model the engine itself uses backwards:
the reference power of the tracker, the offset of the scanner and of the pair,
the exponent, and the line of sight from the scanner's height to the
tracker's. Walls have no term of their own: the exponent and the offsets from
the calibration already hold what a wall in between typically takes. Probe
scanners, placed on the page only, show what a new scanner would change.

The measurement adds up, per tracker, day and cell, what the coordinator saw
there: how many scanners received the tracker well, how well they lay around
it, and how far their circles missed the position. It keeps as many days as
the timeline and is off with it.

Both maps are per level: the floors at one elevation. The model counts the
height of every scanner above the ground and the loss of the ceilings
between; the measurement keeps the level of each sample with its cell.

A cell is good with three scanners or more that receive well (RSSI at least
COVERAGE_GOOD_RSSI) and lie around it, not in a line (HDOP at most
COVERAGE_MAX_HDOP); fair with two; poor with one or none.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import logging
import math
from typing import TYPE_CHECKING, Any

import probatio

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import (
    COVERAGE_CELL,
    COVERAGE_GOOD_RSSI,
    COVERAGE_MAX_HDOP,
    COVERAGE_MIN_SECONDS,
    COVERAGE_PROBE_HEIGHT,
    COVERAGE_SAVE_DELAY_SECONDS,
    COVERAGE_STORAGE_KEY,
    COVERAGE_STORAGE_VERSION,
    COVERAGE_TRACKER_HEIGHT,
)
from .engine import median
from .geometry import Point
from .history import day_of
from .model import NUMBER, Floorplan, Tracker

if TYPE_CHECKING:
    from .coordinator import Positions, TrackerPosition

_LOGGER = logging.getLogger(__name__)

POOR = 0
FAIR = 1
GOOD = 2

# Per cell: [samples, sum of good scanners, sum of levels, sum of RMS misses (m)]
type Stats = list[float]
type Cells = dict[str, Stats]
# day -> tracker -> cell "ix,iy" -> stats
type Days = dict[str, dict[str, Cells]]

STATS = probatio.ExactSequence([NUMBER, NUMBER, NUMBER, NUMBER])
STORE_SCHEMA = probatio.Schema(
    {
        probatio.Required("cell"): NUMBER,
        probatio.Optional("days", default=dict): {str: {str: {str: STATS}}},
        probatio.Optional("basis", default=None): probatio.Any(None, dict),
        probatio.Optional("change", default=None): probatio.Any(
            None,
            {
                probatio.Required("at"): NUMBER,
                probatio.Required("reason"): probatio.In(["scanners", "calibration"]),
                probatio.Required("days"): [str],
            },
        ),
    }
)


def basis(plan: Floorplan) -> dict[str, Any]:
    """Return what the measurement depends on, as stored: the scanner setup and the calibration.

    Where a sample lands, which scanners count for it and how far the circles
    miss follow from both; a change makes the days before it show the old state.
    """
    calibration: dict[str, Any] = {
        "offsets": {s.key: s.rssi_offset for s in plan.scanners},
        "pairs": {k: dict(v) for k, v in plan.pair_offsets.items()},
        "ref_power": {t.key: t.ref_power for t in plan.trackers},
        "ref_power_default": plan.settings.ref_power_default,
        "attenuation": plan.settings.attenuation,
        "max_distance": plan.settings.max_distance,
    }
    if len(plan.levels) > 1:
        # Only a plan of several levels has ceilings to lose signal in
        calibration["floor_loss"] = plan.settings.floor_loss
    return {
        "scanners": {s.key: [s.x, s.y, plan.scanner_height(s), s.paused] for s in plan.scanners},
        "calibration": calibration,
    }


@dataclass(frozen=True, slots=True)
class Probe:
    """A scanner that is only thought of: where a new one would go."""

    x: float
    y: float
    z: float = COVERAGE_PROBE_HEIGHT


def hdop(x: float, y: float, scanners: Sequence[Point]) -> float | None:
    """Return how badly the scanners lie around the point for a position fix.

    The horizontal dilution of precision of range measurements: about 1.2 for
    three scanners spread evenly around the point, growing without bound as
    they line up. None with fewer than two scanners or all on one line.
    """
    a11 = a12 = a22 = 0.0
    for sx, sy in scanners:
        dx, dy = sx - x, sy - y
        r = math.hypot(dx, dy)
        if r < 1e-6:
            continue
        ux, uy = dx / r, dy / r
        a11 += ux * ux
        a12 += ux * uy
        a22 += uy * uy
    det = a11 * a22 - a12 * a12
    if det < 1e-6:
        return None
    return math.sqrt((a11 + a22) / det)


def level(good: int, dop: float | None) -> int:
    """Return the level of a place from its good scanners and how they lie around it."""
    if good >= 3 and dop is not None and dop <= COVERAGE_MAX_HDOP:
        return GOOD
    if good >= 2:
        return FAIR
    return POOR


def cell_of(x: float, y: float) -> tuple[int, int]:
    """Return the grid cell of a point."""
    return (math.floor(x / COVERAGE_CELL), math.floor(y / COVERAGE_CELL))


def cell_key(ix: int, iy: int, level: float = 0.0) -> str:
    """Return the key of a cell in storage: with its level unless that is 0."""
    return f"{ix},{iy}/{level}" if level else f"{ix},{iy}"


def parse_cell(key: str) -> tuple[int, int, float]:
    """Return the cell and the level of a key in storage."""
    cell, _, level = key.partition("/")
    ix, iy = (int(v) for v in cell.split(","))
    return ix, iy, float(level) if level else 0.0


def _center(extent: tuple[float, float], ix: int, iy: int) -> Point:
    """Return the centre of the part of the cell inside the plan.

    A cell on the plan's far edge reaches past the outer wall; its plain centre
    may lie outside every room although the room fills the cell up to the wall.
    """
    width, height = extent
    x0, y0 = ix * COVERAGE_CELL, iy * COVERAGE_CELL
    return (
        (x0 + min(x0 + COVERAGE_CELL, width)) / 2,
        (y0 + min(y0 + COVERAGE_CELL, height)) / 2,
    )


def grid(plan: Floorplan) -> list[tuple[int, int]]:
    """Return the cells whose centre lies in a room, zone or outdoor area that is tracked."""
    extent = plan.extent
    width, height = extent
    cells = []
    for iy in range(math.ceil(height / COVERAGE_CELL)):
        for ix in range(math.ceil(width / COVERAGE_CELL)):
            cx, cy = _center(extent, ix, iy)
            if (room := plan.room_of(cx, cy)) is not None and room.tracked:
                cells.append((ix, iy))
    return cells


def _predicted_rssi(
    ref_power: float, offset: float, attenuation: float, floor: float, dz: float
) -> float:
    """Return the RSSI the path loss model expects at a floor distance and height difference."""
    distance = max(math.hypot(floor, dz), 0.1)
    return ref_power + offset - 10 * attenuation * math.log10(distance)


@dataclass(frozen=True, slots=True)
class _Source:
    x: float
    y: float
    z: float
    offset: float


def _sources(plan: Floorplan, tracker: Tracker | None, level: float) -> list[_Source]:
    """Return the scanners as heard from the level: height above ground, offsets, ceilings lost."""
    loss = plan.settings.floor_loss
    return [
        _Source(
            s.x,
            s.y,
            plan.scanner_height(s),
            s.rssi_offset
            + (plan.pair_offset(s.key, tracker.key) if tracker else 0.0)
            - loss * plan.ceilings(s, level),
        )
        for s in plan.scanners
        if not s.paused
    ]


def probe_offset(plan: Floorplan) -> float:
    """Return the offset a probe scanner gets: the median of the plan's scanners, 0 without any."""
    return median([s.rssi_offset for s in plan.scanners]) if plan.scanners else 0.0


def _model_cell(
    x: float, y: float, sources: Iterable[_Source], ref_power: float, height: float, n: float
) -> tuple[int, int, float | None]:
    good = [
        (s.x, s.y)
        for s in sources
        if _predicted_rssi(ref_power, s.offset, n, math.hypot(s.x - x, s.y - y), s.z - height)
        >= COVERAGE_GOOD_RSSI
    ]
    dop = hdop(x, y, good)
    return level(len(good), dop), len(good), dop


def _error(
    x: float, y: float, sources: Iterable[_Source], ref_power: float, height: float, n: float
) -> float:
    """Return how far off a position at the point is expected to be, in units that cancel when compared.

    The distance read from an RSSI scatters in proportion to the distance, so
    each good scanner pins the point along its direction with a weight of
    1/r². The error is sqrt(trace(J⁻¹)) of J = Σ u·uᵀ/r²: a near scanner
    helps much, a far one little, scanners on one line hardly across it.
    Infinite with fewer than three good scanners.
    """
    a11 = a12 = a22 = 0.0
    good = 0
    for s in sources:
        floor = math.hypot(s.x - x, s.y - y)
        if _predicted_rssi(ref_power, s.offset, n, floor, s.z - height) < COVERAGE_GOOD_RSSI:
            continue
        good += 1
        if floor < 1e-6:
            continue
        # Right under a scanner it still counts as half a metre away
        r = max(math.hypot(floor, s.z - height), 0.5)
        ux, uy = (s.x - x) / floor, (s.y - y) / floor
        w = 1 / (r * r)
        a11 += w * ux * ux
        a12 += w * ux * uy
        a22 += w * uy * uy
    det = a11 * a22 - a12 * a12
    if good < 3 or det < 1e-9:
        return math.inf
    return math.sqrt((a11 + a22) / det)


def precision(plan: Floorplan, elevation: float) -> dict[tuple[int, int], tuple[int, float]]:
    """Return per tracked cell of the level its level and its expected error, for a tracker of the default values."""
    ref_power = plan.settings.ref_power_default
    height = elevation + COVERAGE_TRACKER_HEIGHT
    n = plan.settings.attenuation
    sources = _sources(plan, None, elevation)
    on_level = plan.on_level(elevation)
    result = {}
    for ix, iy in grid(on_level):
        x, y = _center(on_level.extent, ix, iy)
        lvl = _model_cell(x, y, sources, ref_power, height, n)[0]
        result[(ix, iy)] = (lvl, _error(x, y, sources, ref_power, height, n))
    return result


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def model(
    plan: Floorplan,
    tracker: Tracker | None = None,
    probes: Sequence[Probe] = (),
    elevation: float | None = None,
) -> dict[str, Any]:
    """Return the predicted coverage for the tracker, or for a tracker of the default values.

    On the level at the elevation, the lowest without one; probes stand on
    it. Every cell is [ix, iy, level, good scanners, HDOP]; with probes, also
    the level without them, so the page can show what they change.
    """
    at = plan.levels[0] if elevation is None else elevation
    ref_power = plan.ref_power(tracker) if tracker else plan.settings.ref_power_default
    height = at + (tracker.height if tracker else COVERAGE_TRACKER_HEIGHT)
    n = plan.settings.attenuation
    sources = _sources(plan, tracker, at)
    offset = probe_offset(plan)
    extra = [_Source(p.x, p.y, at + p.z, offset) for p in probes]
    cells: list[list[Any]] = []
    rooms: dict[str, list[int]] = {}
    plan = plan.on_level(at)
    for ix, iy in grid(plan):
        x, y = _center(plan.extent, ix, iy)
        lvl, good, dop = _model_cell(x, y, [*sources, *extra], ref_power, height, n)
        cell: list[Any] = [ix, iy, lvl, good, _round(dop)]
        if probes:
            cell.append(_model_cell(x, y, sources, ref_power, height, n)[0])
        cells.append(cell)
        if name := plan.room_at(x, y):
            rooms.setdefault(name, [0, 0, 0])[lvl] += 1
    return {
        "cell": COVERAGE_CELL,
        "good_rssi": COVERAGE_GOOD_RSSI,
        "max_hdop": COVERAGE_MAX_HDOP,
        "probe_offset": round(offset, 1),
        "cells": cells,
        "rooms": [{"name": name, "cells": counts} for name, counts in rooms.items()],
    }


def sample(plan: Floorplan, position: TrackerPosition) -> tuple[str, Stats] | None:
    """Return the cell and the stats of one position as the coordinator computed it.

    None while the tracker is not seen or stands in a room that is not tracked. Good scanners are those that went into
    the position with an RSSI of at least COVERAGE_GOOD_RSSI; the miss is the
    RMS of how far each used scanner's circle passes the raw position.
    """
    if position.x is None or position.y is None:
        return None
    on_level = plan.on_level(plan.levels[0] if position.level is None else position.level)
    if (room := on_level.room_of(position.x, position.y)) is not None and not room.tracked:
        # A room left out of the tracking is left out of the measurement too
        return None
    assert position.raw_x is not None and position.raw_y is not None
    good: list[Point] = []
    misses: list[float] = []
    for scanner in plan.scanners:
        reading = position.readings.get(scanner.key)
        if reading is None or not reading.used:
            continue
        assert reading.rssi is not None and reading.distance is not None
        misses.append(
            math.hypot(position.raw_x - scanner.x, position.raw_y - scanner.y) - reading.distance
        )
        if reading.rssi >= COVERAGE_GOOD_RSSI:
            good.append((scanner.x, scanner.y))
    rms = math.sqrt(sum(m * m for m in misses) / len(misses)) if misses else 0.0
    lvl = level(len(good), hdop(position.x, position.y, good))
    key = cell_key(*cell_of(position.x, position.y), position.level or 0.0)
    return key, [1, len(good), lvl, rms]


class CoverageStore:
    """What the scanners saw where, per tracker and day; today's in memory and written delayed."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store: Store[dict[str, Any]] = Store(
            hass, COVERAGE_STORAGE_VERSION, COVERAGE_STORAGE_KEY
        )
        self.days: Days = {}
        # What the days were measured with, and the last change of it:
        # {at (unix time), reason, days that held samples then}
        self._basis: dict[str, Any] | None = None
        self._change: dict[str, Any] | None = None
        # The plan the basis was last compared for; a saved plan is a new object
        self._plan: Floorplan | None = None
        self._save_pending = False
        # Set when Home Assistant stops or the entry unloads: nothing more is recorded
        self._closed = False

    async def async_load(self, now: float, keep_days: int) -> None:
        """Load the days and drop what is older than keep_days.

        A store that cannot be read, or one of another cell size, starts anew
        with a warning: it is only a measurement, and the next days bring it back.
        """
        if (data := await self._store.async_load()) is not None:
            try:
                valid = STORE_SCHEMA(data)
            except probatio.Invalid as err:
                _LOGGER.warning("The coverage cannot be read and starts anew: %s", err)
            else:
                if valid["cell"] == COVERAGE_CELL:
                    self.days = valid["days"]
                    self._basis = valid["basis"]
                    self._change = valid["change"]
        await self.async_prune(now, keep_days)

    def _data(self) -> dict[str, Any]:
        return {
            "cell": COVERAGE_CELL,
            "days": self.days,
            "basis": self._basis,
            "change": self._change,
        }

    @callback
    def _compare(self, plan: Floorplan, now: float) -> None:
        """Note when the scanner setup or the calibration changed while days were measured."""
        self._plan = plan
        now_basis = basis(plan)
        if now_basis == self._basis:
            return
        before, self._basis = self._basis, now_basis
        self._schedule_save()
        if before is None or not self.days:
            return
        reason = "scanners" if now_basis["scanners"] != before["scanners"] else "calibration"
        stale = set(self._change["days"]) if self._change is not None else set()
        self._change = {"at": now, "reason": reason, "days": sorted(stale | set(self.days))}

    def _delayed_data(self) -> dict[str, Any]:
        self._save_pending = False
        return self._data()

    @callback
    def _schedule_save(self) -> None:
        """Write a while after the first new sample, once per interval, as the timeline does."""
        if not self._save_pending:
            self._save_pending = True
            self._store.async_delay_save(self._delayed_data, COVERAGE_SAVE_DELAY_SECONDS)

    async def async_prune(self, now: float, keep_days: int) -> None:
        """Remove the days that ended more than keep_days ago; 0 removes every day."""
        cutoff = day_of(now - keep_days * 86400) if keep_days else None
        gone = [d for d in self.days if cutoff is None or d < cutoff]
        if not gone:
            return
        for day in gone:
            del self.days[day]
        await self._store.async_save(self._data())

    @callback
    def record(self, plan: Floorplan, positions: Positions, now: float, keep_days: int) -> None:
        """Add a sample for every tracker the positions see, to today's cells."""
        if self._closed or not keep_days:
            return
        if plan is not self._plan:
            self._compare(plan, now)
        today: dict[str, Cells] | None = None
        for key, position in positions.items():
            if (got := sample(plan, position)) is None:
                continue
            if today is None:
                today = self.days.setdefault(day_of(now), {})
            cell, stats = got
            have = today.setdefault(key, {}).setdefault(cell, [0, 0, 0, 0.0])
            for i, value in enumerate(stats):
                have[i] += value
        if today is not None:
            self._schedule_save()

    def measured(
        self, plan: Floorplan, tracker: str | None = None, elevation: float | None = None
    ) -> dict[str, Any]:
        """Return the measured coverage of one tracker or all of them, over every day kept.

        On the level at the elevation, the lowest without one. Every cell is
        [ix, iy, level, mean good scanners, mean miss (m), seconds]; its level
        is the mean of its samples' levels, rounded. A cell needs
        COVERAGE_MIN_SECONDS of samples to count.
        """
        at = plan.levels[0] if elevation is None else elevation
        plan = plan.on_level(at)
        total: dict[str, Stats] = {}
        for trackers in self.days.values():
            for key, cells in trackers.items():
                if tracker is not None and key != tracker:
                    continue
                for cell, stats in cells.items():
                    have = total.setdefault(cell, [0, 0, 0, 0.0])
                    for i, value in enumerate(stats):
                        have[i] += value
        cells_out: list[list[Any]] = []
        rooms: dict[str, list[float]] = {}
        extent = plan.extent
        for cell, (n, good, lvl, miss) in sorted(total.items()):
            ix, iy, on = parse_cell(cell)
            if n < COVERAGE_MIN_SECONDS or on != at:
                continue
            mean = lvl / n
            shown = GOOD if mean >= 1.5 else FAIR if mean >= 0.5 else POOR
            cells_out.append([ix, iy, shown, round(good / n, 1), round(miss / n, 2), int(n)])
            if name := plan.room_at(*_center(extent, ix, iy)):
                room = rooms.setdefault(name, [0, 0, 0])
                room[0] += n
                room[1] += lvl
                room[2] += good
        return {
            "cell": COVERAGE_CELL,
            "good_rssi": COVERAGE_GOOD_RSSI,
            "max_hdop": COVERAGE_MAX_HDOP,
            "days": sorted(self.days),
            "change": self._change_now(),
            "cells": cells_out,
            "rooms": [
                {
                    "name": name,
                    "level": round(lvl / n, 2),
                    "good": round(good / n, 1),
                    "seconds": int(n),
                }
                for name, (n, lvl, good) in rooms.items()
            ],
        }

    def _change_now(self) -> dict[str, Any] | None:
        """Return the last change with the days from before it that are still kept; None without."""
        if self._change is None:
            return None
        days = [d for d in self._change["days"] if d in self.days]
        return {**self._change, "days": days} if days else None

    async def async_reset(self) -> None:
        """Forget every day, after a scanner moved or came in: the old samples no longer hold."""
        self.days = {}
        self._change = None
        await self._store.async_save(self._data())

    @callback
    def close(self) -> None:
        """Stop recording; the delayed write Home Assistant does before it stops carries the rest."""
        self._closed = True

    async def async_close(self) -> None:
        """Stop recording and write at once, for an unload of the entry."""
        self.close()
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Remove the stored coverage, with the entry."""
        await self._store.async_remove()


def parse_probes(raw: Iterable[Mapping[str, Any]]) -> list[Probe]:
    """Return the probes of a validated WebSocket message."""
    return [Probe(p["x"], p["y"], p.get("z", COVERAGE_PROBE_HEIGHT)) for p in raw]
