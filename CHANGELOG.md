# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-22

### Added

- One config entry *BLE Floorplan*; the floor plan (rooms, openings), the scanners (position, height, RSSI offset) and the trackers (fixed address or Private BLE Device, height, reference power) live in a versioned store of the integration.
- Position engine: per tracker the RSSI of every scanner from Home Assistant's Bluetooth stack (median of a short window, advertisements older than 30 s count as not seen), distance by the log-distance path loss model, projected onto the floor from the scanner's height, weighted Gauss-Newton trilateration, clamping into the rooms, time-based smoothing with a dead zone, room by polygon.
- Sensors per tracker: *Room* (with position, nearest scanner, scanner count and the distance of every scanner as attributes), *Position X* and *Position Y* (diagnostic).
- WebSocket API: `ble_floorplan/get_floorplan`, `ble_floorplan/subscribe` (plan and live positions), `ble_floorplan/set_scanner` (move a scanner, set its height), `ble_floorplan/set_floorplan`, `ble_floorplan/import` (the configuration of the earlier dashboard card plus its saved scanner positions).
- Lovelace card `custom:ble-floorplan-card`, served by the integration and registered as a dashboard resource: draws the plan with the live positions, rotation, three label switches, tooltips with distances, distance circles for the selected tracker, drag scanners into place and set their heights (admins).
