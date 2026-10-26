"""The timeline: where every tracker was, kept for the days of the settings.

A point goes into the track of a tracker when it is seen again or no longer
seen, when its room changes, and when it moved HISTORY_MIN_MOVE since the last
point and that point is HISTORY_MIN_INTERVAL old. A tracker at rest adds
nothing; between two points it stayed where the first one says.

Every day (UTC) has a store of its own that starts with where every tracker
was at midnight, so a day is read alone. Only today's is written to; an index
store names the days there are.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
import math
from typing import TYPE_CHECKING, Any

import probatio

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    HISTORY_MIN_INTERVAL,
    HISTORY_MIN_MOVE,
    HISTORY_SAVE_DELAY_SECONDS,
    HISTORY_STORAGE_KEY,
    HISTORY_STORAGE_VERSION,
)
from .model import NUMBER

if TYPE_CHECKING:
    from .coordinator import Positions

# (unix time, x, y, room); x and y are None while no scanner sees the tracker
type Point = tuple[float, float | None, float | None, str | None]
type Tracks = dict[str, list[Point]]

COORD = probatio.Any(None, NUMBER)
POINT = probatio.ExactSequence([NUMBER, COORD, COORD, probatio.Any(None, cv.string)])
DAY_SCHEMA = probatio.Schema(
    {
        probatio.Required("saved"): NUMBER,
        probatio.Optional("tracks", default=dict): {cv.slug: [POINT]},
    }
)
INDEX_SCHEMA = probatio.Schema({probatio.Optional("days", default=list): [cv.string]})


def day_of(t: float) -> str:
    """Return the UTC day of the unix time t, as YYYY-MM-DD."""
    return datetime.fromtimestamp(t, UTC).date().isoformat()


def day_start(day: str) -> float:
    """Return the unix time of the day's midnight, UTC."""
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC).timestamp()


def _seen(point: Point | None) -> bool:
    return point is not None and point[1] is not None


class _Day:
    """One day's track and its store."""

    def __init__(self, hass: HomeAssistant, day: str, tracks: Tracks) -> None:
        self.day = day
        self.tracks = tracks
        self.store: Store[dict[str, Any]] = _day_store(hass, day)
        self._save_pending = False

    def data(self) -> dict[str, Any]:
        """Return the day as stored."""
        return {
            "saved": dt_util.utcnow().timestamp(),
            "tracks": {key: [list(p) for p in track] for key, track in self.tracks.items()},
        }

    def _delayed_data(self) -> dict[str, Any]:
        self._save_pending = False
        return self.data()

    @callback
    def schedule_save(self) -> None:
        """Write the day a while after the first new point; the next point schedules the next write.

        Scheduled once per interval: the store itself would push the write
        back with every call, and points may come every two seconds.
        """
        if not self._save_pending:
            self._save_pending = True
            self.store.async_delay_save(self._delayed_data, HISTORY_SAVE_DELAY_SECONDS)

    async def async_save(self) -> None:
        """Write now; a delayed write that was scheduled is covered by this one."""
        self._save_pending = False
        await self.store.async_save(self.data())


def _day_store(hass: HomeAssistant, day: str) -> Store[dict[str, Any]]:
    return Store(hass, HISTORY_STORAGE_VERSION, f"{HISTORY_STORAGE_KEY}.{day}")


def _tracks_of(data: Mapping[str, Any]) -> Tracks:
    return {
        key: [(p[0], p[1], p[2], p[3]) for p in points] for key, points in data["tracks"].items()
    }


class HistoryStore:
    """The tracks of all trackers, today's in memory, the other days in storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self.hass = hass
        self._index: Store[dict[str, Any]] = Store(
            hass, HISTORY_STORAGE_VERSION, HISTORY_STORAGE_KEY
        )
        # The days in storage, oldest first
        self.days: list[str] = []
        self._today: _Day | None = None
        # Set when Home Assistant stops or the entry unloads: nothing more is recorded
        self._closed = False

    async def async_load(self, now: float, keep_days: int) -> None:
        """Load the index and today's track; drop what is older than keep_days.

        A tracker that was seen when the track was last written gets a gap
        there: what happened while Home Assistant was down is unknown.
        """
        if (data := await self._index.async_load()) is not None:
            self.days = sorted(set(INDEX_SCHEMA(data)["days"]))
        await self.async_prune(now, keep_days)

    async def async_prune(self, now: float, keep_days: int) -> None:
        """Remove the days that ended more than keep_days ago; 0 removes every day."""
        cutoff = day_of(now - keep_days * 86400) if keep_days else None
        gone = [d for d in self.days if cutoff is None or d < cutoff]
        if self._today is not None and (cutoff is None or self._today.day < cutoff):
            self._today = None
        for day in gone:
            await _day_store(self.hass, day).async_remove()
        if gone:
            self.days = [d for d in self.days if d not in gone]
            await self._index.async_save({"days": self.days})

    async def async_day(self, day: str) -> Tracks:
        """Return the tracks of a day; nothing for a day that is not stored."""
        if self._today is not None and self._today.day == day:
            return {key: list(track) for key, track in self._today.tracks.items()}
        if day not in self.days:
            return {}
        if (data := await _day_store(self.hass, day).async_load()) is None:
            return {}
        return _tracks_of(DAY_SCHEMA(data))

    async def _async_open(self, day: str) -> _Day:
        """Return today's track: from storage after a restart, else a new day."""
        tracks: Tracks = {}
        if day in self.days and (data := await _day_store(self.hass, day).async_load()):
            valid = DAY_SCHEMA(data)
            tracks = _tracks_of(valid)
            for track in tracks.values():
                if _seen(track[-1] if track else None):
                    track.append((valid["saved"], None, None, None))
        elif self._today is not None:
            # Where every tracker was at midnight starts the new day
            start = day_start(day)
            for key, track in self._today.tracks.items():
                if _seen(last := track[-1] if track else None):
                    assert last is not None
                    tracks[key] = [(start, last[1], last[2], last[3])]
        opened = _Day(self.hass, day, tracks)
        if day not in self.days:
            self.days.append(day)
            await self._index.async_save({"days": self.days})
        return opened

    async def async_record(self, positions: Positions, now: float, keep_days: int) -> None:
        """Add the points the positions at the unix time now call for."""
        if self._closed or not keep_days:
            return
        day = day_of(now)
        if self._today is None or self._today.day != day:
            previous = self._today
            self._today = await self._async_open(day)
            if previous is not None:
                await previous.async_save()
                await self.async_prune(now, keep_days)
        today = self._today
        assert today is not None
        added = False
        for key, position in positions.items():
            point: Point = (
                (round(now, 1), round(position.x, 2), round(position.y, 2), position.room or None)
                if position.x is not None and position.y is not None
                else (round(now, 1), None, None, None)
            )
            track = today.tracks.get(key)
            if _wanted(track[-1] if track else None, point):
                today.tracks.setdefault(key, []).append(point)
                added = True
        if added:
            today.schedule_save()

    @callback
    def close(self, now: float) -> None:
        """End every track with a gap at the unix time now; recording stops.

        The delayed write carries the gaps; Home Assistant writes pending
        stores before it stops.
        """
        self._closed = True
        if (today := self._today) is None:
            return
        added = False
        for track in today.tracks.values():
            if _seen(track[-1] if track else None):
                track.append((round(now, 1), None, None, None))
                added = True
        if added:
            today.schedule_save()

    async def async_close(self, now: float) -> None:
        """End every track and write today's at once, for an unload of the entry."""
        self.close(now)
        if self._today is not None:
            await self._today.async_save()

    async def async_remove(self) -> None:
        """Remove every day and the index, with the entry."""
        await self.async_load(dt_util.utcnow().timestamp(), 0)
        await self._index.async_remove()


def _wanted(last: Point | None, point: Point) -> bool:
    """Return whether the point says something the last one does not."""
    if _seen(last) != _seen(point):
        return True
    if not _seen(point):
        return False
    assert last is not None
    if point[3] != last[3]:
        return True
    assert point[1] is not None and point[2] is not None
    assert last[1] is not None and last[2] is not None
    return (
        point[0] - last[0] >= HISTORY_MIN_INTERVAL
        and math.hypot(point[1] - last[1], point[2] - last[2]) >= HISTORY_MIN_MOVE
    )


def to_wire(tracks: Tracks) -> dict[str, list[list[Any]]]:
    """Return the tracks for the card."""
    return {key: [list(p) for p in track] for key, track in tracks.items()}
