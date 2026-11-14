"""Calibration runs: the raw RSSI of every scanner while a tracker sits at a known place.

A run is started with the tracker's true position; the coordinator adds every
new advertisement of every scanner until the run is stopped. The runs are the
input of the adjustment in solver.py and live in a store of their own.

A guided run shows per scanner how far it is, and can end by itself once
every scanner that hears the tracker often enough has enough samples. The
guide tells per tracker in which rooms it was measured with the scanners as
they stand.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import math
from typing import Any, Self

import probatio

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import (
    CALIBRATION_AUTO_MAX_SECONDS,
    CALIBRATION_AUTO_MIN_SECONDS,
    CALIBRATION_GOOD_ERROR,
    CALIBRATION_GOOD_SAMPLES,
    CALIBRATION_SAVE_DELAY_SECONDS,
    CALIBRATION_SETUP_TOLERANCE,
    CALIBRATION_STORAGE_KEY,
    CALIBRATION_STORAGE_VERSION,
    CALIBRATION_TARGET_SAMPLES,
    CALIBRATION_WEAK_RATE,
)
from .model import NUMBER, Floorplan

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
        probatio.Optional("scanners", default=None): probatio.Any(
            None, {cv.slug: probatio.ExactSequence([NUMBER, NUMBER, NUMBER])}
        ),
        probatio.Optional("floor", default=""): probatio.Any("", cv.slug),
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
    # Where the plan's scanners stood when the run started: key -> (x, y, z),
    # z above the ground of the site; None for a run recorded before it was
    # kept. A scanner moved, added or taken off since makes the run describe
    # another setup.
    scanners: dict[str, tuple[float, float, float]] | None = None
    # The floor the tracker lay on; "" is the plan's first floor
    floor: str = ""

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
            scanners=(
                {key: (p[0], p[1], p[2]) for key, p in scanners.items()}
                if (scanners := data.get("scanners")) is not None
                else None
            ),
            floor=data.get("floor", ""),
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
        } | self._scanners_dict()

    def _scanners_dict(self) -> dict[str, Any]:
        """Return where the scanners stood and the floor, each only when known."""
        extra: dict[str, Any] = {"floor": self.floor} if self.floor else {}
        if self.scanners is None:
            return extra
        return extra | {"scanners": {k: list(p) for k, p in self.scanners.items()}}

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
        } | self._scanners_dict()


def scanner_progress(samples: list[Sample], elapsed: float) -> dict[str, Any]:
    """Return how far a scanner is in a run: its samples, the standard error of their mean, its state.

    The state is done (enough samples, or a mean known well enough), weak
    (hears the tracker too seldom to wait for) or collecting.
    """
    n = len(samples)
    error: float | None = None
    if n >= 2:
        mean = sum(s[1] for s in samples) / n
        spread = math.sqrt(sum((s[1] - mean) ** 2 for s in samples) / (n - 1))
        error = spread / math.sqrt(n)
    if n >= CALIBRATION_TARGET_SAMPLES or (
        n >= CALIBRATION_GOOD_SAMPLES and error is not None and error <= CALIBRATION_GOOD_ERROR
    ):
        state = "done"
    elif elapsed >= CALIBRATION_AUTO_MIN_SECONDS and n / elapsed < CALIBRATION_WEAK_RATE:
        state = "weak"
    else:
        state = "collecting"
    return {
        "count": n,
        "error": round(error, 2) if error is not None else None,
        "state": state,
    }


def setup_matches(run: CalibrationRun, plan: Floorplan) -> bool | None:
    """Return whether the plan's scanners stand as they did in the run; None when the run does not tell."""
    if run.scanners is None:
        return None
    if {s.key for s in plan.scanners} != set(run.scanners):
        return False
    return all(
        abs(a - b) <= CALIBRATION_SETUP_TOLERANCE
        for s in plan.scanners
        for a, b in zip(run.scanners[s.key], (s.x, s.y, plan.scanner_height(s)), strict=True)
    )


def guide(plan: Floorplan, runs: list[CalibrationRun]) -> dict[str, list[dict[str, Any]]]:
    """Return per tracker every room with walls, with its floor, and how many of its finished runs lie there.

    A run made with the scanners standing elsewhere does not count; one that
    does not tell how they stood does.
    """
    places = list(dict.fromkeys((r.floor, r.name) for r in plan.rooms if not r.zone))
    result: dict[str, list[dict[str, Any]]] = {}
    for tracker in plan.trackers:
        counts = dict.fromkeys(places, 0)
        for run in runs:
            if run.tracker != tracker.key or run.running or setup_matches(run, plan) is False:
                continue
            level = plan.on_level(plan.floor(run.floor or plan.floor_list[0].key).elevation)
            if (room := level.space_of(run.x, run.y)) is not None:
                counts[(room.floor, room.name)] += 1
        result[tracker.key] = [
            {"room": name, "floor": floor, "runs": n} for (floor, name), n in counts.items()
        ]
    return result


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
        # Whether the active run ends by itself, and how long it has been going
        self.auto_stop = False
        self.elapsed = 0.0
        # The run stopped last in this session, with the values its stop saved
        self.stopped: dict[str, Any] | None = None

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

    def as_event(self, plan: Floorplan | None = None) -> dict[str, Any]:
        """Return what the page shows: the active run's id and every run's summary.

        While a run is going, how far it is; after a stop, what it saved; with
        the plan, the guide.
        """
        event: dict[str, Any] = {
            "active": self.active.id if self.active is not None else None,
            "runs": [run.summary() for run in self.runs],
        }
        if self.active is not None:
            event["progress"] = self.progress()
        if self.stopped is not None:
            event["stopped"] = self.stopped
        if plan is not None:
            event["guide"] = guide(plan, self.runs)
        return event

    def progress(self) -> dict[str, Any]:
        """Return how far the active run is: its length, whether it ends by itself, each scanner."""
        assert self.active is not None
        return {
            "elapsed": round(self.elapsed, 1),
            "auto_stop": self.auto_stop,
            "max_seconds": CALIBRATION_AUTO_MAX_SECONDS if self.auto_stop else None,
            "target": CALIBRATION_TARGET_SAMPLES,
            "scanners": {
                key: scanner_progress(samples, self.elapsed)
                for key, samples in self.active.samples.items()
            },
        }

    def tick(self, now: float) -> bool:
        """Note the monotonic time now; returns whether the active run should end by itself.

        The listeners hear of every tick of a going run, whether or not a
        position changed. It ends after the shortest time once one scanner has
        enough and every other is done or hears the tracker too seldom, and at
        the latest after the longest time.
        """
        if self.active is None:
            return False
        self.elapsed = max(now - self._start, 0.0)
        self._notify()
        if not self.auto_stop:
            return False
        if self.elapsed >= CALIBRATION_AUTO_MAX_SECONDS:
            return True
        if self.elapsed < CALIBRATION_AUTO_MIN_SECONDS:
            return False
        states = [p["state"] for p in self.progress()["scanners"].values()]
        return "done" in states and all(state in ("done", "weak") for state in states)

    @callback
    def note_stopped(self, run: CalibrationRun, fit: dict[str, Any] | None, auto: bool) -> None:
        """Keep what the stop of the run saved, for the page to show, and tell the listeners."""
        self.stopped = {"run": run.id, "auto": auto, "fit": fit}
        self._notify()

    async def async_start(
        self,
        tracker: str,
        x: float,
        y: float,
        height: float,
        now: float,
        scanners: dict[str, tuple[float, float, float]] | None = None,
        auto_stop: bool = False,
        floor: str = "",
    ) -> CalibrationRun:
        """Start a run at the monotonic time now, with where the scanners stand.

        With auto_stop, tick tells when it has enough. Raises RuntimeError
        while one is going.
        """
        if self.active is not None:
            raise RuntimeError("a calibration run is going")
        run = CalibrationRun(
            ulid_now(),
            tracker,
            x,
            y,
            height,
            dt_util.utcnow().isoformat(),
            scanners=scanners,
            floor=floor,
        )
        self.runs.append(run)
        self.active = run
        self._start = now
        self.auto_stop = auto_stop
        self.elapsed = 0.0
        self.stopped = None
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

    async def async_stop(self, now: float, notify: bool = True) -> CalibrationRun:
        """Stop the active run at the monotonic time now; raises RuntimeError without one.

        Without notify, the listeners hear of it with note_stopped.
        """
        if (run := self.active) is None:
            raise RuntimeError("no calibration run is going")
        run.duration = max(now - self._start, 0.0)
        self.active = None
        await self._async_save()
        if notify:
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

    async def async_clear(self) -> None:
        """Delete every run, the active one included."""
        self.runs = []
        self.active = None
        self.stopped = None
        await self._async_save()
        self._notify()

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
