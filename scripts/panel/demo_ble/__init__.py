"""Made-up Bluetooth scanners for the page checks of BLE Floorplan.

Registers the scanners of the made-up flat as remote scanners, as ESPHome
proxies are, and every second lets them hear the made-up trackers with the
signal strength the distance gives. Nothing goes on air; it lives only in the
throwaway Home Assistant of scripts/panel/check_panel.py, which passes the
flat in configuration.yaml.
"""

from __future__ import annotations

from datetime import timedelta
import math
from typing import Any

from homeassistant.components.bluetooth import (
    MONOTONIC_TIME,
    BaseHaRemoteScanner,
    async_register_scanner,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

DOMAIN = "demo_ble"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the scanners and let them hear the trackers once a second."""
    flat: dict[str, Any] = config[DOMAIN]
    scanners: list[tuple[BaseHaRemoteScanner, dict[str, Any]]] = []
    for item in flat["scanners"]:
        scanner = BaseHaRemoteScanner(item["source"], item["name"])
        async_register_scanner(hass, scanner)
        scanner.async_setup()
        scanners.append((scanner, item))

    @callback
    def _hear(_now: Any = None) -> None:
        now = MONOTONIC_TIME()
        for tracker in flat["trackers"]:
            for scanner, item in scanners:
                line = math.dist(
                    (tracker["x"], tracker["y"], tracker["height"]),
                    (item["x"], item["y"], item["z"]),
                )
                rssi = round(tracker["ref_power"] - 30 * math.log10(max(line, 0.1)))
                scanner._async_on_advertisement(
                    tracker["address"], rssi, None, [], {}, {}, None, {}, now
                )

    _hear()
    async_track_time_interval(hass, _hear, timedelta(seconds=1))
    return True
