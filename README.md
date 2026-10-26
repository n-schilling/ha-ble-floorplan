# BLE Floorplan for Home Assistant

[![Release](https://img.shields.io/github/v/release/n-schilling/ha-ble-floorplan)](https://github.com/n-schilling/ha-ble-floorplan/releases)
[![CI](https://github.com/n-schilling/ha-ble-floorplan/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/n-schilling/ha-ble-floorplan/actions/workflows/ci.yaml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

BLE Floorplan places Bluetooth Low Energy trackers on a floor plan of your home. It takes the signal strength that every Bluetooth scanner of Home Assistant reports for a tracker, turns it into distances and computes a position by trilateration. Each tracker gets a *Room* sensor, its coordinates and a presence tracker, and a dashboard card shows the plan with the trackers moving live.

![The card: two trackers walk through the doors of a flat, the panel follows the tag](https://raw.githubusercontent.com/n-schilling/ha-ble-floorplan/main/docs/images/overview.gif)

*All images show a made-up example flat with made-up devices, rendered from the test data of this repository.*

## Features

- **Works with every scanner Home Assistant has:** the Bluetooth adapter of the machine, [ESPHome Bluetooth proxies](https://esphome.io/components/bluetooth_proxy.html) and Shelly devices acting as proxies. The integration reads the raw advertisements from Home Assistant's Bluetooth stack and needs nothing else.
- **Phones and watches included:** devices set up with [Private BLE Device](https://www.home-assistant.io/integrations/private_ble_device/) change their address every few minutes; BLE Floorplan follows whatever address they currently use. Tags and beacons with a fixed address work as they are.
- **A position, not only the nearest scanner:** distances from all scanners go into a weighted least-squares fit, with the heights of scanners and trackers taken into account.
- **Calm, plausible movement:** smoothing, a speed limit, a confirmation for jumps and walls that can only be passed through doors keep trackers from hopping across the plan. Rooms change only after a hold time.
- **Calibration on your own data:** record a tracker at a few known places, and a least-squares fit proposes the reference power of every tracker, the offset of every scanner and a correction per pair of scanner and tracker. Nothing is applied until you say so.
- **Timeline:** drag back to any moment of the last days, or let it play, and the trackers move on the plan as they did, with the way behind them. Off until you set how many days to keep.
- **Everything in the card:** draw the floor plan, add scanners and trackers, move scanners, tune the settings and run the calibration from the dashboard, without YAML files or developer tools.
- **Home Assistant native:** rooms link to areas, presence works with persons, and an *Active scanners* sensor tells you when a scanner goes quiet.
- **Local only:** no cloud, no network access of its own. All data stays in Home Assistant's storage.

## Requirements

- Home Assistant 2026.10 or newer with the Bluetooth integration.
- At least two scanners that see the trackers; three or more spread over the home give useful positions, four or more let the integration spot a scanner that disagrees with the others.
- Trackers that advertise often: a tag or beacon with a fixed address, or a phone or watch set up as a Private BLE Device.

## Installation

1. In HACS: **⋮ → Custom repositories**, add `https://github.com/n-schilling/ha-ble-floorplan` as type **Integration**.
2. Install **BLE Floorplan** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → BLE Floorplan**. There is nothing to fill in.
4. Add the card `custom:ble-floorplan-card` to a dashboard. The integration registers the card as a dashboard resource by itself.

## Getting started

Everything is done in the card, as an administrator, from the gear (⚙). While the plan is empty, the gear opens with the floor plan, the scanners and the trackers.

![Setting up: the floor plan as YAML, adding scanners and trackers](https://raw.githubusercontent.com/n-schilling/ha-ble-floorplan/main/docs/images/setup.png)

1. **Draw the floor plan.** The text field starts with a template of two rooms and a door. Replace it with your rooms in metres, with the origin at the top left corner: rectangles with `x`, `y`, `w`, `h` or polygons with `points`, plus zones, outdoor areas and the doors as `openings`. Then **Save**. A mistake comes back as a message and nothing is saved. [The floor plan](#the-floor-plan) lists every option.
2. **Add the scanners.** The list offers every Bluetooth scanner Home Assistant knows. Choose one, set the height it is mounted at and **Add**. It lands in the middle of the plan: tap it, **Move**, drag it to its place and **Save**.
3. **Add the trackers.** The list offers the Private BLE Devices and the devices with a fixed Bluetooth address. Choose one, give it a name and the height it is usually carried at, then **Add**. Its sensors appear right away.
4. **Calibrate.** Put each tracker at a few known places and record a [calibration run](#calibration) each time, then compute and apply the proposal. Without calibration the positions are rough.
5. **Tune if needed.** The defaults of the [settings](#settings) suit a flat.

A scanner or a tracker is taken off the plan with the ✕ next to it in the same lists.

## The card

The card is the plan. Hovering a scanner or a tracker shows its distances and signal strengths; tapping it opens its panel next to the plan. The buttons at the top rotate the plan, switch the labels of rooms, scanners and trackers, open the timeline and open the gear (the last two for administrators only).

| Tracker panel with the distance circles | Scanner panel |
|---|---|
| ![Tracker panel](https://raw.githubusercontent.com/n-schilling/ha-ble-floorplan/main/docs/images/tracker.png) | ![Scanner panel](https://raw.githubusercontent.com/n-schilling/ha-ble-floorplan/main/docs/images/scanner.png) |

- **Tracker panel:** room, position, the distance and signal strength at every scanner, height, reference power and pair corrections. Administrators edit those values, show the distance circles and start a calibration run from here.
- **Scanner panel:** position, height, offset, what the scanner hears from every tracker and its pair corrections. Administrators move the scanner and edit its values.
- **Gear:** sections that fold, for the floor plan, the scanners, the trackers, the display (rotation and labels, kept per browser), the settings and the calibration.
- **Timeline** (the clock, once *Days kept* is above 0): a bar next to the plan with newer moments at the top and a bar per tracker where it was seen. Drag it up to go back, tap it to jump to a moment, scroll with the mouse wheel, zoom with − and + from minutes to days. ▶ plays from the moment shown at the speed chosen, *Back to live* returns. The trackers on the plan show where they were then, with their way over the two minutes before.

```yaml
type: custom:ble-floorplan-card
title: Home            # optional
rotation: 90           # optional default: 0, 90, 180 or 270
show_room_labels: true
show_scanner_labels: true
show_tracker_labels: true
```

The visual editor offers the title; rotation and labels are set on the card itself. Numbers are shown in the language of Home Assistant, and a point and a comma are both taken as the decimal sign.

## Entities

Each tracker becomes a device with these entities:

| Entity | Description |
|---|---|
| Room (`sensor`) | The room the tracker is in, unknown while no scanner sees it or the room has no name. Attributes: `x`, `y` in metres, `nearest_scanner`, `scanner_count`, `distances` (the floor distance to every scanner, null when not seen) and `area_id`. The recorder keeps the room and `area_id` only; the other attributes change with every advertisement, the timeline keeps the way. |
| Position X, Position Y (`sensor`, diagnostic) | The coordinates on the plan in metres, rounded to a decimetre. |
| Presence (`device_tracker`) | `home` while a scanner of the plan saw the tracker within `away_seconds`, `not_home` after that. Right after a start of Home Assistant it stays unknown until the tracker is seen or `away_seconds` passed, so a restart does not look like leaving home. Assign it to a person in **Settings → People**. |

The integration's own device *BLE Floorplan* carries **Active scanners** (`sensor`): the number of scanners of the plan that received anything within the last minute, with the names of the active and inactive ones as attributes. Use it to get notified when a scanner fails.

### Rooms and areas

A room of the plan can stand for an area of Home Assistant. Give it `area` with the area's id or name; an area Home Assistant does not know is refused when the plan is saved. The *Room* sensor then carries the area as `area_id`, so automations can work with areas:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.phone_room
actions:
  - action: light.turn_on
    target:
      area_id: "{{ state_attr('sensor.phone_room', 'area_id') }}"
```

The *Room* sensor changes only after the room hold time, so it suits "who is where" better than switching lights the moment someone walks in. A motion sensor is quicker for that.

## Calibration

Every scanner hears every tracker a little differently: an adapter may hear a tag as loud as a proxy does, and a phone 15 dB louder. One reference power per tracker and one offset per scanner cannot express that. The calibration therefore records each tracker at known places and fits all of it at once.

1. In the card, tap the tracker and choose **Calibration run**. Set the tracker's height for this run, tap the plan where it lies and **Start run**. Leave it there for a minute or two, then **Stop run**. While the run goes, a crosshair marks the true position and the panel counts the samples per scanner.

   ![A calibration run](https://raw.githubusercontent.com/n-schilling/ha-ble-floorplan/main/docs/images/measure.png)

2. Repeat at other places and with the other trackers. A scanner needs at least three samples in a run to count. Fitting the exponent needs runs at different distances from a scanner.
3. In the gear, open **Calibration** and **Compute**. The proposal lists the current and the proposed value of every parameter, the runs and samples behind it, and the error before and after.

   ![The calibration proposal](https://raw.githubusercontent.com/n-schilling/ha-ble-floorplan/main/docs/images/calibration.png)

4. **Apply** writes the proposal into the plan. Nothing is applied by itself; a proposal you do not like is simply not applied.

How the fit works: for each run and scanner, the median signal strength is one observation, and its true distance follows from the positions and heights of the run and the scanner. A least-squares fit over `rssi = ref_power + rssi_offset - 10 * attenuation * log10(distance)` gives the reference power of every tracker and the offset of every scanner. The offsets are made to average zero, because only the sum of a tracker's and a scanner's value can be observed. What the fit leaves per pair of scanner and tracker becomes the pair's correction. With runs of one tracker only, the differences between the scanners all land in the offsets and then apply to every tracker, so calibrate every tracker you care about.

The runs are kept in `.storage/ble_floorplan.calibration`.

## Settings

All settings are in the gear of the card. Setting a value to 0 switches a rule off where noted.

| Setting | Default | Meaning |
|---|---|---|
| Path loss exponent (`attenuation`) | 3.0 | How fast the signal weakens with distance. |
| Default reference power (`ref_power_default`) | −55 dBm | Signal strength at one metre for trackers without their own value. |
| Largest distance (`max_distance`) | 15 m | Scanners farther away are ignored for the position. |
| Smoothing (`smoothing_seconds`) | 20 s | Time constant of the smoothing of the shown position. |
| Dead zone (`min_move`) | 0.25 m | Smaller moves are ignored. |
| Keep trackers in the rooms (`clamp`) | on | A position outside every room moves to the closest wall. |
| Outdoor areas count as rooms (`clamp_outdoor`) | off | Lets trackers stay on balconies and terraces. |
| Top speed (`max_speed`) | 1.5 m/s | The shown position never moves faster; 0 is off. |
| Jump distance (`jump_distance`) | 2 m | A measured position this far away counts as a jump; 0 is off. |
| Jump confirmation (`jump_confirm_seconds`) | 3 s | A jump is followed only after it stayed that long. |
| Through walls only at doors (`walls`) | on | The shown position passes walls only through openings. |
| Away after (`away_seconds`) | 120 s | Presence turns `not_home` after this long without a sighting. |
| Hold time (`room_hold_seconds`) | 5 s | The room changes only after this long in the new room. |
| Wall margin (`room_margin`) | 0.3 m | ... and at least this far from the new room's walls; 0 is off. |
| Residual (`robust_residual`) | 1 m | With four or more scanners, a scanner the others contradict by more loses weight; 0 is off. |
| Days kept (`history_days`) | 0 | Days the timeline keeps, at most 30; 0 records nothing and deletes what was kept. |

## The floor plan

The floor plan is edited as YAML in the gear. Everything is in metres; the origin is the top left corner and y grows downwards.

```yaml
rooms:
  - name: Living room          # a rectangle
    area: living_room          # optional: the area of Home Assistant, by id or name
    x: 0
    y: 0
    w: 6
    h: 5
  - name: Bedroom              # a polygon
    points: [[0, 5], [6, 5], [6, 9], [2, 9], [2, 8], [0, 8]]
  - name: Dining               # a zone inside a room: dashed, and wins when a tracker lies in it
    x: 3
    y: 0
    w: 3
    h: 2.5
    zone: true
  - name: Balcony              # outdoors: dashed, trackers are kept out unless clamp_outdoor is on
    x: 0
    y: 9
    w: 10
    h: 2
    outdoor: true
openings:                      # doors and open passages, as a line on a wall
  - [6, 1, 6, 2.5]
```

Room labels also take `lx`, `ly` (position), `fs` (font size), `rot` (rotation) and `label: false`. Of overlapping rooms the one drawn last wins; zones win over the rooms they lie in. Walls are the outlines of the rooms; a tracker passes them only where an opening lies on them, so add every door and open passage.

## How it works

1. **Signals.** Every second, for each tracker, the newest advertisement of every scanner that sees it is read: its signal strength (RSSI) and the time the scanner saw it. Per scanner, the RSSI is the median of the last 10 s; an advertisement older than 30 s counts as not seen.
2. **Distances.** The RSSI becomes a distance with the log-distance path loss model, `d = 10^((ref_power + rssi_offset + pair_offset - rssi) / (10 * attenuation))`, and is projected onto the floor with the heights of scanner and tracker.
3. **Position.** The distances of the scanners within reach go into a weighted Gauss-Newton least-squares fit. Near scanners count more, and a position nearer to a scanner than its measured distance costs less than one farther away, because walls make measured distances rather too long. With four or more scanners, one that the others contradict loses weight.
4. **Movement.** The shown position follows the measured one with smoothing, ignores small moves, confirms jumps, keeps to the top speed and passes walls only through doors: a step through a wall heads for the door of its room that lies best on the way instead.
5. **Room and presence.** The room is the room or zone the shown position lies in, and it changes only after the hold time and well inside the new room. Presence is `home` while any scanner saw the tracker within `away_seconds`.
6. **Timeline.** When days are kept, a point goes into a tracker's track when it is seen again or no longer seen, when its room changes, and when it moved 0.3 m and the last point is 2 s old; a tracker at rest adds nothing. Every day (UTC) is a store of its own that starts with where the trackers were at midnight, written a minute after new points; days older than *Days kept* are deleted. A stop of Home Assistant ends every track with a gap, so the time it was down shows as not seen. A busy tracker adds about 10,000 points a day, some 350 kB.

## WebSocket API

The card uses these commands; they are open for scripts and tools as well. Commands marked *admins* need an administrator.

| Command | Who | Description |
|---|---|---|
| `ble_floorplan/get_floorplan` | everyone | Returns `floorplan` and `positions`. |
| `ble_floorplan/subscribe` | everyone | Sends `floorplan`, `positions` and `calibration` now, then an event for every change. |
| `ble_floorplan/get_layout` | admins | Returns `yaml`: the rooms and openings, a template while the plan has none. |
| `ble_floorplan/set_layout` | admins | `yaml`: replaces the rooms and openings; scanners, trackers and settings stay. |
| `ble_floorplan/set_floorplan` | admins | `floorplan`: replaces the whole plan and reloads the entry. |
| `ble_floorplan/candidates` | admins | Returns the `scanners` (`source`, `name`) and `trackers` (`device_id` or `address`, `name`) that are not on the plan yet. |
| `ble_floorplan/add_scanner` | admins | `source`, optionally `name` and `z`: puts a scanner in the middle of the plan. |
| `ble_floorplan/add_tracker` | admins | `device_id` or `address`, `name`, optionally `height`: adds a tracker. |
| `ble_floorplan/remove_scanner` | admins | `key`: takes a scanner off the plan, with its pair corrections. |
| `ble_floorplan/remove_tracker` | admins | `key`: takes a tracker off the plan, with its pair corrections. |
| `ble_floorplan/set_scanner` | admins | `key` and any of `x`, `y`, `z`, `rssi_offset`, `pair_offsets` (`{tracker: dB}`, null removes a pair). |
| `ble_floorplan/set_tracker` | admins | `key` and any of `height`, `ref_power` (null for the default), `pair_offsets` (`{scanner: dB}`). |
| `ble_floorplan/set_settings` | admins | `settings`: the values to change; the others stay. |
| `ble_floorplan/calibration/start` | admins | `tracker`, `x`, `y`, optionally `height`: starts a run (one at a time). |
| `ble_floorplan/calibration/stop` | admins | Stops the run that is going. |
| `ble_floorplan/calibration/list` | admins | Returns the runs with their sample counts; `samples: true` adds every sample. |
| `ble_floorplan/calibration/delete` | admins | `run_id`: deletes a run. |
| `ble_floorplan/calibration/solve` | admins | Optionally `attenuation: true` to fit the exponent too. Returns the proposal; nothing is written. |
| `ble_floorplan/calibration/apply` | admins | `attenuation`, `trackers`, `scanners`, `pairs`, each optional: writes them into the plan. |
| `ble_floorplan/history` | admins | `day` (`YYYY-MM-DD`, UTC): returns `tracks` (`{tracker: [[unix time, x, y, room], …]}`, x and y null while not seen; the first point is where the tracker was at midnight) and the stored `days`. |

Example from a browser console on a dashboard: `await document.querySelector("home-assistant").hass.callWS({type: "ble_floorplan/get_floorplan"})`.

## Limitations

- Indoor signal strength scatters by 10–20 dB with reflections, bodies and orientation. Positions are rough; rooms are right most of the time when the scanners are spread out and the trackers calibrated.
- A corner that no scanner covers places trackers at the nearest wall.
- Uncalibrated trackers get the scanner offsets only, which fit the calibrated trackers best.
- One floor only.

## Privacy

The integration stores the floor plan, the scanners' addresses, the trackers' addresses or device ids the calibration runs (positions in the home and signal strengths) and, when *Days kept* is above 0, the timeline (where every tracker was, for that many days) in Home Assistant's storage. The timeline is a movement profile of the people who carry the trackers; only administrators can read it, and setting *Days kept* to 0 deletes it. It sends nothing anywhere else, and the card talks to Home Assistant only. A test in this repository checks that the code uses no network library, that no real address is in any file and that the images carry no metadata.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy custom_components
.venv/bin/pytest --cov=custom_components.ble_floorplan --cov-report=term-missing
```

## License

Apache License 2.0, see [LICENSE](LICENSE).
