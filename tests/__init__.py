"""Tests for BLE Floorplan: a made-up flat, fake scanners and their advertisements."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothScannerDevice

from custom_components.ble_floorplan.model import Floorplan

# Addresses of the example only
SCANNER_LIVING = "AA:BB:CC:DD:EE:01"
SCANNER_KITCHEN = "AA:BB:CC:DD:EE:02"
SCANNER_BEDROOM = "AA:BB:CC:DD:EE:03"
TAG = "AA:BB:CC:DD:EE:10"
PHONE_ADDRESS = "AA:BB:CC:DD:EE:20"
PHONE_DEVICE_ID = "phone-device-id"

ROOMS: list[dict[str, Any]] = [
    {"name": "Living room", "x": 0, "y": 0, "w": 6, "h": 5},
    {"name": "Kitchen", "x": 6, "y": 0, "w": 4, "h": 5},
    {
        "name": "Bedroom",
        "points": [[0, 5], [6, 5], [6, 9], [2, 9], [2, 8], [0, 8]],
        "lx": 2.5,
        "ly": 6.5,
    },
    {"name": "Hall", "x": 6, "y": 5, "w": 4, "h": 4, "fs": 0.3, "rot": -90},
    {"name": "Dining", "x": 3, "y": 0, "w": 3, "h": 2.5, "zone": True},
    {"name": "Balcony", "x": 0, "y": 9, "w": 10, "h": 2, "outdoor": True, "label": False},
]
OPENINGS = [[6, 1, 6, 2.5], [3, 5, 4, 5], [6, 6, 6, 7]]
SCANNERS: list[dict[str, Any]] = [
    {
        "key": "living",
        "name": "Living room scanner",
        "source": SCANNER_LIVING,
        "x": 1,
        "y": 1,
        "z": 0.8,
    },
    {"key": "kitchen", "name": "Kitchen plug", "source": SCANNER_KITCHEN, "x": 9, "y": 1, "z": 2.0},
    {
        "key": "bedroom",
        "name": "Bedroom proxy",
        "source": SCANNER_BEDROOM,
        "x": 1,
        "y": 8,
        "z": 0.5,
    },
]
TRACKERS: list[dict[str, Any]] = [
    {"key": "tag", "name": "Tag", "address": TAG, "height": 0.3, "ref_power": -60},
    {"key": "phone", "name": "Phone", "device_id": PHONE_DEVICE_ID, "height": 1.0},
]
FLOORPLAN: dict[str, Any] = {
    "rooms": ROOMS,
    "openings": OPENINGS,
    "scanners": SCANNERS,
    "trackers": TRACKERS,
    "settings": {},
}


def make_plan(**overrides: Any) -> Floorplan:
    """Return the example plan, with parts replaced."""
    return Floorplan.from_dict({**FLOORPLAN, **overrides})


class FakeScanner:
    """What the engine needs of a Home Assistant scanner: source, name and timestamps."""

    def __init__(self, source: str, name: str) -> None:
        """Initialize the scanner."""
        self.source = source
        self.name = name
        self.discovered_device_timestamps: dict[str, float] = {}


def scanner_device(
    scanner: FakeScanner, address: str, rssi: int, stamp: float | None
) -> BluetoothScannerDevice:
    """Return an advertisement of the address as the scanner reports it to Home Assistant."""
    if stamp is not None:
        scanner.discovered_device_timestamps[address] = stamp
    advertisement = AdvertisementData(
        local_name=None,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        tx_power=-127,
        rssi=rssi,
        platform_data=(),
    )
    return BluetoothScannerDevice(scanner, BLEDevice(address, None, {}), advertisement)  # type: ignore[arg-type]


def rssi_for(
    floor_distance: float,
    ref_power: float,
    scanner_z: float = 0.0,
    tracker_height: float = 0.0,
    rssi_offset: float = 0.0,
    attenuation: float = 3.0,
) -> int:
    """Return the RSSI that gives the floor distance; rounded, so the distance is only close."""
    line = math.hypot(floor_distance, scanner_z - tracker_height)
    return round(ref_power + rssi_offset - 10 * attenuation * math.log10(line))


def rssi_exact(
    floor_distance: float,
    ref_power: float,
    scanner_z: float = 0.0,
    tracker_height: float = 0.0,
    rssi_offset: float = 0.0,
    attenuation: float = 3.0,
) -> float:
    """Return the exact RSSI that gives the floor distance."""
    line = math.hypot(floor_distance, scanner_z - tracker_height)
    return ref_power + rssi_offset - 10 * attenuation * math.log10(line)


def readings_of(position: Mapping[str, Any]) -> dict[str, float | None]:
    """Return scanner key -> distance of a position as the card gets it."""
    return {key: r["distance"] for key, r in position["readings"].items()}
