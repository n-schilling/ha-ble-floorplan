"""What can go on the plan: Home Assistant's scanners and the devices that can be tracked.

Also the floor plan's rooms and openings as YAML, so they can be edited as
text in the card.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

import probatio
import yaml

from homeassistant.components.bluetooth import async_current_scanners
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.util import slugify

from .const import DOMAIN, SCANNER_ACTIVE_SECONDS
from .coordinator import PRIVATE_BLE_DEVICE
from .model import Floorplan, Scanner, Tracker


class LayoutProblem(Exception):
    """The YAML of the rooms and openings is not a valid layout."""


def device_name(device: dr.BaseDeviceEntry) -> str | None:
    """Return the name the user sees for the device."""
    return device.name_by_user or device.name


def _bluetooth_devices(hass: HomeAssistant) -> dict[str, dr.DeviceEntry]:
    """Return address -> device of every device with a Bluetooth connection."""
    devices: dict[str, dr.DeviceEntry] = {}
    for device in dr.async_get(hass).devices:
        for kind, value in device.connections:
            if kind == CONNECTION_BLUETOOTH:
                devices[value.upper()] = device
    return devices


def alive_sources(hass: HomeAssistant) -> set[str]:
    """Return the sources of the scanners that received anything within the last minute.

    A scanner Home Assistant no longer has is not alive either.
    """
    return {
        scanner.source.upper()
        for scanner in async_current_scanners(hass)
        if scanner.time_since_last_detection() <= SCANNER_ACTIVE_SECONDS
    }


def offline_scanners(hass: HomeAssistant, plan: Floorplan) -> list[str]:
    """Return the keys of the plan's scanners that received nothing within the last minute."""
    alive = alive_sources(hass)
    return [s.key for s in plan.scanners if not s.paused and s.source not in alive]


def scanner_names(hass: HomeAssistant) -> dict[str, str]:
    """Return source -> name of every scanner Home Assistant has.

    The name of the scanner's device wins over the scanner's own name, which
    is often just its address.
    """
    by_address = _bluetooth_devices(hass)
    names: dict[str, str] = {}
    for scanner in async_current_scanners(hass):
        source = scanner.source.upper()
        known = by_address.get(source)
        names[source] = (device_name(known) if known is not None else None) or scanner.name
    return names


def candidates(hass: HomeAssistant, plan: Floorplan) -> dict[str, list[dict[str, Any]]]:
    """Return the scanners and the trackable devices that are not on the plan yet.

    Trackers are Private BLE Devices (phones and watches with changing
    addresses) and devices with a fixed Bluetooth address; scanners and the
    integration's own devices are left out.
    """
    sources = scanner_names(hass)
    on_plan_sources = {s.source for s in plan.scanners}
    scanners = [
        {"source": source, "name": name}
        for source, name in sources.items()
        if source not in on_plan_sources
    ]
    on_plan_addresses = {t.address for t in plan.trackers if t.address}
    on_plan_devices = {t.device_id for t in plan.trackers if t.device_id}
    devices = dr.async_get(hass)
    trackers: list[dict[str, Any]] = []
    private: set[str] = set()
    for entry in er.async_get(hass).entities.values():
        if (
            entry.domain != "device_tracker"
            or entry.platform != PRIVATE_BLE_DEVICE
            or entry.device_id is None
        ):
            continue
        private.add(entry.device_id)
        if entry.device_id in on_plan_devices:
            continue
        device = devices.async_get(entry.device_id)
        name = (device_name(device) if device is not None else None) or entry.entity_id
        trackers.append({"device_id": entry.device_id, "name": name})
    own = {e.entry_id for e in hass.config_entries.async_entries(DOMAIN)}
    for address, device in _bluetooth_devices(hass).items():
        if (
            address in sources
            or address in on_plan_addresses
            or device.id in private
            or device.config_entry_id in own
        ):
            continue
        trackers.append({"address": address, "name": device_name(device) or address})
    scanners.sort(key=lambda s: str(s["name"]).lower())
    trackers.sort(key=lambda t: str(t["name"]).lower())
    return {"scanners": scanners, "trackers": trackers}


def new_key(name: str, taken: Iterable[str]) -> str:
    """Return a key for the name that no scanner or tracker has yet."""
    base = slugify(name) or "item"
    used = set(taken)
    key = base
    number = 2
    while key in used:
        key = f"{base}_{number}"
        number += 1
    return key


def _center(plan: Floorplan) -> tuple[float, float]:
    width, height = plan.extent
    return (round(width / 2, 2), round(height / 2, 2))


def add_scanner(
    plan: Floorplan, source: str, name: str, z: float, floor: str = ""
) -> tuple[Floorplan, Scanner]:
    """Return the plan with a new scanner on the floor, in the middle of the plan."""
    x, y = _center(plan)
    scanner = Scanner(
        key=new_key(name, (s.key for s in plan.scanners)),
        name=name,
        source=source.upper(),
        x=x,
        y=y,
        z=z,
        floor=floor,
    )
    return replace(plan, scanners=(*plan.scanners, scanner)), scanner


def add_tracker(
    plan: Floorplan, name: str, address: str | None, device_id: str | None, height: float
) -> tuple[Floorplan, Tracker]:
    """Return the plan with a new tracker."""
    tracker = Tracker(
        key=new_key(name, (t.key for t in plan.trackers)),
        name=name,
        address=address.upper() if address else None,
        device_id=device_id,
        height=height,
    )
    return replace(plan, trackers=(*plan.trackers, tracker)), tracker


def remove_scanner(plan: Floorplan, key: str) -> Floorplan:
    """Return the plan without the scanner and its pair corrections."""
    return replace(
        plan,
        scanners=tuple(s for s in plan.scanners if s.key != key),
        pair_offsets={s: dict(t) for s, t in plan.pair_offsets.items() if s != key},
    )


def remove_tracker(plan: Floorplan, key: str) -> Floorplan:
    """Return the plan without the tracker and its pair corrections."""
    pairs = {s: {t: v for t, v in ts.items() if t != key} for s, ts in plan.pair_offsets.items()}
    return replace(
        plan,
        trackers=tuple(t for t in plan.trackers if t.key != key),
        pair_offsets={s: ts for s, ts in pairs.items() if ts},
    )


# What an empty plan starts from: two rooms and a door, to be overwritten
LAYOUT_TEMPLATE = """\
# Metres; the origin is the top left corner of the plan, y grows downwards.
# A room is a rectangle (x, y, w, h) or a polygon (points: [[x, y], ...]).
# zone: true marks an area inside a room, outdoor: true a balcony or garden.
rooms:
  - {name: Living room, x: 0, y: 0, w: 5, h: 4}
  - {name: Kitchen, x: 5, y: 0, w: 3, h: 4}
# area: links a room to an area of Home Assistant, by id or name.
# Doors and open passages: [x1, y1, x2, y2] on a wall
openings:
  - [5, 1, 5, 2]
# More floors or buildings: list them under floors (key, name, building,
# elevation in metres, ha_floor) and give rooms, scanners and stairs their
# floor; an opening names its floor fifth: [x1, y1, x2, y2, floor].
# Stairs join two floors: {floor: eg, to: og, x: 1, y: 1, w: 1, h: 3}
"""


def with_areas(hass: HomeAssistant, plan: Floorplan) -> Floorplan:
    """Return the plan with every room's area and every floor's floor of Home Assistant as ids.

    Both may be named by id or by name; one Home Assistant does not know is
    refused with LayoutProblem.
    """
    registry = ar.async_get(hass)
    rooms = []
    for room in plan.rooms:
        if room.area is None:
            rooms.append(room)
            continue
        area = registry.async_get_area(room.area) or registry.async_get_area_by_name(room.area)
        if area is None:
            raise LayoutProblem(f"room {room.name or '(no name)'}: no area {room.area}")
        rooms.append(replace(room, area=area.id))
    floor_registry = fr.async_get(hass)
    floors = []
    for floor in plan.floors:
        if floor.ha_floor is None:
            floors.append(floor)
            continue
        found = floor_registry.async_get_floor(
            floor.ha_floor
        ) or floor_registry.async_get_floor_by_name(floor.ha_floor)
        if found is None:
            raise LayoutProblem(f"floor {floor.name or floor.key}: no floor {floor.ha_floor}")
        floors.append(replace(floor, ha_floor=found.floor_id))
    return replace(plan, rooms=tuple(rooms), floors=tuple(floors))


# The parts of the plan the layout text holds
LAYOUT_KEYS = ("floors", "rooms", "openings", "stairs")


def layout_yaml(plan: Floorplan) -> str:
    """Return the floors, rooms, openings and stairs of the plan as YAML; a template for an empty plan."""
    if not plan.rooms and not plan.openings and not plan.floors:
        return LAYOUT_TEMPLATE
    data = plan.as_dict()
    # Defaults are left out, so the text stays short
    defaults = {"zone": False, "outdoor": False, "label": True}
    rooms = [{k: v for k, v in r.items() if defaults.get(k, object()) != v} for r in data["rooms"]]
    layout = {"floors": data.get("floors"), "rooms": rooms, "openings": data["openings"]}
    layout["stairs"] = data.get("stairs")
    return yaml.safe_dump(
        {k: v for k, v in layout.items() if v is not None},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=None,
    )


def with_layout_data(plan: Floorplan, data: Any) -> Floorplan:
    """Return the plan with the floors, rooms, openings and stairs given; raises LayoutProblem.

    The scanners keep their places; one on a floor the layout no longer has is
    refused. Without floors, the plan has one again, and every scanner stands on it.
    """
    if not isinstance(data, dict) or set(data) - set(LAYOUT_KEYS):
        raise LayoutProblem("expected a mapping with floors, rooms, openings and stairs")
    whole = plan.as_dict() | {key: data.get(key) or [] for key in LAYOUT_KEYS}
    if not whole["floors"]:
        # Back to one floor: the scanners stand on it
        whole["scanners"] = [
            {k: v for k, v in s.items() if k != "floor"} for s in whole["scanners"]
        ]
    try:
        return Floorplan.from_dict(whole)
    except probatio.Invalid as err:
        raise LayoutProblem(str(err)) from err


def with_layout(plan: Floorplan, text: str) -> Floorplan:
    """Return the plan with the floors, rooms, openings and stairs of the YAML; raises LayoutProblem.

    The scanners keep their places; one on a floor the layout no longer has is refused.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise LayoutProblem(f"not YAML: {err}") from err
    return with_layout_data(plan, {} if data is None else data)
