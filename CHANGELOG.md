# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.0] - 2026-10-22

### Added

- Walls: the shown position passes a wall only through an opening of the plan. A step that would cross a wall heads for the door of its room that lies best on the way to the measured position and goes through it; in a room without a door the position stops before the wall. Setting `walls` (on by default), switchable in the card.
- Screenshots in the README, rendered from the example flat of the tests; a privacy test makes sure every image in the repository carries pixels only.

### Changed

- Number fields of the card show their values in the language of Home Assistant and take a point or a comma as the decimal sign.
- The distance circles stay inside the map of the card.

## [0.4.0] - 2026-10-22

### Added

- WebSocket `ble_floorplan/set_tracker` (`key`, `height`, `ref_power` or null for the default, `pair_offsets` per scanner, null removes a pair) and `ble_floorplan/set_settings` (`settings`: the values to change; the rest stays). Neither reloads the entry.
- `ble_floorplan/set_scanner` takes `rssi_offset` and `pair_offsets` per tracker as well; `x` and `y` are optional now and stay as they are when left out.

### Changed

- The card is the plan: tapping a tracker or a scanner opens its panel with the details and, for admins, the actions. The tracker panel edits height, reference power and pair corrections and starts a calibration run (tap the plan for the true position); the scanner panel moves the scanner and edits position, height, offset and pair corrections. The gear opens the settings in sections (display, engine, motion, rooms, robust weights) and the calibration with the runs, the proposal and apply. The table under the plan and the header buttons are gone; rotation and labels are set on the card.
- The visual editor of the card offers the title only. `rotation` and `show_*` in the card configuration still work as defaults.

## [0.3.0] - 2026-10-22

### Added

- Motion rules for the shown position, all in the settings: `max_speed` (1.5 m/s) caps how fast it moves; a raw position farther than `jump_distance` (2 m) away is followed only once it stayed there for `jump_confirm_seconds` (3 s), meanwhile the position holds; the step after a confirmed jump is as large as if it had been followed all along.
- Room hysteresis: the *Room* sensor changes only after the position lay in another room for `room_hold_seconds` (5 s) and at least `room_margin` (0.3 m) away from that room's walls the whole time.
- Robust weights in the trilateration: with four or more scanners, a scanner whose distance the others contradict by more than `robust_residual` (1 m), while they agree with each other, loses weight in proportion to the square of the miss. Three scanners leave no way to tell which one is wrong and stay as they were.

### Changed

- All four rules are on by default; 0 switches each off (`jump_distance`, `max_speed`, `robust_residual`, `room_hold_seconds` and `room_margin`).

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
