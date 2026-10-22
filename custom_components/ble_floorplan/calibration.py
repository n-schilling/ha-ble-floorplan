"""Calibration runs: the raw RSSI of every scanner while a tracker sits at a known place.

A run is started with the tracker's true position; the coordinator adds every
new advertisement of every scanner until the run is stopped. The runs are the
input of the adjustment in solver.py and live in a store of their own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Self

import probatio

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import (
    CALIBRATION_SAVE_DELAY_SECONDS,
    CALIBRATION_STORAGE_KEY,
    CALIBRATION_STORAGE_VERSION,
)
from .model import NUMBER

type Sample = tuple[float, float]  # (seconds since the start of the run, rssi)

SAMPLE = probatio.ExactSequence([NUMBER, NUMBER])
RUN_SCHEMA = probatio.Schema(
    {
        probatio.Required("id"): cv.string,
        probatio.Required("tracker"): cv.slug,
        probatio.Required("x"): NUMBER,
        probatio.Required("y"): NUMBER,
        probatio.Optional("height", default=0.0): NUMBER,
        probatio.Required("started"): cv.string,
        probatio.Optional("duration", default=None): probatio.Any(None, NUMBER),
        probatio.Optional("samples", default=dict): {cv.slug: [SAMPLE]},
    }
)
DATA_SCHEMA = probatio.Schema({probatio.Optional("runs", default=list): [RUN_SCHEMA]})


@dataclass(slots=True)
class CalibrationRun:
    """One run: the tracker at a known place, and what every scanner heard."""

    id: str
    tracker: str
    # True position of the tracker on the plan in metres
    x: float
    y: float
    # Height of the tracker above the floor during the run in metres
    height: float
    # Start in UTC, ISO 8601
    started: str
    # Length in seconds; None while the run is going
    duration: float | None = None
    # Scanner key -> samples
    samples: dict[str, list[Sample]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a run from validated data."""
        return cls(
            id=data["id"],
            tracker=data["tracker"],
            x=data["x"],
            y=data["y"],
            height=data["height"],
            started=data["started"],
            duration=data["duration"],
            samples={
                scanner: [(s[0], s[1]) for s in samples]
                for scanner, samples in data["samples"].items()
            },
        )

    @property
    def running(self) -> bool:
        """Return whether the run is still recording."""
        return self.duration is None

    def summary(self) -> dict[str, Any]:
        """Return the run without its samples, with the count per scanner."""
        return {
            "id": self.id,
            "tracker": self.tracker,
            "x": self.x,
            "y": self.y,
            "height": self.height,
            "started": self.started,
            "duration": self.duration,
            "running": self.running,
            "counts": {scanner: len(samples) for scanner, samples in self.samples.items()},
        }

    def as_dict(self) -> dict[str, Any]:
        """Return the run as stored, samples included."""
        return {
            "id": self.id,
            "tracker": self.tracker,
            "x": self.x,
            "y": self.y,
            "height": self.height,
            "started": self.started,
            "duration": self.duration,
            "samples": {
                scanner: [list(s) for s in samples] for scanner, samples in self.samples.items()
            },
        }


class CalibrationStore:
    """The runs, loaded once; a running one is written along, every other change at once."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store: Store[dict[str, Any]] = Store(
            hass, CALIBRATION_STORAGE_VERSION, CALIBRATION_STORAGE_KEY
        )
        self._listeners: list[CALLBACK_TYPE] = []
        self.runs: list[CalibrationRun] = []
        self.active: CalibrationRun | None = None
        # The monotonic time the active run started at
        self._start: float = 0.0
        # Whether a delayed write of the samples is scheduled
        self._save_pending = False

    async def async_load(self) -> list[CalibrationRun]:
        """Load the runs; a run that was going when Home Assistant stopped ends with its last sample."""
        if (data := await self._store.async_load()) is not None:
            valid = DATA_SCHEMA(data)
            self.runs = [CalibrationRun.from_dict(r) for r in valid["runs"]]
            closed = False
            for run in self.runs:
                if run.running:
                    run.duration = max(
                        (s[0] for samples in run.samples.values() for s in samples), default=0.0
                    )
                    closed = True
            if closed:
                await self._async_save()
        return self.runs

    def _data(self) -> dict[str, Any]:
        return {"runs": [run.as_dict() for run in self.runs]}

    async def _async_save(self) -> None:
        """Write now; a delayed write that was scheduled is covered by this one."""
        self._save_pending = False
        await self._store.async_save(self._data())

    def _delayed_data(self) -> dict[str, Any]:
        """Return the data for the delayed write; the next sample schedules the next one."""
        self._save_pending = False
        return self._data()

    def get(self, run_id: str) -> CalibrationRun | None:
        """Return the run with the id."""
        return next((r for r in self.runs if r.id == run_id), None)

    @property
    def finished(self) -> list[CalibrationRun]:
        """Return the runs that are over: what the adjustment works on."""
        return [r for r in self.runs if not r.running]

    def as_event(self) -> dict[str, Any]:
        """Return what the card shows: the active run's id and every run's summary."""
        return {
            "active": self.active.id if self.active is not None else None,
            "runs": [run.summary() for run in self.runs],
        }

    async def async_start(
        self, tracker: str, x: float, y: float, height: float, now: float
    ) -> CalibrationRun:
        """Start a run at the monotonic time now; raises RuntimeError while one is going."""
        if self.active is not None:
            raise RuntimeError("a calibration run is going")
        run = CalibrationRun(ulid_now(), tracker, x, y, height, dt_util.utcnow().isoformat())
        self.runs.append(run)
        self.active = run
        self._start = now
        await self._async_save()
        self._notify()
        return run

    @callback
    def add_sample(self, scanner_key: str, stamp: float, rssi: float) -> None:
        """Record an advertisement of the active run's tracker, heard by the scanner at stamp."""
        if self.active is None or stamp < self._start:
            return
        self.active.samples.setdefault(scanner_key, []).append((stamp - self._start, rssi))
        # Scheduled once per interval: the store itself would push the write
        # back with every call, and samples come every second
        if not self._save_pending:
            self._save_pending = True
            self._store.async_delay_save(self._delayed_data, CALIBRATION_SAVE_DELAY_SECONDS)

    async def async_stop(self, now: float) -> CalibrationRun:
        """Stop the active run at the monotonic time now; raises RuntimeError without one."""
        if (run := self.active) is None:
            raise RuntimeError("no calibration run is going")
        run.duration = max(now - self._start, 0.0)
        self.active = None
        await self._async_save()
        self._notify()
        return run

    async def async_delete(self, run_id: str) -> bool:
        """Delete a run, the active one included; returns whether there was one."""
        if (run := self.get(run_id)) is None:
            return False
        if run is self.active:
            self.active = None
        self.runs.remove(run)
        await self._async_save()
        self._notify()
        return True

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call the listener after every start, stop and delete; returns the remover."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove
