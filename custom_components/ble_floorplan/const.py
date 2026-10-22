"""Constants for BLE Floorplan."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ble_floorplan"
NAME: Final = "BLE Floorplan"

# The floor plan, the scanners and the trackers live in a versioned store of
# their own: they are too large for the options of the config entry
STORAGE_KEY: Final = f"{DOMAIN}.floorplan"
STORAGE_VERSION: Final = 1

# How often the positions are recomputed from the advertisements Home
# Assistant's Bluetooth scanners hold
UPDATE_INTERVAL_SECONDS: Final = 1.0
# An advertisement older than this counts as "not seen" by that scanner
STALE_SECONDS: Final = 30.0
# The RSSI of a scanner is the median of the samples of this window, counted
# back from the newest sample
RSSI_WINDOW_SECONDS: Final = 10.0

# Defaults of the global settings
DEFAULT_ATTENUATION: Final = 3.0
DEFAULT_REF_POWER: Final = -55.0
DEFAULT_SMOOTHING_SECONDS: Final = 20.0
DEFAULT_MIN_MOVE: Final = 0.25
DEFAULT_MAX_DISTANCE: Final = 15.0

# The card, served by the integration
FRONTEND_URL_BASE: Final = f"/{DOMAIN}"
CARD_FILENAME: Final = "ble-floorplan-card.js"

# WebSocket commands
WS_GET_FLOORPLAN: Final = f"{DOMAIN}/get_floorplan"
WS_SUBSCRIBE: Final = f"{DOMAIN}/subscribe"
WS_SET_SCANNER: Final = f"{DOMAIN}/set_scanner"
WS_SET_FLOORPLAN: Final = f"{DOMAIN}/set_floorplan"
WS_IMPORT: Final = f"{DOMAIN}/import"

# Bermuda keeps a calibration number per device; 0 means "use the default"
BERMUDA_REF_POWER_ENTITY: Final = "number.{prefix}_calibration_ref_power_at_1m_0_for_default"
