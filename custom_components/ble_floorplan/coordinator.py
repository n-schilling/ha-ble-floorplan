"""The coordinator: reads the scanners' advertisements and places the trackers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.bluetooth import MONOTONIC_TIME, async_scanner_devices_by_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .calibration import CalibrationRun, CalibrationStore
from .const import DOMAIN, RSSI_WINDOW_SECONDS, STALE_SECONDS, UPDATE_INTERVAL_SECONDS
from .engine import Measurement, Smoother, floor_distance, median, rssi_to_distance, trilaterate
from .model import Floorplan, Tracker
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
    ) -> None:
        """Initialize the coordinator."""
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
        self._samples: dict[tuple[str, str], deque[Sample]] = {}
        self._smoother = Smoother()
        # device_id -> entity_id of the device tracker of a Private BLE Device
        self._tracker_entities: dict[str, str] = {}

    @property
    def plan(self) -> Floorplan:
        """Return the current floor plan."""
        return self.store.plan

    async def _async_update_data(self) -> Positions:
        """Compute the positions."""
        return self.compute(MONOTONIC_TIME())

    def compute(self, now: float) -> Positions:
        """Compute the position of every tracker at the monotonic time now."""
        plan = self.plan
        sources = {s.source: s.key for s in plan.scanners}
        positions: Positions = {}
        for tracker in plan.trackers:
            address = self._address_of(tracker)
            if address is not None:
                self._collect(tracker.key, address, sources)
            positions[tracker.key] = self._locate(tracker, address, now, plan)
        return positions

    async def async_start_calibration(
        self, tracker_key: str, x: float, y: float, height: float
    ) -> CalibrationRun:
        """Start recording the tracker's advertisements at its true position."""
        return await self.calibration.async_start(tracker_key, x, y, height, MONOTONIC_TIME())

    async def async_stop_calibration(self) -> CalibrationRun:
        """Stop the recording."""
        return await self.calibration.async_stop(MONOTONIC_TIME())

    def _address_of(self, tracker: Tracker) -> str | None:
        """Return the address to look for: fixed, or the current one of the Private BLE Device."""
        if tracker.address is not None:
            return tracker.address
        assert tracker.device_id is not None
        if (entity_id := self._tracker_entities.get(tracker.device_id)) is None:
            registry = er.async_get(self.hass)
            for entry in er.async_entries_for_device(registry, tracker.device_id, True):
                if entry.domain == "device_tracker" and entry.platform == PRIVATE_BLE_DEVICE:
                    entity_id = self._tracker_entities[tracker.device_id] = entry.entity_id
                    break
            else:
                return None
        state = self.hass.states.get(entity_id)
        if state is None or (address := state.attributes.get(ATTR_CURRENT_ADDRESS)) is None:
            return None
        return str(address).upper()

    def _collect(self, key: str, address: str, sources: dict[str, str]) -> None:
        """Take the newest advertisement of every scanner that sees the address.

        A new advertisement also goes into the calibration run of the tracker,
        when one is going and the scanner is in the plan.
        """
        run = self.calibration.active
        for device in async_scanner_devices_by_address(self.hass, address, connectable=False):
            scanner = device.scanner
            stamp = scanner.discovered_device_timestamps.get(address)
            samples = self._samples.setdefault((key, scanner.source), deque())
            if stamp is not None and samples and stamp <= samples[-1][0]:
                continue
            sample = (stamp if stamp is not None else MONOTONIC_TIME(), device.advertisement.rssi)
            samples.append(sample)
            if run is not None and run.tracker == key and scanner.source in sources:
                self.calibration.add_sample(sources[scanner.source], sample[0], sample[1])

    def _locate(
        self, tracker: Tracker, address: str | None, now: float, plan: Floorplan
    ) -> TrackerPosition:
        """Turn the collected samples of a tracker into a position."""
        settings = plan.settings
        ref_power = plan.ref_power(tracker)
        readings: dict[str, Reading] = {}
        measurements: list[Measurement] = []
        nearest: str | None = None
        nearest_distance = float("inf")
        for scanner in plan.scanners:
            samples = self._samples.get((tracker.key, scanner.source))
            if samples:
                # Drop what fell out of the window; the newest sample defines it
                newest = samples[-1][0]
                while samples[0][0] < newest - RSSI_WINDOW_SECONDS:
                    samples.popleft()
            if not samples or samples[-1][0] < now - STALE_SECONDS:
                readings[scanner.key] = Reading(None, None, False)
                continue
            rssi = median([s[1] for s in samples])
            offset = scanner.rssi_offset + plan.pair_offset(scanner.key, tracker.key)
            distance = floor_distance(
                rssi_to_distance(rssi, ref_power, offset, settings.attenuation),
                scanner.z,
                tracker.height,
            )
            used = distance <= settings.max_distance
            readings[scanner.key] = Reading(rssi, distance, used)
            if used:
                measurements.append(Measurement(scanner.x, scanner.y, distance))
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest = scanner.key
        raw = trilaterate(measurements, plan)
        if raw is None:
            self._smoother.reset(tracker.key)
            return TrackerPosition(
                tracker.key, address, None, None, None, None, None, None, 0, readings
            )
        x, y = self._smoother.smooth(tracker.key, raw, now, plan)
        return TrackerPosition(
            tracker.key,
            address,
            x,
            y,
            raw[0],
            raw[1],
            plan.room_at(x, y),
            nearest,
            len(measurements),
            readings,
        )
