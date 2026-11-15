"""How good each scanner is, and where its trouble lies: the device, the site, its place in the plan.

Three figures, gathered while Home Assistant runs, over the last day:

Reception: per tracker, how many advertisements the scanner took, against
the scanner that took the most of the same tracker in the same time;
averaged over the trackers it heard. A low figure is mostly the device: how
often it scans and reports (a Shelly reports a fraction of what an ESPHome
proxy does).

Fidelity: every second, for every tracker seen by enough scanners, the
position is solved without the scanner, and the scanner's circle is held
against it: the miss is how much longer (positive) or shorter its distance
is than the way to that position. A miss that scatters while the others
agree points at the site: reflections, metal, something in the way. A miss
that grows towards one side means the scanner stands elsewhere than the plan
says: misses m ≈ a + dx·cos θ + dy·sin θ over the directions θ to the
trackers give (dx, dy), where it rather stands.

Contribution: how many cells of the coverage model get worse without the
scanner, on its level. Good reception with no contribution is a scanner in
the wrong place or one too many.

Everything is kept per hour, for as many hours as the setting quality_hours
says, and written to storage every few minutes, so a restart keeps it.

Each scanner has its own start: when it came into the plan, and again when
its place, height, offset or pair corrections change, since the figures
before tell of another setup; what it gathered until then is dropped. Its
reception is held against the other scanners only over the time since
its start: in the hour it started, only what the others took after it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import TYPE_CHECKING, Any

import probatio

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_QUALITY_HOURS,
    QUALITY_CONTRIBUTION_FAIR,
    QUALITY_CONTRIBUTION_GOOD,
    QUALITY_DIRECTIONS,
    QUALITY_MIN_MISSES,
    QUALITY_MIN_SCANNERS,
    QUALITY_MIN_TRACKER_SAMPLES,
    QUALITY_OUTLIER,
    QUALITY_RATE_FAIR,
    QUALITY_RATE_GOOD,
    QUALITY_SAVE_DELAY_SECONDS,
    QUALITY_SHIFT,
    QUALITY_SPREAD_FAIR,
    QUALITY_SPREAD_GOOD,
    QUALITY_STORAGE_KEY,
    QUALITY_STORAGE_VERSION,
)
from .coverage import model
from .engine import Measurement, solve_point
from .model import NUMBER, Floorplan, Scanner

if TYPE_CHECKING:
    from .geometry import Point

GOOD = "good"
FAIR = "fair"
POOR = "poor"
UNKNOWN = "unknown"

# Sums of the misses of one scanner: n, Σm, Σm², outliers, Σc, Σs, Σcc, Σss, Σcs, Σmc, Σms
_N, _M, _MM, _OUT, _C, _S, _CC, _SS, _CS, _MC, _MS = range(11)

# In storage: per scanner its start and the setup it counts for; per hour
# (unix time // 3600) counts {"tracker|scanner": n} and misses {scanner: sums}
DATA_SCHEMA = probatio.Schema(
    {
        # One start for all scanners, before each had its own: not used
        probatio.Remove("since"): object,
        probatio.Optional("scanners", default=dict): {
            cv.string: {
                probatio.Required("since"): NUMBER,
                probatio.Required("basis"): list,
                probatio.Optional("base", default=dict): {cv.string: probatio.Coerce(int)},
            }
        },
        probatio.Optional("hours", default=dict): {
            probatio.Coerce(int): {
                probatio.Optional("counts", default=dict): {cv.string: probatio.Coerce(int)},
                probatio.Optional("misses", default=dict): {
                    cv.string: probatio.All([NUMBER], probatio.Length(min=11, max=11))
                },
            }
        },
    }
)


@dataclass(slots=True)
class _Hour:
    # (tracker, scanner) -> advertisements taken
    counts: dict[tuple[str, str], int] = field(default_factory=dict)
    # scanner -> sums of its misses
    misses: dict[str, list[float]] = field(default_factory=dict)


def basis(plan: Floorplan, scanner: Scanner) -> list[Any]:
    """Return the setup of the scanner its figures count for, as stored.

    Where it stands and how high, its offset and its pair corrections; paused
    or not, so one that comes back starts afresh.
    """
    pairs = plan.pair_offsets.get(scanner.key, {})
    return [
        scanner.x,
        scanner.y,
        plan.scanner_height(scanner),
        scanner.rssi_offset,
        [[t, pairs[t]] for t in sorted(pairs)],
        scanner.paused,
    ]


@dataclass(slots=True)
class _Start:
    # Unix time it started gathering, the setup it gathers for
    since: float
    basis: list[Any]
    # What every scanner had taken in the hour of the start, before it: not held against it
    base: dict[tuple[str, str], int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Heard:
    """A scanner that went into a position: its key, where it stands, its distance."""

    key: str
    x: float
    y: float
    distance: float


class QualityTracker:
    """Reception and fidelity per scanner, per hour of the last hours the setting keeps."""

    def __init__(self, hass: HomeAssistant | None = None) -> None:
        """Initialize the tracker; with hass it is kept in storage."""
        self._hours: dict[int, _Hour] = {}
        self._now = 0.0
        self._starts: dict[str, _Start] = {}
        # The plan the starts were last compared for; a saved plan is a new object
        self._plan: Floorplan | None = None
        self.keep = DEFAULT_QUALITY_HOURS
        self._store: Store[dict[str, Any]] | None = (
            Store(hass, QUALITY_STORAGE_VERSION, QUALITY_STORAGE_KEY) if hass else None
        )
        self._save_pending = False

    async def async_load(self, now: float, keep: int) -> None:
        """Load what was gathered, the hours that still count; raises probatio.Invalid on bad data."""
        assert self._store is not None
        self._now = now
        self.keep = keep
        if (data := await self._store.async_load()) is None:
            return
        valid = DATA_SCHEMA(data)
        self._starts = {
            k: _Start(v["since"], v["basis"], {_pair(c): n for c, n in v["base"].items()})
            for k, v in valid["scanners"].items()
        }
        for hour, item in valid["hours"].items():
            counts = {_pair(key): n for key, n in item["counts"].items()}
            self._hours[hour] = _Hour(counts, {k: list(v) for k, v in item["misses"].items()})
        self._prune()

    def _data(self) -> dict[str, Any]:
        self._save_pending = False
        return {
            "scanners": {
                k: {
                    "since": v.since,
                    "basis": v.basis,
                    "base": {f"{t}|{s}": n for (t, s), n in v.base.items()},
                }
                for k, v in self._starts.items()
            },
            "hours": {
                str(hour): {
                    "counts": {f"{t}|{s}": n for (t, s), n in item.counts.items()},
                    "misses": item.misses,
                }
                for hour, item in self._hours.items()
            },
        }

    async def async_save(self) -> None:
        """Write now, for an unload of the entry."""
        if self._store is not None:
            await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Remove what is stored, with the entry."""
        if self._store is not None:
            await self._store.async_remove()

    def _prune(self) -> None:
        """Drop the hours that no longer count; the starts move up with them."""
        first = int(self._now // 3600) - self.keep + 1
        for old in [h for h in self._hours if h < first]:
            del self._hours[old]
        for start in self._starts.values():
            if start.since < first * 3600.0:
                # The hour of the start is gone, and what was before it in that hour with it
                start.since, start.base = first * 3600.0, {}

    def begin(self, now: float, keep: int | None = None) -> None:
        """Start a refresh at the unix time now, keeping the last keep hours: what follows goes into its hour."""
        self._now = now
        if keep is not None and keep != self.keep:
            self.keep = keep
            self._prune()
        hour = int(now // 3600)
        if hour not in self._hours:
            self._hours[hour] = _Hour()
            self._prune()
        # Written every few minutes; Home Assistant writes what is pending when it stops
        if self._store is not None and not self._save_pending:
            self._save_pending = True
            self._store.async_delay_save(self._data, QUALITY_SAVE_DELAY_SECONDS)

    def setup(self, plan: Floorplan) -> None:
        """Hold each scanner's setup against the plan: a new or changed one starts afresh, a gone one is dropped.

        Call after begin(), so a start is the time of the refresh.
        """
        if plan is self._plan:
            return
        self._plan = plan
        for key in [k for k in self._starts if plan.scanner(k) is None]:
            self._drop(key)
            del self._starts[key]
        new = {}
        for scanner in plan.scanners:
            now_basis = basis(plan, scanner)
            start = self._starts.get(scanner.key)
            if start is None or start.basis != now_basis:
                self._drop(scanner.key)
                new[scanner.key] = now_basis
        # Taken once all that starts afresh is dropped
        base = dict(self._hour().counts)
        for key, now_basis in new.items():
            self._starts[key] = _Start(self._now, now_basis, base)

    def _drop(self, scanner: str) -> None:
        """Forget what the scanner gathered."""
        for hour in self._hours.values():
            hour.misses.pop(scanner, None)
            for key in [k for k in hour.counts if k[1] == scanner]:
                del hour.counts[key]

    def since(self, scanner: str) -> float | None:
        """Return when the scanner started gathering; None for one not in the plan."""
        start = self._starts.get(scanner)
        return None if start is None else start.since

    def _hour(self) -> _Hour:
        return self._hours.setdefault(int(self._now // 3600), _Hour())

    def count(self, tracker: str, scanner: str) -> None:
        """Note an advertisement of the tracker the scanner took."""
        counts = self._hour().counts
        counts[(tracker, scanner)] = counts.get((tracker, scanner), 0) + 1

    def misses(self, heard: list[Heard], start: Point) -> None:
        """Hold every scanner's circle against the position solved without it, from the start point."""
        if len(heard) < QUALITY_MIN_SCANNERS + 1:
            return
        hour = self._hour()
        for i, own in enumerate(heard):
            others = [Measurement(h.x, h.y, h.distance) for j, h in enumerate(heard) if j != i]
            point = solve_point(others, start)
            way = math.hypot(point[0] - own.x, point[1] - own.y)
            if way < 0.5:
                # Right on the scanner the direction says nothing
                continue
            m = own.distance - way
            c = (point[0] - own.x) / way
            s = (point[1] - own.y) / way
            sums = hour.misses.setdefault(own.key, [0.0] * 11)
            for k, v in (
                (_N, 1.0),
                (_M, m),
                (_MM, m * m),
                (_OUT, 1.0 if abs(m) > QUALITY_OUTLIER else 0.0),
                (_C, c),
                (_S, s),
                (_CC, c * c),
                (_SS, s * s),
                (_CS, c * s),
                (_MC, m * c),
                (_MS, m * s),
            ):
                sums[k] += v

    # ---- Figures ----

    def rate(self, scanner: str) -> dict[str, Any]:
        """Return the reception of the scanner against the best one, over the trackers it heard.

        Only the time since its start counts, for it and the others alike.
        """
        if (start := self._starts.get(scanner)) is None:
            return {"value": None, "trackers": 0, "state": UNKNOWN}
        first = int(start.since // 3600)
        counts: dict[tuple[str, str], int] = {}
        for h, hour in self._hours.items():
            if h < first:
                continue
            for key, n in hour.counts.items():
                if h == first:
                    n = max(n - start.base.get(key, 0), 0)
                counts[key] = counts.get(key, 0) + n
        best: dict[str, int] = {}
        for (tracker, _), n in counts.items():
            best[tracker] = max(best.get(tracker, 0), n)
        shares = [
            counts[(tracker, scanner)] / most
            for tracker, most in best.items()
            if most >= QUALITY_MIN_TRACKER_SAMPLES and counts.get((tracker, scanner), 0) > 0
        ]
        if not shares:
            return {"value": None, "trackers": 0, "state": UNKNOWN}
        value = sum(shares) / len(shares)
        state = GOOD if value >= QUALITY_RATE_GOOD else FAIR if value >= QUALITY_RATE_FAIR else POOR
        return {"value": round(value, 2), "trackers": len(shares), "state": state}

    def fidelity(self, scanner: str) -> dict[str, Any]:
        """Return how the scanner's circles fit the others: mean, spread, outliers, the shift its misses suggest."""
        sums = [0.0] * 11
        for hour in self._hours.values():
            for k, v in enumerate(hour.misses.get(scanner, ())):
                sums[k] += v
        n = sums[_N]
        if n < QUALITY_MIN_MISSES:
            return {
                "n": int(n),
                "bias": None,
                "spread": None,
                "outliers": None,
                "shift": None,
                "state": UNKNOWN,
            }
        mean = sums[_M] / n
        spread = math.sqrt(max(sums[_MM] / n - mean * mean, 0.0))
        shift = _shift(sums)
        state = (
            GOOD
            if spread <= QUALITY_SPREAD_GOOD
            else FAIR
            if spread <= QUALITY_SPREAD_FAIR
            else POOR
        )
        if shift is not None and state == GOOD:
            state = FAIR
        return {
            "n": int(n),
            "bias": round(mean, 2),
            "spread": round(spread, 2),
            "outliers": round(sums[_OUT] / n, 2),
            "shift": shift,
            "state": state,
        }

    def summary(self, scanner: str) -> dict[str, Any]:
        """Return the reception and the fidelity; the cheap part, for the list."""
        rate = self.rate(scanner)
        fidelity = self.fidelity(scanner)
        return {
            "rate": rate,
            "fidelity": fidelity,
            "state": _worst(rate["state"], fidelity["state"]),
        }

    def report(self, scanner: str, part: dict[str, Any], shelly: bool = False) -> dict[str, Any]:
        """Return all three figures, the time they cover, and the findings, the most telling first.

        part is the scanner's contribution, as contribution() gives it; shelly
        whether it runs on a Shelly, which explains a low reception.
        """
        rate = self.rate(scanner)
        fidelity = self.fidelity(scanner)
        findings: list[str] = []
        if rate["state"] == UNKNOWN or fidelity["state"] == UNKNOWN:
            findings.append("few_data")
        if fidelity["shift"] is not None:
            findings.append("plan_position")
        if fidelity["state"] == POOR:
            findings.append("site")
        if rate["state"] == POOR:
            findings.append("device" if shelly else "reception")
        if part["state"] == POOR:
            findings.append("redundant")
        since = self.since(scanner)
        return {
            "since": since,
            # Hours gone by since its start, as far as they still count
            "hours": None if since is None else round(max(self._now - since, 0.0) / 3600, 1),
            "rate": rate,
            "fidelity": fidelity,
            "contribution": part,
            "findings": findings or ["good"],
        }


def _pair(key: str) -> tuple[str, str]:
    """Return the tracker and the scanner of a stored "tracker|scanner"."""
    tracker, _, scanner = key.partition("|")
    return tracker, scanner


def _shift(sums: list[float]) -> dict[str, float] | None:
    """Return where the misses say the scanner stands, relative to the plan; None when they do not tell.

    A least-squares fit of m = a + dx·c + dy·s. It needs trackers seen from
    enough directions, and a shift worth naming.
    """
    n = sums[_N]
    mc, ms = sums[_C] / n, sums[_S] / n
    vcc = sums[_CC] / n - mc * mc
    vss = sums[_SS] / n - ms * ms
    vcs = sums[_CS] / n - mc * ms
    det = vcc * vss - vcs * vcs
    if det < QUALITY_DIRECTIONS:
        return None
    mean = sums[_M] / n
    ccm = sums[_MC] / n - mean * mc
    csm = sums[_MS] / n - mean * ms
    # A scanner that stands farther along u hears the trackers in direction u
    # nearer than the plan says: the fit comes out with the opposite sign
    dx = -(vss * ccm - vcs * csm) / det
    dy = -(vcc * csm - vcs * ccm) / det
    if math.hypot(dx, dy) < QUALITY_SHIFT:
        return None
    return {"dx": round(dx, 2), "dy": round(dy, 2), "m": round(math.hypot(dx, dy), 2)}


def contribution(plan: Floorplan, scanner: str) -> dict[str, Any]:
    """Return how many cells of the coverage model on the scanner's level get worse without it."""
    own = plan.scanner(scanner)
    if own is None or own.paused:
        return {"worse": 0, "cells": 0, "share": None, "state": UNKNOWN}
    level = plan.floor(own.floor).elevation
    without = replace(plan, scanners=tuple(s for s in plan.scanners if s.key != scanner))
    before = {(c[0], c[1]): c[2] for c in model(plan, None, (), level)["cells"]}
    after = {(c[0], c[1]): c[2] for c in model(without, None, (), level)["cells"]}
    worse = sum(1 for cell, lvl in before.items() if after.get(cell, lvl) < lvl)
    if not before:
        return {"worse": 0, "cells": 0, "share": None, "state": UNKNOWN}
    share = worse / len(before)
    state = (
        GOOD
        if share >= QUALITY_CONTRIBUTION_GOOD
        else FAIR
        if share >= QUALITY_CONTRIBUTION_FAIR
        else POOR
    )
    return {"worse": worse, "cells": len(before), "share": round(share, 3), "state": state}


def _worst(*states: str) -> str:
    """Return the worst of the states; unknown only when all are."""
    known = [s for s in states if s != UNKNOWN]
    if not known:
        return UNKNOWN
    return POOR if POOR in known else FAIR if FAIR in known else GOOD
