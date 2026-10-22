"""Import of the configuration of the earlier dashboard card.

The card knew scanners by the suffix of Bermuda's distance sensors and trackers
by the prefix of their entities. Here they become Bluetooth addresses and
Private BLE Devices.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.util import slugify

from .catalog import device_name, scanner_names
from .const import BERMUDA_REF_POWER_ENTITY
from .coordinator import PRIVATE_BLE_DEVICE
from .model import Floorplan

SETTING_KEYS = ("max_distance", "smoothing_seconds", "min_move", "clamp", "clamp_outdoor")


class ImportProblem(Exception):
    """Something of the card's configuration could not be mapped."""


def _scanner_slugs(hass: HomeAssistant) -> dict[str, str]:
    """Return source -> slug of the name of every Bluetooth scanner Home Assistant has.

    Bermuda names its distance sensors after the scanner's device in Home
    Assistant, so that device's name is slugged.
    """
    return {source: slugify(name) for source, name in scanner_names(hass).items()}


def _resolve_scanner(item: Mapping[str, Any], slugs: dict[str, str]) -> str:
    """Return the source of a card scanner: given, or matched by Bermuda's suffix."""
    if (source := item.get("source")) is not None:
        return str(source).upper()
    if (suffix := item.get("suffix")) is None:
        raise ImportProblem(f"scanner {item['key']}: neither source nor suffix given")
    matches = [s for s, slug in slugs.items() if slug == suffix or slug.startswith(f"{suffix}_")]
    if len(matches) != 1:
        known = ", ".join(sorted(slugs.values())) or "none"
        raise ImportProblem(
            f"scanner {item['key']}: suffix {suffix} matches {len(matches)} scanners (known: {known})"
        )
    return matches[0]


def _resolve_tracker(hass: HomeAssistant, item: Mapping[str, Any]) -> dict[str, Any]:
    """Return address or device_id and the name of a card tracker.

    A Private BLE Device is found through its device tracker (device_tracker.<key>
    unless entity_id says otherwise); a fixed address through a device of that
    name with a Bluetooth connection.
    """
    key = item.get("key") or item.get("prefix")
    if not key:
        raise ImportProblem("tracker without key or prefix")
    result: dict[str, Any] = {"key": key, "name": item.get("name") or key}
    if (address := item.get("address")) is not None:
        result["address"] = address
        return result
    devices = dr.async_get(hass)
    if (device_id := item.get("device_id")) is not None:
        if not isinstance(device := devices.async_get(device_id), dr.DeviceEntry):
            raise ImportProblem(f"tracker {key}: device {device_id} does not exist")
        result["device_id"] = device_id
        result["name"] = device_name(device) or result["name"]
        return result
    entities = er.async_get(hass)
    entity_id = item.get("entity_id") or f"device_tracker.{key}"
    entry = entities.async_get(entity_id)
    if entry is not None and entry.platform == PRIVATE_BLE_DEVICE and entry.device_id is not None:
        device = devices.async_get(entry.device_id)
        result["device_id"] = entry.device_id
        if isinstance(device, dr.DeviceEntry) and (name := device_name(device)):
            result["name"] = name
        return result
    for device in devices.devices:
        name = device_name(device)
        if name is None or slugify(name) != key:
            continue
        for kind, value in device.connections:
            if kind == CONNECTION_BLUETOOTH:
                result["address"] = value
                result["name"] = name
                return result
    raise ImportProblem(
        f"tracker {key}: {entity_id} is no Private BLE Device tracker and no device named "
        f"{key} has a Bluetooth address; give address or device_id"
    )


def _ref_power(hass: HomeAssistant, item: Mapping[str, Any], key: str) -> float | None:
    """Return the reference power: given, or Bermuda's calibration of the device if set."""
    if "ref_power" in item:
        value = item["ref_power"]
        return None if value is None else float(value)
    state = hass.states.get(BERMUDA_REF_POWER_ENTITY.format(prefix=key))
    if state is None:
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    return value if value != 0 else None


def build_floorplan(hass: HomeAssistant, config: Mapping[str, Any]) -> Floorplan:
    """Turn the card's configuration and the saved scanner positions into a floor plan.

    Raises ImportProblem when a scanner or tracker cannot be mapped and
    probatio.Invalid when the result is no valid floor plan.
    """
    slugs = _scanner_slugs(hass)
    positions: Mapping[str, Any] = config.get("positions") or {}
    scanners = []
    for item in config["scanners"]:
        position = positions.get(item["key"]) or item.get("default") or [0, 0]
        scanners.append(
            {
                "key": item["key"],
                "name": item.get("name") or item["key"],
                "source": _resolve_scanner(item, slugs),
                "x": position[0],
                "y": position[1],
                "z": item.get("z", 0),
                "rssi_offset": item.get("rssi_offset", 0),
            }
        )
    trackers = []
    for item in config["trackers"]:
        tracker = _resolve_tracker(hass, item)
        tracker["height"] = item.get("height", 0)
        tracker["ref_power"] = _ref_power(hass, item, tracker["key"])
        trackers.append(tracker)
    settings = {k: config[k] for k in SETTING_KEYS if k in config}
    settings.update(config.get("settings") or {})
    return Floorplan.from_dict(
        {
            "rooms": config["rooms"],
            "openings": config.get("openings") or [],
            "scanners": scanners,
            "trackers": trackers,
            "settings": settings,
        }
    )
