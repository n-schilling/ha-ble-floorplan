"""The coordinator: reads the scanners' advertisements and places the trackers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from datetime import timedelta
import logging
import math
from typing import Any

from homeassistant.components.bluetooth import MONOTONIC_TIME, async_scanner_devices_by_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .calibration import CalibrationRun, CalibrationStore
from .const import (
    DOMAIN,
    RSSI_SCATTER_DB,
    RSSI_WINDOW_SECONDS,
    STALE_SECONDS,
    UPDATE_INTERVAL_SECONDS,
)
from .coverage import CoverageStore
from .engine import (
    Heard,
    LevelTracker,
    Measurement,
    RoomTracker,
    Smoother,
    floor_distance,
    floor_range,
    median,
    misfit,
    rssi_to_distance,
    trilaterate,
)
from .geometry import Point
from .history import HistoryStore
from .model import Floorplan, Tracker, with_calibration
from .quality import Heard as QualityHeard, QualityTracker
from .solver import CalibrationError, fit_tracker
from .store import FloorplanStore

_LOGGER = logging.getLogger(__name__)

PRIVATE_BLE_DEVICE = "private_ble_device"
ATTR_CURRENT_ADDRESS = "current_address"


@dataclass(frozen=True, slots=True)
class Reading:
    """What one scanner contributes to a tracker."""

    # Median RSSI of the window in dBm, None when the scanner does not see the tracker
    rssi: float | None
    # Distance on the floor in metres, None when not seen
    distance: float | None
    # Whether it went into the trilateration (seen and within max_distance)
    used: bool
    # How much the tracker's height leaves the distance open, as weighed (m)
    spread: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """Return the reading for the card."""
        return {"rssi": self.rssi, "distance": self.distance, "used": self.used}


@dataclass(frozen=True, slots=True)
class TrackerPosition:
    """The computed position of a tracker."""

    key: str
    # The address the readings were taken for, None when a Private BLE Device has none
    address: str | None
    # Smoothed position in metres, None when no scanner sees the tracker
    x: float | None
    y: float | None
    # Position before smoothing
    raw_x: float | None
    raw_y: float | None
    room: str | None
    # Scanner key of the shortest distance
    nearest: str | None
    # Number of scanners that went into the position
    scanner_count: int
    readings: dict[str, Reading] = field(default_factory=dict)
    # Whether a scanner saw the tracker within away_seconds; None right after
    # the start, before away_seconds passed without seeing it
    present: bool | None = None
    # The floor of its room (None outside the rooms) and the elevation of its level
    floor: str | None = None
    level: float | None = None

    @property
    def seen(self) -> bool:
        """Return whether a scanner sees the tracker."""
        return self.x is not None

    def as_dict(self) -> dict[str, Any]:
        """Return the position for the card."""
        return {
            "key": self.key,
            "x": self.x,
            "y": self.y,
            "raw_x": self.raw_x,
            "raw_y": self.raw_y,
            "room": self.room,
            "nearest": self.nearest,
            "scanner_count": self.scanner_count,
            "readings": {key: r.as_dict() for key, r in self.readings.items()},
            "present": self.present,
            "floor": self.floor,
            "level": self.level,
        }


type Positions = dict[str, TrackerPosition]
type Sample = tuple[float, float]  # (monotonic time, rssi)


class FloorplanCoordinator(DataUpdateCoordinator[Positions]):
    """Computes the positions of all trackers once a second."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: FloorplanStore,
        calibration: CalibrationStore,
        history: HistoryStore,
        coverage: CoverageStore,
        quality: QualityTracker | None = None,
    ) -> None:
        """Initialize the coordinator; without a quality tracker it keeps one in memory."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
            always_update=False,
        )
        self.store = store
        self.calibration = calibration
        self.history = history
        self.coverage = coverage
        self._samples: dict[tuple[str, str], deque[Sample]] = {}
        self._smoother = Smoother()
        # The last measured position per tracker: where the walls are counted from
        self._last_raw: dict[str, Point] = {}
        self._rooms = RoomTracker()
        self._levels = LevelTracker()
        # How good each scanner is: reception and fidelity
        self.quality = quality or QualityTracker()
        # Monotonic time of the first computation and of the last sighting per tracker
        self._started: float | None = None
        self._last_seen: dict[str, float] = {}
        # The room, floor and level of the last sighting per tracker, kept until it counts as away
        self._last_place: dict[str, tuple[str | None, str | None, float | None]] = {}
        # device_id -> entity_id of the device tracker of a Private BLE Device
        self._tracker_entities: dict[str, str] = {}

    @property
    def plan(self) -> Floorplan:
        """Return the current floor plan."""
        return self.store.plan

    async def _async_update_data(self) -> Positions:
        """Compute the positions and add them to the timeline and the coverage."""
        monotonic = MONOTONIC_TIME()
        self.quality.begin(dt_util.utcnow().timestamp(), self.plan.settings.quality_hours)
        self.quality.setup(self.plan)
        positions = self.compute(monotonic)
        if self.calibration.tick(monotonic):
            await self.async_stop_calibration(auto=True)
        now = dt_util.utcnow().timestamp()
        days = self.plan.settings.history_days
        await self.history.async_record(positions, now, days)
        self.coverage.record(self.plan, positions, now, days)
        return positions

    def compute(self, now: float) -> Positions:
        """Compute the position of every tracker at the monotonic time now."""
        plan = self.plan
        if self._started is None:
            self._started = now
        sources = {s.source: s.key for s in plan.scanners if not s.paused}
        positions: Positions = {}
        for tracker in plan.trackers:
            if tracker.paused:
                # Starts afresh when resumed: no smoothing, room or sighting carried over
                self._forget(tracker.key)
                self._last_seen.pop(tracker.key, None)
                self._last_place.pop(tracker.key, None)
                positions[tracker.key] = TrackerPosition(
                    tracker.key, None, None, None, None, None, None, None, 0
                )
                continue
            address = self._address_of(tracker)
            if address is not None:
                self._collect(tracker.key, address, sources)
            position = self._locate(tracker, address, now, plan)
            if position.seen:
                self._last_seen[tracker.key] = now
                self._last_place[tracker.key] = (position.room, position.floor, position.level)
            last = self._last_seen.get(tracker.key)
            away = plan.settings.away_seconds
            if last is not None:
                present: bool | None = now - last <= away
            else:
                present = None if now - self._started < away else False
            if not position.seen:
                # A short gap keeps the last room: unknown only once the tracker counts as away
                room, floor, level = self._last_place.get(tracker.key, (None, None, None))
                if not present:
                    room = floor = level = None
                    self._last_place.pop(tracker.key, None)
                position = replace(position, room=room, floor=floor, level=level)
            positions[tracker.key] = replace(position, present=present)
        return positions

    def _forget(self, key: str) -> None:
        """Start the tracker afresh: no smoothing, room or level carried over."""
        self._last_raw.pop(key, None)
        self._smoother.reset(key)
        self._rooms.reset(key)
        self._levels.reset(key)

    async def async_start_calibration(
        self,
        tracker_key: str,
        x: float,
        y: float,
        height: float,
        auto_stop: bool = False,
        floor: str = "",
    ) -> CalibrationRun:
        """Start recording the tracker's advertisements at its true position, on the floor."""
        plan = self.plan
        scanners = {s.key: (s.x, s.y, plan.scanner_height(s)) for s in plan.scanners}
        return await self.calibration.async_start(
            tracker_key, x, y, height, MONOTONIC_TIME(), scanners, auto_stop, floor
        )

    async def async_stop_calibration(
        self, auto: bool = False
    ) -> tuple[CalibrationRun, dict[str, Any] | None]:
        """Stop the recording and save the tracker's values from its runs, as fit_tracker does.

        auto tells that the run ended by itself; the page shows what was saved either way.
        """
        run = await self.calibration.async_stop(MONOTONIC_TIME(), notify=False)
        fit = await self.async_fit_tracker(run.tracker)
        self.calibration.note_stopped(run, fit, auto)
        return run, fit

    async def async_fit_tracker(self, tracker_key: str) -> dict[str, Any] | None:
        """Save the tracker's reference power and pair corrections from all of its runs.

        Returns the fit (old and new values), None when the runs give nothing,
        for a tracker without a usable run or no longer on the plan.
        """
        plan = self.plan
        try:
            fit = fit_tracker(plan, self.calibration.finished, tracker_key)
        except CalibrationError:
            return None
        pairs = {scanner: {tracker_key: value["new"]} for scanner, value in fit["pairs"].items()}
        await self.store.async_save(
            with_calibration(plan, None, {tracker_key: fit["ref_power"]["new"]}, {}, pairs)
        )
        return fit

    def _address_of(self, tracker: Tracker) -> str | None:
        """Return the address to look for: fixed, or the current one of the Private BLE Device."""
        if tracker.address is not None:
            return tracker.address
        assert tracker.device_id is not None
        entity_id = self._tracker_entities.get(tracker.device_id)
        state = self.hass.states.get(entity_id) if entity_id is not None else None
        if state is None:
            # Not looked up yet, or renamed or created anew since: ask the registry
            if (entity_id := self._tracker_entity(tracker.device_id)) is None:
                return None
            state = self.hass.states.get(entity_id)
        if state is None or (address := state.attributes.get(ATTR_CURRENT_ADDRESS)) is None:
            return None
        return str(address).upper()

    def _tracker_entity(self, device_id: str) -> str | None:
        """Look up and remember the device tracker of a Private BLE Device."""
        registry = er.async_get(self.hass)
        for entry in er.async_entries_for_device(registry, device_id, True):
            if entry.domain == "device_tracker" and entry.platform == PRIVATE_BLE_DEVICE:
                self._tracker_entities[device_id] = entry.entity_id
                return entry.entity_id
        self._tracker_entities.pop(device_id, None)
        return None

    def _collect(self, key: str, address: str, sources: dict[str, str]) -> None:
        """Take the newest advertisement of every scanner that sees the address.

        A device without a timestamp is skipped: the scanner only remembers it.
        A local adapter keeps a bonded device in its cache with the last RSSI
        long after the advertisement expired, and only the timestamp is gone.

        A new advertisement also goes into the calibration run of the tracker,
        when one is going and the scanner is in the plan.
        """
        run = self.calibration.active
        for device in async_scanner_devices_by_address(self.hass, address, connectable=False):
            scanner = device.scanner
            stamp = scanner.discovered_device_timestamps.get(address)
            if stamp is None:
                continue
            samples = self._samples.setdefault((key, scanner.source), deque())
            if samples and stamp <= samples[-1][0]:
                continue
            sample = (stamp, device.advertisement.rssi)
            samples.append(sample)
            # Keep only the window, for every scanner: also one that is
            # paused or not in the plan, whose samples _locate never reads
            while samples[0][0] < stamp - RSSI_WINDOW_SECONDS:
                samples.popleft()
            if scanner.source in sources:
                self.quality.count(key, sources[scanner.source])
            if run is not None and run.tracker == key and scanner.source in sources:
                self.calibration.add_sample(sources[scanner.source], sample[0], sample[1])

    def _locate(
        self, tracker: Tracker, address: str | None, now: float, plan: Floorplan
    ) -> TrackerPosition:
        """Turn the collected samples of a tracker into a position.

        Each scanner's signal gives a line-of-sight distance. On a plan of one
        level, a scanner counts when the distance on the floor is within
        max_distance. With more levels, the scanners within max_distance in
        a straight line count; the position is solved for every level, and
        the level that fits them best, with hysteresis, is taken.
        """
        settings = plan.settings
        heard: dict[str, float] = {}
        silent: dict[str, Reading] = {}
        for scanner in plan.scanners:
            if scanner.paused:
                silent[scanner.key] = Reading(None, None, False)
                continue
            # _collect keeps only the window of the newest sample
            samples = self._samples.get((tracker.key, scanner.source))
            if not samples or samples[-1][0] < now - STALE_SECONDS:
                silent[scanner.key] = Reading(None, None, False)
                continue
            heard[scanner.key] = median([s[1] for s in samples])
        # Walls are counted from where it was last measured; the first time, none
        at = self._last_raw.get(tracker.key) if settings.wall_loss > 0 else None
        levels = plan.levels
        if len(levels) == 1:
            level = levels[0]
        else:
            fits: dict[float, float] = {}
            for candidate in levels:
                lines = self._lines(plan, tracker, heard, candidate, at)
                hearing = [
                    Heard(s.x, s.y, plan.scanner_height(s), line)
                    for key, line in lines.items()
                    if (s := plan.scanner(key)) is not None and line <= settings.max_distance
                ]
                point = trilaterate(
                    self._measurements(plan, tracker, heard, candidate, at, strict=False)[0],
                    plan.on_level(candidate),
                    plan.extent,
                )
                if point is not None and hearing:
                    fits[candidate] = misfit(point, hearing, candidate + tracker.height)
            # Nothing heard: no position on any level, the first one stands in
            level = self._pick_level(tracker.key, fits, now, plan) if fits else levels[0]
        level_plan = plan.on_level(level)
        measurements, readings, nearest = self._measurements(
            plan, tracker, heard, level, at, strict=len(levels) == 1
        )
        readings |= silent
        readings = {s.key: readings[s.key] for s in plan.scanners}
        raw = trilaterate(measurements, level_plan, plan.extent)
        if raw is None:
            self._forget(tracker.key)
            return TrackerPosition(
                tracker.key, address, None, None, None, None, None, None, 0, readings
            )
        self._last_raw[tracker.key] = raw
        self.quality.misses(
            [
                QualityHeard(key, s.x, s.y, r.distance, r.spread)
                for key, r in readings.items()
                if r.used and r.distance is not None and (s := plan.scanner(key)) is not None
            ],
            raw,
        )
        x, y = self._smoother.smooth(tracker.key, raw, now, level_plan)
        room = self._rooms.room(tracker.key, x, y, now, level_plan)
        floor = next((r.floor for r in level_plan.rooms if r.name == room), None)
        return TrackerPosition(
            tracker.key,
            address,
            x,
            y,
            raw[0],
            raw[1],
            room,
            nearest,
            len(measurements),
            readings,
            floor=floor,
            level=level,
        )

    @staticmethod
    def _lines(
        plan: Floorplan,
        tracker: Tracker,
        heard: dict[str, float],
        level: float,
        at: Point | None = None,
    ) -> dict[str, float]:
        """Return per scanner the line-of-sight distance, were the tracker on the level.

        Each ceiling between the scanner's level and that one weakened the
        signal by floor_loss, each wall between the scanner and at (where the
        tracker was last measured) by wall_loss; that much is added back
        before the distance.
        """
        settings = plan.settings
        level_plan = plan.on_level(level)
        ref_power = plan.ref_power(tracker)
        lines: dict[str, float] = {}
        for key, rssi in heard.items():
            scanner = plan.scanner(key)
            assert scanner is not None
            offset = scanner.rssi_offset + plan.pair_offset(key, tracker.key)
            loss = settings.floor_loss * plan.ceilings(scanner, level)
            if at is not None:
                loss += settings.wall_loss * level_plan.walls_between((scanner.x, scanner.y), at)
            lines[key] = rssi_to_distance(rssi + loss, ref_power, offset, settings.attenuation)
        return lines

    def _pick_level(self, key: str, fits: dict[float, float], now: float, plan: Floorplan) -> float:
        """Return the tracker's level; a change of level starts its position afresh."""
        shown = self._smoother.position(key)
        previous = self._levels.current(key)
        level = self._levels.level(key, fits, now, plan, shown)
        if previous is not None and level != previous:
            self._smoother.reset(key)
            self._rooms.reset(key)
        return level

    def _measurements(
        self,
        plan: Floorplan,
        tracker: Tracker,
        heard: dict[str, float],
        level: float,
        at: Point | None,
        strict: bool,
    ) -> tuple[list[Measurement], dict[str, Reading], str | None]:
        """Return the measurements on the level, the readings and the nearest scanner.

        strict compares the distance on the floor with max_distance, else the
        distance in a straight line.
        """
        settings = plan.settings
        measurements: list[Measurement] = []
        readings: dict[str, Reading] = {}
        nearest: str | None = None
        nearest_distance = float("inf")
        heights = plan.height_range(tracker)
        # Metres of distance the RSSI leaves open per metre: what the height's share is weighed against
        scatter = RSSI_SCATTER_DB * math.log(10) / (10 * settings.attenuation)
        for key, line in self._lines(plan, tracker, heard, level, at).items():
            scanner = plan.scanner(key)
            assert scanner is not None
            spread = 0.0
            if heights is None:
                distance = floor_distance(
                    line, plan.scanner_height(scanner), level + tracker.height
                )
            else:
                distance, half = floor_range(
                    line, plan.scanner_height(scanner), level + heights[0], level + heights[1]
                )
                spread = half / scatter
            used = (distance if strict else line) <= settings.max_distance
            readings[key] = Reading(heard[key], distance, used, spread)
            if used:
                measurements.append(Measurement(scanner.x, scanner.y, distance, spread))
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest = key
        return measurements, readings, nearest
