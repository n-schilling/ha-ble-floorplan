# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-22

### Added

- Calibration mode: a run records the raw RSSI of every scanner while a tracker sits at a known place (`ble_floorplan/calibration/start` with the tracker, its true position and optionally its height, `…/stop`, `…/list`, `…/delete`). The runs live in a store of their own; a run that is going when Home Assistant stops ends with its last sample.
- Adjustment over all finished runs (`ble_floorplan/calibration/solve`): least squares over the log-distance model with the true distances gives the reference power of every tracker, the offset of every scanner (averaging zero) and, on request, the path loss exponent; what the fit leaves per pair scanner × tracker becomes the pair's correction. The result is a proposal with the current and the proposed value of every parameter and the RMS error before and after; `ble_floorplan/calibration/apply` writes what it is given into the plan and reloads the entry. Nothing is applied by itself.
- `pair_offsets` in the floor plan: a correction in dB per scanner and tracker, added to the scanner's offset for that tracker only.
- The card has a calibration mode for admins: tap the plan for the true position, start and stop a run, the runs with their sample counts per scanner, compute with a preview of every change, apply.
- `ble_floorplan/subscribe` sends the runs with the snapshot, on every change, and with the positions while a run is going.

### Fixed

- A subscription of the card now follows a reload of the entry (after `set_floorplan`, `import` or `apply`) with a fresh snapshot instead of going quiet.

## [0.1.0] - 2026-10-22

### Added

- One config entry *BLE Floorplan*; the floor plan (rooms, openings), the scanners (position, height, RSSI offset) and the trackers (fixed address or Private BLE Device, height, reference power) live in a versioned store of the integration.
- Position engine: per tracker the RSSI of every scanner from Home Assistant's Bluetooth stack (median of a short window, advertisements older than 30 s count as not seen), distance by the log-distance path loss model, projected onto the floor from the scanner's height, weighted Gauss-Newton trilateration, clamping into the rooms, time-based smoothing with a dead zone, room by polygon.
- Sensors per tracker: *Room* (with position, nearest scanner, scanner count and the distance of every scanner as attributes), *Position X* and *Position Y* (diagnostic).
- WebSocket API: `ble_floorplan/get_floorplan`, `ble_floorplan/subscribe` (plan and live positions), `ble_floorplan/set_scanner` (move a scanner, set its height), `ble_floorplan/set_floorplan`, `ble_floorplan/import` (the configuration of the earlier dashboard card plus its saved scanner positions).
- Lovelace card `custom:ble-floorplan-card`, served by the integration and registered as a dashboard resource: draws the plan with the live positions, rotation, three label switches, tooltips with distances, distance circles for the selected tracker, drag scanners into place and set their heights (admins).
