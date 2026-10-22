"""Constants for BLE Floorplan."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ble_floorplan"
NAME: Final = "BLE Floorplan"

# The floor plan, the scanners and the trackers live in a versioned store of
# their own: they are too large for the options of the config entry
STORAGE_KEY: Final = f"{DOMAIN}.floorplan"
STORAGE_VERSION: Final = 1
# The calibration runs: raw RSSI of every scanner while a tracker sits at a
# known place; a store of their own, they are only read for the adjustment
CALIBRATION_STORAGE_KEY: Final = f"{DOMAIN}.calibration"
CALIBRATION_STORAGE_VERSION: Final = 1
# A running calibration is written to storage this long after a new sample
CALIBRATION_SAVE_DELAY_SECONDS: Final = 10.0
# A scanner needs this many samples in a run for the run to count for it
CALIBRATION_MIN_SAMPLES: Final = 3
# A run closer than this to a scanner counts as this far, so the logarithm stays finite
CALIBRATION_MIN_DISTANCE: Final = 0.05

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
# Motion: the shown position moves at most this fast, in m/s (0 = no limit)
DEFAULT_MAX_SPEED: Final = 1.5
# A raw position farther than this from the shown one is a jump (0 = follow at once) …
DEFAULT_JUMP_DISTANCE: Final = 2.0
# … that is followed only after the raw position stayed there this long
DEFAULT_JUMP_CONFIRM_SECONDS: Final = 3.0
# The room changes only after the position lay in the new room this long …
DEFAULT_ROOM_HOLD_SECONDS: Final = 5.0
# … and at least this far from its walls (0 = anywhere inside)
DEFAULT_ROOM_MARGIN: Final = 0.3
# A scanner whose circle misses the position by more than this loses weight (0 = off)
DEFAULT_ROBUST_RESIDUAL: Final = 1.0
# A tracker counts as away once no scanner saw it this long (s)
DEFAULT_AWAY_SECONDS: Final = 120.0
# A scanner counts as active when it received anything this recently (s)
SCANNER_ACTIVE_SECONDS: Final = 60.0
# A wall is crossed only through an opening this close (m)
DOOR_TOLERANCE: Final = 0.15
# Going through a door, the position lands this far past it (m) …
DOOR_STEP: Final = 0.2
# … and stopped by a wall, this far before it
WALL_STOP: Final = 0.1

# The card, served by the integration
FRONTEND_URL_BASE: Final = f"/{DOMAIN}"
CARD_FILENAME: Final = "ble-floorplan-card.js"

# WebSocket commands
WS_GET_FLOORPLAN: Final = f"{DOMAIN}/get_floorplan"
WS_SUBSCRIBE: Final = f"{DOMAIN}/subscribe"
WS_SET_SCANNER: Final = f"{DOMAIN}/set_scanner"
WS_SET_TRACKER: Final = f"{DOMAIN}/set_tracker"
WS_SET_SETTINGS: Final = f"{DOMAIN}/set_settings"
WS_CANDIDATES: Final = f"{DOMAIN}/candidates"
WS_ADD_SCANNER: Final = f"{DOMAIN}/add_scanner"
WS_ADD_TRACKER: Final = f"{DOMAIN}/add_tracker"
WS_REMOVE_SCANNER: Final = f"{DOMAIN}/remove_scanner"
WS_REMOVE_TRACKER: Final = f"{DOMAIN}/remove_tracker"
WS_GET_LAYOUT: Final = f"{DOMAIN}/get_layout"
WS_SET_LAYOUT: Final = f"{DOMAIN}/set_layout"
WS_SET_FLOORPLAN: Final = f"{DOMAIN}/set_floorplan"
WS_CALIBRATION_START: Final = f"{DOMAIN}/calibration/start"
WS_CALIBRATION_STOP: Final = f"{DOMAIN}/calibration/stop"
WS_CALIBRATION_LIST: Final = f"{DOMAIN}/calibration/list"
WS_CALIBRATION_DELETE: Final = f"{DOMAIN}/calibration/delete"
WS_CALIBRATION_SOLVE: Final = f"{DOMAIN}/calibration/solve"
WS_CALIBRATION_APPLY: Final = f"{DOMAIN}/calibration/apply"
