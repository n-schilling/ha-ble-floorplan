# BLE Floorplan for Home Assistant

[![Release](https://img.shields.io/github/v/release/n-schilling/ha-ble-floorplan)](https://github.com/n-schilling/ha-ble-floorplan/releases)
[![CI](https://github.com/n-schilling/ha-ble-floorplan/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/n-schilling/ha-ble-floorplan/actions/workflows/ci.yaml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

A custom integration that places Bluetooth Low Energy trackers on a floor plan of your home. It takes the signal strength every Bluetooth scanner of Home Assistant reports for a tracker, turns it into distances and solves for the position by weighted trilateration. Each tracker gets a *Room* sensor and its position, and a Lovelace card draws the plan with the trackers live.

It reads the raw advertisements from Home Assistant's Bluetooth stack, so it works with every scanner Home Assistant has: the adapter of the machine, [ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy.html) and Shelly devices as proxies. It complements [Bermuda](https://github.com/agittins/bermuda), which assigns a tracker to the area of the nearest scanner; this integration computes a point on the plan, with the scanners' heights and a correction per scanner. [Private BLE Device](https://www.home-assistant.io/integrations/private_ble_device/) resolves the changing addresses of phones and watches; this integration tracks whatever address it currently resolves to.

## How it works

1. Every second, for each tracker, the newest advertisement of every scanner that sees it is read: its RSSI, the scanner's address and the time the scanner saw it. Advertisements older than 30 s count as not seen. Per scanner the RSSI is the median of the samples of the last 10 s.
2. The RSSI becomes a distance with the log-distance path loss model: `d = 10^((ref_power + rssi_offset - rssi) / (10 * attenuation))`. `ref_power` is the RSSI at one metre, per tracker or the global default (−55 dBm); `rssi_offset` is a correction per scanner; `attenuation` is the path loss exponent (3.0 by default). The distance is projected onto the floor with the scanner's height and the tracker's height.
3. The distances of the scanners within `max_distance` go into a weighted Gauss-Newton least-squares solution: near scanners count more (weights 1/d²), and a residual that puts the tracker nearer than measured counts a quarter, because walls make measured distances rather too long. With clamping on, a point outside every room is moved to the closest wall.
4. The position is smoothed with a time constant (`smoothing_seconds`), independent of how often it is computed; moves below `min_move` are ignored. The room is the zone or room the smoothed point lies in; of overlapping rooms the one drawn last wins.

## Requirements

- Home Assistant 2026.10 or newer with the Bluetooth integration and at least two scanners that see the trackers; three or more spread over the home give useful positions.
- Trackers that advertise often: a beacon or a tag with a fixed address, or a phone or watch set up as a Private BLE Device.

## Installation

1. In HACS: **⋮ → Custom repositories**, add `https://github.com/n-schilling/ha-ble-floorplan` as type **Integration**.
2. Install **BLE Floorplan** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → BLE Floorplan**. There is nothing to fill in; the floor plan comes next.
4. Set the floor plan over the WebSocket API (`ble_floorplan/set_floorplan`, see below), or import the configuration of an earlier card with `ble_floorplan/import`. The card registers itself as a dashboard resource; add `custom:ble-floorplan-card` to a dashboard.

## The floor plan

Everything is in metres, the origin is the top left corner of the plan, y grows downwards.

```yaml
rooms:
  - name: Living room          # a rectangle
    x: 0
    y: 0
    w: 6
    h: 5
  - name: Bedroom              # or a polygon
    points: [[0, 5], [6, 5], [6, 9], [2, 9], [2, 8], [0, 8]]
  - name: Dining               # a zone inside a room: dashed, wins when a tracker lies in it
    x: 3
    y: 0
    w: 3
    h: 2.5
    zone: true
  - name: Balcony              # outdoors: dashed, trackers are kept out unless clamp_outdoor
    x: 0
    y: 9
    w: 10
    h: 2
    outdoor: true
openings:                      # doors and passages, drawn as gaps in the walls
  - [6, 1, 6, 2.5]
scanners:
  - key: living
    name: Living room scanner
    source: AA:BB:CC:DD:EE:01   # the address Home Assistant knows the scanner by
    x: 1
    y: 1
    z: 0.8                     # height above the floor
    rssi_offset: 0             # correction of the reference power for this scanner, dB
trackers:
  - key: tag
    name: Tag
    address: AA:BB:CC:DD:EE:10 # a fixed address …
    height: 0.3
    ref_power: -60             # RSSI at one metre; omit for the default
  - key: phone
    name: Phone
    device_id: 1f2e3d…         # … or the device of a Private BLE Device
    height: 1.0
settings:
  attenuation: 3.0
  ref_power_default: -55
  smoothing_seconds: 20
  min_move: 0.25
  max_distance: 15
  clamp: true
  clamp_outdoor: false
```

Room labels take `lx`, `ly` (position), `fs` (font size), `rot` (rotation) and `label: false`.

The addresses of the scanners are those of the Bluetooth devices in **Settings → Devices & services → Bluetooth**; the device id of a Private BLE Device is in the URL of its device page.

## Entities

Each tracker is a device named after the tracker, with:

| Entity | Description |
|---|---|
| Room (`sensor`) | The room the tracker is in; unknown while no scanner sees it. Attributes: `x`, `y` (m), `nearest_scanner`, `scanner_count`, `distances` (floor distance of every scanner in m, null when not seen). |
| Position X, Position Y (`sensor`, diagnostic) | The coordinates on the plan in metres. |

## WebSocket API

| Command | Who | Description |
|---|---|---|
| `ble_floorplan/get_floorplan` | everyone | Returns `floorplan` and `positions`. |
| `ble_floorplan/subscribe` | everyone | Sends `floorplan` and `positions` now, then an event for every change of the positions (`positions`) or the plan (`floorplan`). |
| `ble_floorplan/set_scanner` | admins | `key`, `x`, `y` and optionally `z`: moves a scanner. |
| `ble_floorplan/set_floorplan` | admins | `floorplan`: replaces the whole plan (validated; see above) and reloads the entry. |
| `ble_floorplan/import` | admins | The configuration of the earlier card: `rooms`, `openings`, `scanners` (`key`, `name`, `suffix` of Bermuda's distance sensor or `source`, `default` position, `z`), `trackers` (`prefix` or `key`, `name`, optionally `address`, `device_id` or `entity_id`, `ref_power`, `height`), `positions` (`{key: [x, y]}`), `max_distance`, `smoothing_seconds`, `min_move`, `clamp`, `clamp_outdoor`. Scanners are matched by the name of their Bluetooth device, trackers by `device_tracker.<key>` of a Private BLE Device or a device of that name with a Bluetooth address; a missing `ref_power` takes Bermuda's calibration of the device when it is set. Nothing is written when something cannot be mapped. |

Example from the developer tools or a browser console: `await hass.callWS({type: "ble_floorplan/set_scanner", key: "living", x: 1.2, y: 0.9, z: 0.8})`.

## The card

`custom:ble-floorplan-card` draws the plan, the scanners and the trackers, and lists each tracker's room, nearest scanner and the number of scanners that placed it. Hovering a scanner or a tracker shows the distances and signal strengths; tapping a row shows the distance circles of that tracker. The buttons switch the labels of rooms, scanners and trackers and rotate the plan; both choices are kept per browser. Admins can drag the scanners to their places and set their heights, which the integration stores.

```yaml
type: custom:ble-floorplan-card
title: Home            # optional
rotation: 90           # optional default, 0/90/180/270
show_room_labels: true
show_scanner_labels: true
show_tracker_labels: true
```

The visual editor offers these options. The integration serves the card at `/ble_floorplan/ble-floorplan-card.js` and adds it to the dashboard resources (storage mode) by itself.

## Limitations

- Indoor signal strength scatters by 10–20 dB with reflections, bodies and orientation; the positions are rough, the rooms are right most of the time when the scanners are spread out and calibrated. A corner of the home no scanner covers places trackers at the nearest wall.
- The scanners' response is device specific: two trackers at the same place can differ by 10 dB at the same scanner. A correction per scanner and tracker is planned.
- One floor only.

## Privacy

The integration stores the floor plan, the scanners' addresses and the trackers' addresses or device ids in Home Assistant's storage. It sends nothing anywhere else. The card talks to Home Assistant only.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy custom_components
.venv/bin/pytest --cov=custom_components.ble_floorplan --cov-report=term-missing
```

## License

Apache License 2.0, see [LICENSE](LICENSE).
