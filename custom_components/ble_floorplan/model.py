"""The data model of the floor plan: rooms, openings, scanners, trackers and settings.

Everything is validated by one schema, used by the store, the WebSocket
commands and the import alike, and kept as immutable dataclasses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Self

import probatio

from homeassistant.helpers import config_validation as cv

from .const import (
    DEFAULT_ATTENUATION,
    DEFAULT_JUMP_CONFIRM_SECONDS,
    DEFAULT_JUMP_DISTANCE,
    DEFAULT_MAX_DISTANCE,
    DEFAULT_MAX_SPEED,
    DEFAULT_MIN_MOVE,
    DEFAULT_REF_POWER,
    DEFAULT_ROBUST_RESIDUAL,
    DEFAULT_ROOM_HOLD_SECONDS,
    DEFAULT_ROOM_MARGIN,
    DEFAULT_SMOOTHING_SECONDS,
)
from .geometry import Point, closest_on_outline, point_in_polygon, point_in_rect

NUMBER = probatio.Coerce(float)
POINT = probatio.ExactSequence([NUMBER, NUMBER])
OPENING = probatio.ExactSequence([NUMBER, NUMBER, NUMBER, NUMBER])


def mac_address(value: Any) -> str:
    """Validate a Bluetooth address and return it upper case, as Home Assistant keeps it."""
    text = cv.string(value).upper()
    parts = text.split(":")
    if len(parts) != 6 or any(
        len(p) != 2 or not all(c in "0123456789ABCDEF" for c in p) for p in parts
    ):
        raise probatio.Invalid(f"{value} is no Bluetooth address")
    return text


def _rect_or_polygon(room: dict[str, Any]) -> dict[str, Any]:
    """A room is a rectangle (x, y, w, h) or a polygon (points), not both, not neither."""
    has_rect = all(k in room for k in ("x", "y", "w", "h"))
    has_points = "points" in room
    if has_rect == has_points:
        raise probatio.Invalid("a room needs either x, y, w and h or points")
    if has_rect and (room["w"] <= 0 or room["h"] <= 0):
        raise probatio.Invalid("w and h of a room must be positive")
    return room


def _one_address(tracker: dict[str, Any]) -> dict[str, Any]:
    """A tracker has a fixed address or refers to a Private BLE Device, not both."""
    if ("address" in tracker) == ("device_id" in tracker):
        raise probatio.Invalid("a tracker needs either address or device_id")
    return tracker


def _unique_keys(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [item["key"] for item in items]
    if len(set(keys)) != len(keys):
        raise probatio.Invalid("keys must be unique")
    return items


ROOM_SCHEMA = probatio.All(
    probatio.Schema(
        {
            probatio.Optional("name", default=""): cv.string,
            probatio.Optional("x"): NUMBER,
            probatio.Optional("y"): NUMBER,
            probatio.Optional("w"): NUMBER,
            probatio.Optional("h"): NUMBER,
            probatio.Optional("points"): probatio.All([POINT], probatio.Length(min=3)),
            probatio.Optional("zone", default=False): cv.boolean,
            probatio.Optional("outdoor", default=False): cv.boolean,
            probatio.Optional("lx"): NUMBER,
            probatio.Optional("ly"): NUMBER,
            probatio.Optional("fs"): NUMBER,
            probatio.Optional("rot"): NUMBER,
            probatio.Optional("label", default=True): cv.boolean,
        }
    ),
    _rect_or_polygon,
)

SCANNER_SCHEMA = probatio.Schema(
    {
        probatio.Required("key"): cv.slug,
        probatio.Required("name"): cv.string,
        probatio.Required("source"): mac_address,
        probatio.Optional("x", default=0.0): NUMBER,
        probatio.Optional("y", default=0.0): NUMBER,
        probatio.Optional("z", default=0.0): NUMBER,
        probatio.Optional("rssi_offset", default=0.0): NUMBER,
    }
)

TRACKER_SCHEMA = probatio.All(
    probatio.Schema(
        {
            probatio.Required("key"): cv.slug,
            probatio.Required("name"): cv.string,
            probatio.Optional("address"): mac_address,
            probatio.Optional("device_id"): cv.string,
            probatio.Optional("height", default=0.0): NUMBER,
            probatio.Optional("ref_power", default=None): probatio.Any(None, NUMBER),
        }
    ),
    _one_address,
)

SETTINGS_SCHEMA = probatio.Schema(
    {
        probatio.Optional("attenuation", default=DEFAULT_ATTENUATION): probatio.All(
            NUMBER, probatio.Range(min=1.0, max=6.0)
        ),
        probatio.Optional("ref_power_default", default=DEFAULT_REF_POWER): probatio.All(
            NUMBER, probatio.Range(min=-127.0, max=0.0)
        ),
        probatio.Optional("smoothing_seconds", default=DEFAULT_SMOOTHING_SECONDS): probatio.All(
            NUMBER, probatio.Range(min=0.0)
        ),
        probatio.Optional("min_move", default=DEFAULT_MIN_MOVE): probatio.All(
            NUMBER, probatio.Range(min=0.0)
        ),
        probatio.Optional("max_distance", default=DEFAULT_MAX_DISTANCE): probatio.All(
            NUMBER, probatio.Range(min=0.1)
        ),
        probatio.Optional("clamp", default=True): cv.boolean,
        probatio.Optional("clamp_outdoor", default=False): cv.boolean,
        probatio.Optional("max_speed", default=DEFAULT_MAX_SPEED): probatio.All(
            NUMBER, probatio.Range(min=0.0)
        ),
        probatio.Optional("jump_distance", default=DEFAULT_JUMP_DISTANCE): probatio.All(
            NUMBER, probatio.Range(min=0.0)
        ),
        probatio.Optional(
            "jump_confirm_seconds", default=DEFAULT_JUMP_CONFIRM_SECONDS
        ): probatio.All(NUMBER, probatio.Range(min=0.0)),
        probatio.Optional("room_hold_seconds", default=DEFAULT_ROOM_HOLD_SECONDS): probatio.All(
            NUMBER, probatio.Range(min=0.0)
        ),
        probatio.Optional("room_margin", default=DEFAULT_ROOM_MARGIN): probatio.All(
            NUMBER, probatio.Range(min=0.0)
        ),
        probatio.Optional("robust_residual", default=DEFAULT_ROBUST_RESIDUAL): probatio.All(
            NUMBER, probatio.Range(min=0.0)
        ),
    }
)

# Correction per pair scanner x tracker in dB: {scanner key: {tracker key: dB}}
PAIR_OFFSETS_SCHEMA = probatio.Schema({cv.slug: {cv.slug: NUMBER}})

FLOORPLAN_SCHEMA = probatio.Schema(
    {
        probatio.Optional("rooms", default=list): [ROOM_SCHEMA],
        probatio.Optional("openings", default=list): [OPENING],
        probatio.Optional("scanners", default=list): probatio.All([SCANNER_SCHEMA], _unique_keys),
        probatio.Optional("trackers", default=list): probatio.All([TRACKER_SCHEMA], _unique_keys),
        probatio.Optional("settings", default=dict): SETTINGS_SCHEMA,
        probatio.Optional("pair_offsets", default=dict): PAIR_OFFSETS_SCHEMA,
    }
)

type PairOffsets = Mapping[str, Mapping[str, float]]


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Drop the optional values that are not set."""
    return {k: v for k, v in data.items() if v is not None}


@dataclass(frozen=True, slots=True)
class Room:
    """A room: a rectangle or a polygon, with its label options."""

    name: str
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    points: tuple[Point, ...] | None = None
    zone: bool = False
    outdoor: bool = False
    lx: float | None = None
    ly: float | None = None
    fs: float | None = None
    rot: float | None = None
    label: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a room from validated data."""
        points = data.get("points")
        return cls(
            name=data["name"],
            x=data.get("x"),
            y=data.get("y"),
            w=data.get("w"),
            h=data.get("h"),
            points=tuple((p[0], p[1]) for p in points) if points is not None else None,
            zone=data["zone"],
            outdoor=data["outdoor"],
            lx=data.get("lx"),
            ly=data.get("ly"),
            fs=data.get("fs"),
            rot=data.get("rot"),
            label=data["label"],
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the room as stored and sent to the card."""
        return _clean(
            {
                "name": self.name,
                "x": self.x,
                "y": self.y,
                "w": self.w,
                "h": self.h,
                "points": [list(p) for p in self.points] if self.points is not None else None,
                "zone": self.zone,
                "outdoor": self.outdoor,
                "lx": self.lx,
                "ly": self.ly,
                "fs": self.fs,
                "rot": self.rot,
                "label": self.label,
            }
        )

    @property
    def corners(self) -> tuple[Point, ...]:
        """Return the outline, clockwise for a rectangle, as given for a polygon."""
        if self.points is not None:
            return self.points
        assert (
            self.x is not None and self.y is not None and self.w is not None and self.h is not None
        )
        return (
            (self.x, self.y),
            (self.x + self.w, self.y),
            (self.x + self.w, self.y + self.h),
            (self.x, self.y + self.h),
        )

    def contains(self, x: float, y: float) -> bool:
        """Return whether the point lies in the room."""
        if self.points is not None:
            return point_in_polygon(self.points, x, y)
        assert (
            self.x is not None and self.y is not None and self.w is not None and self.h is not None
        )
        return point_in_rect(self.x, self.y, self.w, self.h, x, y)


@dataclass(frozen=True, slots=True)
class Scanner:
    """A Bluetooth scanner at a fixed place."""

    key: str
    name: str
    # The address Home Assistant knows the scanner by (scanner.source)
    source: str
    x: float = 0.0
    y: float = 0.0
    # Height above the floor in metres
    z: float = 0.0
    # Added to the reference power for this scanner, in dB
    rssi_offset: float = 0.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a scanner from validated data."""
        return cls(**data)

    def as_dict(self) -> dict[str, Any]:
        """Return the scanner as stored and sent to the card."""
        return {
            "key": self.key,
            "name": self.name,
            "source": self.source,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "rssi_offset": self.rssi_offset,
        }


@dataclass(frozen=True, slots=True)
class Tracker:
    """A tracked device: a fixed address or a Private BLE Device of Home Assistant."""

    key: str
    name: str
    address: str | None = None
    # Device registry id of the Private BLE Device whose current address is tracked
    device_id: str | None = None
    # Height above the floor in metres, usually where it is worn or carried
    height: float = 0.0
    # RSSI at one metre in dBm; None takes the default of the settings
    ref_power: float | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a tracker from validated data."""
        return cls(**data)

    def as_dict(self) -> dict[str, Any]:
        """Return the tracker as stored and sent to the card."""
        return _clean(
            {
                "key": self.key,
                "name": self.name,
                "address": self.address,
                "device_id": self.device_id,
                "height": self.height,
                "ref_power": self.ref_power,
            }
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """The global settings of the position engine."""

    attenuation: float = DEFAULT_ATTENUATION
    ref_power_default: float = DEFAULT_REF_POWER
    smoothing_seconds: float = DEFAULT_SMOOTHING_SECONDS
    min_move: float = DEFAULT_MIN_MOVE
    max_distance: float = DEFAULT_MAX_DISTANCE
    clamp: bool = True
    clamp_outdoor: bool = False
    # Motion: top speed of the shown position in m/s, 0 for none
    max_speed: float = DEFAULT_MAX_SPEED
    # A raw position this far from the shown one is followed only after it
    # stayed there for jump_confirm_seconds; 0 follows at once
    jump_distance: float = DEFAULT_JUMP_DISTANCE
    jump_confirm_seconds: float = DEFAULT_JUMP_CONFIRM_SECONDS
    # The room changes after the position lay in the new room this long and
    # this far from its walls
    room_hold_seconds: float = DEFAULT_ROOM_HOLD_SECONDS
    room_margin: float = DEFAULT_ROOM_MARGIN
    # Scanners whose circle misses the position by more than this lose weight; 0 is off
    robust_residual: float = DEFAULT_ROBUST_RESIDUAL

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build the settings from validated data."""
        return cls(**data)

    def as_dict(self) -> dict[str, Any]:
        """Return the settings as stored and sent to the card."""
        return {
            "attenuation": self.attenuation,
            "ref_power_default": self.ref_power_default,
            "smoothing_seconds": self.smoothing_seconds,
            "min_move": self.min_move,
            "max_distance": self.max_distance,
            "clamp": self.clamp,
            "clamp_outdoor": self.clamp_outdoor,
            "max_speed": self.max_speed,
            "jump_distance": self.jump_distance,
            "jump_confirm_seconds": self.jump_confirm_seconds,
            "room_hold_seconds": self.room_hold_seconds,
            "room_margin": self.room_margin,
            "robust_residual": self.robust_residual,
        }


@dataclass(frozen=True, slots=True)
class Floorplan:
    """The whole floor plan."""

    rooms: tuple[Room, ...] = ()
    openings: tuple[tuple[float, float, float, float], ...] = ()
    scanners: tuple[Scanner, ...] = ()
    trackers: tuple[Tracker, ...] = ()
    settings: Settings = field(default_factory=Settings)
    # Correction of the reference power per pair scanner x tracker in dB, from
    # the calibration: the scanners' response differs from tracker to tracker
    pair_offsets: PairOffsets = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Validate and build the floor plan; raises probatio.Invalid on bad data."""
        valid = FLOORPLAN_SCHEMA(dict(data))
        return cls(
            rooms=tuple(Room.from_dict(r) for r in valid["rooms"]),
            openings=tuple((o[0], o[1], o[2], o[3]) for o in valid["openings"]),
            scanners=tuple(Scanner.from_dict(s) for s in valid["scanners"]),
            trackers=tuple(Tracker.from_dict(t) for t in valid["trackers"]),
            settings=Settings.from_dict(valid["settings"]),
            pair_offsets={
                scanner: dict(trackers) for scanner, trackers in valid["pair_offsets"].items()
            },
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the floor plan as stored and sent to the card."""
        return {
            "rooms": [r.as_dict() for r in self.rooms],
            "openings": [list(o) for o in self.openings],
            "scanners": [s.as_dict() for s in self.scanners],
            "trackers": [t.as_dict() for t in self.trackers],
            "settings": self.settings.as_dict(),
            "pair_offsets": {
                scanner: dict(trackers) for scanner, trackers in self.pair_offsets.items()
            },
        }

    @property
    def inside_rooms(self) -> tuple[Room, ...]:
        """Return the rooms a tracker may be placed in; empty when clamping is off."""
        if not self.settings.clamp:
            return ()
        return tuple(
            r for r in self.rooms if not r.zone and (self.settings.clamp_outdoor or not r.outdoor)
        )

    @property
    def extent(self) -> tuple[float, float]:
        """Return the width and height of the plan, from the origin."""
        max_x = 0.0
        max_y = 0.0
        for room in self.rooms:
            for x, y in room.corners:
                max_x = max(max_x, x)
                max_y = max(max_y, y)
        return max_x, max_y

    def scanner(self, key: str) -> Scanner | None:
        """Return the scanner with the key."""
        return next((s for s in self.scanners if s.key == key), None)

    def tracker(self, key: str) -> Tracker | None:
        """Return the tracker with the key."""
        return next((t for t in self.trackers if t.key == key), None)

    def ref_power(self, tracker: Tracker) -> float:
        """Return the reference power of the tracker: its own, or the default."""
        if tracker.ref_power is not None:
            return tracker.ref_power
        return self.settings.ref_power_default

    def pair_offset(self, scanner_key: str, tracker_key: str) -> float:
        """Return the correction of the pair in dB, 0 without one."""
        return self.pair_offsets.get(scanner_key, {}).get(tracker_key, 0.0)

    def room_at(self, x: float, y: float) -> str | None:
        """Return the name of the room at the point.

        Zones win over the rooms they lie in, and of overlapping rooms the one
        drawn last wins, because it covers the others.
        """
        room = self.room_of(x, y)
        return room.name if room is not None else None

    def room_of(self, x: float, y: float) -> Room | None:
        """Return the room at the point, with the same precedence as room_at."""
        ordered = sorted(reversed(self.rooms), key=lambda r: not r.zone)
        return next((r for r in ordered if r.contains(x, y)), None)

    def clamp(self, x: float, y: float) -> Point:
        """Move a point outside every room to the closest point of a wall."""
        rooms = self.inside_rooms
        if not rooms or any(r.contains(x, y) for r in rooms):
            return (x, y)
        best: Point = (x, y)
        best_d = float("inf")
        for room in rooms:
            q, d = closest_on_outline(room.corners, x, y)
            if d < best_d:
                best_d = d
                best = q
        return best


def replace_scanner(plan: Floorplan, scanner: Scanner) -> Floorplan:
    """Return the plan with the scanner of the same key replaced."""
    return replace(
        plan, scanners=tuple(scanner if s.key == scanner.key else s for s in plan.scanners)
    )


def with_calibration(
    plan: Floorplan,
    attenuation: float | None,
    ref_powers: Mapping[str, float],
    rssi_offsets: Mapping[str, float],
    pair_offsets: PairOffsets,
) -> Floorplan:
    """Return the plan with the calibration written in.

    Trackers and scanners that are not named keep their values; the pairs given
    are set, the other pairs stay. Raises LookupError for an unknown key.
    """
    for key in ref_powers:
        if plan.tracker(key) is None:
            raise LookupError(f"no tracker {key}")
    for key in rssi_offsets:
        if plan.scanner(key) is None:
            raise LookupError(f"no scanner {key}")
    for scanner_key, trackers in pair_offsets.items():
        if plan.scanner(scanner_key) is None:
            raise LookupError(f"no scanner {scanner_key}")
        for tracker_key in trackers:
            if plan.tracker(tracker_key) is None:
                raise LookupError(f"no tracker {tracker_key}")
    pairs = {scanner: dict(trackers) for scanner, trackers in plan.pair_offsets.items()}
    for scanner_key, trackers in pair_offsets.items():
        pairs.setdefault(scanner_key, {}).update(trackers)
    return replace(
        plan,
        trackers=tuple(
            replace(t, ref_power=ref_powers[t.key]) if t.key in ref_powers else t
            for t in plan.trackers
        ),
        scanners=tuple(
            replace(s, rssi_offset=rssi_offsets[s.key]) if s.key in rssi_offsets else s
            for s in plan.scanners
        ),
        settings=plan.settings
        if attenuation is None
        else replace(plan.settings, attenuation=attenuation),
        pair_offsets=pairs,
    )


def with_scanner_position(scanner: Scanner, x: float, y: float, z: float | None = None) -> Scanner:
    """Return the scanner moved to x, y and, when given, the height z."""
    return replace(scanner, x=x, y=y, z=scanner.z if z is None else z)


def with_pair_offsets(
    plan: Floorplan, scanner_key: str, trackers: Mapping[str, float | None]
) -> Floorplan:
    """Return the plan with the pairs of the scanner set; None removes a pair."""
    pairs = {scanner: dict(ts) for scanner, ts in plan.pair_offsets.items()}
    mine = pairs.setdefault(scanner_key, {})
    for tracker_key, value in trackers.items():
        if value is None:
            mine.pop(tracker_key, None)
        else:
            mine[tracker_key] = value
    if not mine:
        del pairs[scanner_key]
    return replace(plan, pair_offsets=pairs)


def with_settings(plan: Floorplan, changes: Mapping[str, Any]) -> Floorplan:
    """Return the plan with the settings given changed; raises probatio.Invalid on bad values."""
    merged = {**plan.settings.as_dict(), **changes}
    return replace(plan, settings=Settings.from_dict(SETTINGS_SCHEMA(merged)))
