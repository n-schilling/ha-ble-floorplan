"""WebSocket commands: the card reads the plan and the positions, admins change the plan."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import probatio

from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util.hass_dict import HassKey

from .catalog import (
    LayoutProblem,
    add_scanner,
    add_tracker,
    candidates,
    layout_yaml,
    remove_scanner,
    remove_tracker,
    scanner_names,
    with_areas,
    with_layout,
)
from .const import (
    DOMAIN,
    WS_ADD_SCANNER,
    WS_ADD_TRACKER,
    WS_CALIBRATION_APPLY,
    WS_CALIBRATION_DELETE,
    WS_CALIBRATION_LIST,
    WS_CALIBRATION_SOLVE,
    WS_CALIBRATION_START,
    WS_CALIBRATION_STOP,
    WS_CANDIDATES,
    WS_GET_FLOORPLAN,
    WS_GET_LAYOUT,
    WS_HISTORY,
    WS_REMOVE_SCANNER,
    WS_REMOVE_TRACKER,
    WS_SET_FLOORPLAN,
    WS_SET_LAYOUT,
    WS_SET_SCANNER,
    WS_SET_SETTINGS,
    WS_SET_TRACKER,
    WS_SUBSCRIBE,
)
from .history import to_wire
from .model import (
    NUMBER,
    Floorplan,
    replace_scanner,
    with_calibration,
    with_pair_offsets,
    with_scanner_position,
    with_settings,
)
from .solver import CalibrationError, solve

if TYPE_CHECKING:
    from . import RuntimeData

DATA_WEBSOCKET: HassKey[bool] = HassKey(f"{DOMAIN}_websocket")
# The subscriptions' rebind callbacks: a reload of the entry replaces the
# coordinator and the stores, and every subscription follows to the new ones
DATA_SUBSCRIPTIONS: HassKey[set[Callable[[RuntimeData], None]]] = HassKey(f"{DOMAIN}_subscriptions")

ERR_NOT_LOADED = "not_loaded"
ERR_NOT_FOUND = "not_found"
ERR_INVALID = "invalid_format"
ERR_RUNNING = "calibration_running"
ERR_NOT_RUNNING = "no_calibration"
ERR_CALIBRATION = "calibration_failed"


@callback
def async_rebind_subscriptions(hass: HomeAssistant, runtime: RuntimeData) -> None:
    """Point every subscription at the entry just set up, with a fresh snapshot."""
    for rebind in list(hass.data.get(DATA_SUBSCRIPTIONS, ())):
        rebind(runtime)


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands once."""
    if DATA_WEBSOCKET in hass.data:
        return
    hass.data[DATA_WEBSOCKET] = True
    hass.data[DATA_SUBSCRIPTIONS] = set()
    async_register_command(hass, ws_get_floorplan)
    async_register_command(hass, ws_subscribe)
    async_register_command(hass, ws_set_scanner)
    async_register_command(hass, ws_set_tracker)
    async_register_command(hass, ws_set_settings)
    async_register_command(hass, ws_set_floorplan)
    async_register_command(hass, ws_candidates)
    async_register_command(hass, ws_add_scanner)
    async_register_command(hass, ws_add_tracker)
    async_register_command(hass, ws_remove_scanner)
    async_register_command(hass, ws_remove_tracker)
    async_register_command(hass, ws_get_layout)
    async_register_command(hass, ws_set_layout)
    async_register_command(hass, ws_calibration_start)
    async_register_command(hass, ws_calibration_stop)
    async_register_command(hass, ws_calibration_list)
    async_register_command(hass, ws_calibration_delete)
    async_register_command(hass, ws_calibration_solve)
    async_register_command(hass, ws_calibration_apply)
    async_register_command(hass, ws_history)


def _runtime(hass: HomeAssistant) -> RuntimeData | None:
    """Return the runtime data of the loaded entry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            data: RuntimeData = entry.runtime_data
            return data
    return None


def _positions(runtime: RuntimeData) -> dict[str, Any]:
    return {key: p.as_dict() for key, p in runtime.coordinator.data.items()}


def _snapshot(runtime: RuntimeData) -> dict[str, Any]:
    return {
        "floorplan": runtime.store.plan.as_dict(),
        "positions": _positions(runtime),
        "calibration": runtime.calibration.as_event(),
    }


@websocket_command({probatio.Required("type"): WS_GET_FLOORPLAN})
@callback
def ws_get_floorplan(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the floor plan and the current positions."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    connection.send_result(msg["id"], _snapshot(runtime))


@websocket_command({probatio.Required("type"): WS_SUBSCRIBE})
@callback
def ws_subscribe(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the plan, the positions and the runs now, then every change of any of them.

    A reload of the entry sends a fresh snapshot of the new one.
    """
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    removers: list[CALLBACK_TYPE] = []

    @callback
    def _send(event: dict[str, Any]) -> None:
        connection.send_message(event_message(msg["id"], event))

    @callback
    def _unbind() -> None:
        for remove in removers:
            remove()
        removers.clear()

    @callback
    def _bind(runtime: RuntimeData) -> None:
        _unbind()

        @callback
        def _send_positions() -> None:
            event: dict[str, Any] = {"positions": _positions(runtime)}
            # The sample counts of a going run grow with every refresh
            if runtime.calibration.active is not None:
                event["calibration"] = runtime.calibration.as_event()
            _send(event)

        removers.append(runtime.coordinator.async_add_listener(_send_positions))
        removers.append(
            runtime.store.async_add_listener(
                lambda: _send({"floorplan": runtime.store.plan.as_dict()})
            )
        )
        removers.append(
            runtime.calibration.async_add_listener(
                lambda: _send({"calibration": runtime.calibration.as_event()})
            )
        )
        _send(_snapshot(runtime))

    @callback
    def _unsubscribe() -> None:
        hass.data[DATA_SUBSCRIPTIONS].discard(_bind)
        _unbind()

    hass.data[DATA_SUBSCRIPTIONS].add(_bind)
    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])
    _bind(runtime)


PAIRS = {cv.string: probatio.Any(None, NUMBER)}


def _check_pairs(plan: Floorplan, keys: Any, lookup: Any, what: str) -> str | None:
    """Return the first unknown key of a pair table, or None."""
    return next((f"no {what} {key}" for key in keys if lookup(key) is None), None)


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_SET_SCANNER,
        probatio.Required("key"): cv.string,
        probatio.Optional("x"): NUMBER,
        probatio.Optional("y"): NUMBER,
        probatio.Optional("z"): NUMBER,
        probatio.Optional("rssi_offset"): NUMBER,
        probatio.Optional("pair_offsets"): PAIRS,
    }
)
@async_response
async def ws_set_scanner(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Change a scanner: position, height, offset, its pairs; what is not given stays."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    plan = runtime.store.plan
    if (scanner := plan.scanner(msg["key"])) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no scanner {msg['key']}")
        return
    pairs = msg.get("pair_offsets", {})
    if (problem := _check_pairs(plan, pairs, plan.tracker, "tracker")) is not None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, problem)
        return
    changed = with_scanner_position(
        scanner, msg.get("x", scanner.x), msg.get("y", scanner.y), msg.get("z")
    )
    if "rssi_offset" in msg:
        changed = replace(changed, rssi_offset=msg["rssi_offset"])
    plan = replace_scanner(plan, changed)
    if pairs:
        plan = with_pair_offsets(plan, scanner.key, pairs)
    await runtime.store.async_save(plan)
    connection.send_result(
        msg["id"],
        {**changed.as_dict(), "pair_offsets": dict(plan.pair_offsets.get(scanner.key, {}))},
    )


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_SET_TRACKER,
        probatio.Required("key"): cv.string,
        probatio.Optional("height"): NUMBER,
        probatio.Optional("ref_power"): probatio.Any(None, NUMBER),
        probatio.Optional("pair_offsets"): PAIRS,
    }
)
@async_response
async def ws_set_tracker(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Change a tracker: height, reference power (null for the default), its pairs per scanner."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    plan = runtime.store.plan
    if (tracker := plan.tracker(msg["key"])) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no tracker {msg['key']}")
        return
    pairs = msg.get("pair_offsets", {})
    if (problem := _check_pairs(plan, pairs, plan.scanner, "scanner")) is not None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, problem)
        return
    changed = tracker
    if "height" in msg:
        changed = replace(changed, height=msg["height"])
    if "ref_power" in msg:
        changed = replace(changed, ref_power=msg["ref_power"])
    plan = replace(
        plan, trackers=tuple(changed if t.key == tracker.key else t for t in plan.trackers)
    )
    for scanner_key, value in pairs.items():
        plan = with_pair_offsets(plan, scanner_key, {tracker.key: value})
    await runtime.store.async_save(plan)
    connection.send_result(
        msg["id"],
        {
            **changed.as_dict(),
            "pair_offsets": {
                scanner_key: ts[tracker.key]
                for scanner_key, ts in plan.pair_offsets.items()
                if tracker.key in ts
            },
        },
    )


@require_admin
@websocket_command(
    {probatio.Required("type"): WS_SET_SETTINGS, probatio.Required("settings"): dict}
)
@async_response
async def ws_set_settings(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Change some of the settings; the others stay. No reload."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    try:
        plan = with_settings(runtime.store.plan, msg["settings"])
    except probatio.Invalid as err:
        connection.send_error(msg["id"], ERR_INVALID, str(err))
        return
    await runtime.store.async_save(plan)
    connection.send_result(msg["id"], plan.settings.as_dict())


async def _async_replace(hass: HomeAssistant, runtime: RuntimeData, plan: Floorplan) -> None:
    """Save a new plan and reload the entry, so the entities follow the trackers."""
    await runtime.store.async_save(plan)
    assert runtime.coordinator.config_entry is not None
    hass.config_entries.async_schedule_reload(runtime.coordinator.config_entry.entry_id)


@require_admin
@websocket_command(
    {probatio.Required("type"): WS_SET_FLOORPLAN, probatio.Required("floorplan"): dict}
)
@async_response
async def ws_set_floorplan(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Replace the whole floor plan."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    try:
        plan = with_areas(hass, Floorplan.from_dict(msg["floorplan"]))
    except (probatio.Invalid, LayoutProblem) as err:
        connection.send_error(msg["id"], ERR_INVALID, str(err))
        return
    await _async_replace(hass, runtime, plan)
    connection.send_result(msg["id"], plan.as_dict())


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_CALIBRATION_START,
        probatio.Required("tracker"): cv.string,
        probatio.Required("x"): NUMBER,
        probatio.Required("y"): NUMBER,
        probatio.Optional("height"): NUMBER,
    }
)
@async_response
async def ws_calibration_start(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Start a calibration run: the tracker sits at x, y, at the height given or its own."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    if (tracker := runtime.store.plan.tracker(msg["tracker"])) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no tracker {msg['tracker']}")
        return
    if runtime.calibration.active is not None:
        connection.send_error(msg["id"], ERR_RUNNING, "a calibration run is going")
        return
    height = msg.get("height", tracker.height)
    run = await runtime.coordinator.async_start_calibration(tracker.key, msg["x"], msg["y"], height)
    connection.send_result(msg["id"], run.summary())


@require_admin
@websocket_command({probatio.Required("type"): WS_CALIBRATION_STOP})
@async_response
async def ws_calibration_stop(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stop the calibration run that is going."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    if runtime.calibration.active is None:
        connection.send_error(msg["id"], ERR_NOT_RUNNING, "no calibration run is going")
        return
    run = await runtime.coordinator.async_stop_calibration()
    connection.send_result(msg["id"], run.summary())


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_CALIBRATION_LIST,
        probatio.Optional("samples", default=False): cv.boolean,
    }
)
@callback
def ws_calibration_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the runs: their summaries, or with every sample when asked."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    result = runtime.calibration.as_event()
    if msg["samples"]:
        result["runs"] = [run.as_dict() for run in runtime.calibration.runs]
    connection.send_result(msg["id"], result)


@require_admin
@websocket_command(
    {probatio.Required("type"): WS_CALIBRATION_DELETE, probatio.Required("run_id"): cv.string}
)
@async_response
async def ws_calibration_delete(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a run."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    if not await runtime.calibration.async_delete(msg["run_id"]):
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no run {msg['run_id']}")
        return
    connection.send_result(msg["id"], runtime.calibration.as_event())


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_CALIBRATION_SOLVE,
        probatio.Optional("attenuation", default=False): cv.boolean,
    }
)
@callback
def ws_calibration_solve(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the proposal from all finished runs; nothing is written."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    try:
        proposal = solve(runtime.store.plan, runtime.calibration.runs, msg["attenuation"])
    except CalibrationError as err:
        connection.send_error(msg["id"], ERR_CALIBRATION, str(err))
        return
    connection.send_result(msg["id"], proposal)


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_CALIBRATION_APPLY,
        probatio.Optional("attenuation"): NUMBER,
        probatio.Optional("trackers", default=dict): {cv.string: NUMBER},
        probatio.Optional("scanners", default=dict): {cv.string: NUMBER},
        probatio.Optional("pairs", default=dict): {cv.string: {cv.string: NUMBER}},
    }
)
@async_response
async def ws_calibration_apply(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Write the values given into the plan and reload the entry."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    if runtime.calibration.active is not None:
        connection.send_error(msg["id"], ERR_RUNNING, "stop the calibration run first")
        return
    try:
        plan = with_calibration(
            runtime.store.plan,
            msg.get("attenuation"),
            msg["trackers"],
            msg["scanners"],
            msg["pairs"],
        )
    except LookupError as err:
        connection.send_error(msg["id"], ERR_NOT_FOUND, str(err))
        return
    await _async_replace(hass, runtime, plan)
    connection.send_result(msg["id"], plan.as_dict())


@require_admin
@websocket_command({probatio.Required("type"): WS_CANDIDATES})
@callback
def ws_candidates(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the scanners and the trackable devices that are not on the plan yet."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    connection.send_result(msg["id"], candidates(hass, runtime.store.plan))


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_ADD_SCANNER,
        probatio.Required("source"): cv.string,
        probatio.Optional("name"): cv.string,
        probatio.Optional("z", default=1.0): NUMBER,
    }
)
@async_response
async def ws_add_scanner(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Put a scanner of Home Assistant on the plan, in the middle; it is moved from there."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    source = msg["source"].upper()
    plan = runtime.store.plan
    if any(s.source == source for s in plan.scanners):
        connection.send_error(msg["id"], ERR_INVALID, f"scanner {source} is on the plan")
        return
    name = msg.get("name") or scanner_names(hass).get(source)
    if name is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no scanner {source}")
        return
    plan, scanner = add_scanner(plan, source, name, msg["z"])
    await runtime.store.async_save(plan)
    connection.send_result(msg["id"], scanner.as_dict())


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_ADD_TRACKER,
        probatio.Exclusive("address", "tracker"): cv.string,
        probatio.Exclusive("device_id", "tracker"): cv.string,
        probatio.Required("name"): cv.string,
        probatio.Optional("height", default=1.0): NUMBER,
    }
)
@async_response
async def ws_add_tracker(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Put a device on the plan as a tracker; the entry reloads for its sensors."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    address = msg.get("address")
    device_id = msg.get("device_id")
    plan = runtime.store.plan
    if (address is None) == (device_id is None):
        connection.send_error(msg["id"], ERR_INVALID, "give address or device_id")
        return
    if any(
        (address and t.address == address.upper()) or (device_id and t.device_id == device_id)
        for t in plan.trackers
    ):
        connection.send_error(msg["id"], ERR_INVALID, "the device is on the plan")
        return
    try:
        plan, tracker = add_tracker(plan, msg["name"], address, device_id, msg["height"])
        plan = Floorplan.from_dict(plan.as_dict())
    except probatio.Invalid as err:
        connection.send_error(msg["id"], ERR_INVALID, str(err))
        return
    await _async_replace(hass, runtime, plan)
    connection.send_result(msg["id"], tracker.as_dict())


@require_admin
@websocket_command(
    {probatio.Required("type"): WS_REMOVE_SCANNER, probatio.Required("key"): cv.string}
)
@async_response
async def ws_remove_scanner(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Take a scanner off the plan, with its pair corrections."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    if runtime.store.plan.scanner(msg["key"]) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no scanner {msg['key']}")
        return
    await runtime.store.async_save(remove_scanner(runtime.store.plan, msg["key"]))
    connection.send_result(msg["id"])


@require_admin
@websocket_command(
    {probatio.Required("type"): WS_REMOVE_TRACKER, probatio.Required("key"): cv.string}
)
@async_response
async def ws_remove_tracker(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Take a tracker off the plan; the entry reloads and removes its sensors."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    if runtime.store.plan.tracker(msg["key"]) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no tracker {msg['key']}")
        return
    await _async_replace(hass, runtime, remove_tracker(runtime.store.plan, msg["key"]))
    connection.send_result(msg["id"])


@require_admin
@websocket_command({probatio.Required("type"): WS_GET_LAYOUT})
@callback
def ws_get_layout(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the rooms and openings as YAML."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    connection.send_result(msg["id"], {"yaml": layout_yaml(runtime.store.plan)})


@require_admin
@websocket_command({probatio.Required("type"): WS_SET_LAYOUT, probatio.Required("yaml"): str})
@async_response
async def ws_set_layout(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Replace the rooms and openings from YAML; scanners, trackers and settings stay."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    try:
        plan = with_areas(hass, with_layout(runtime.store.plan, msg["yaml"]))
    except LayoutProblem as err:
        connection.send_error(msg["id"], ERR_INVALID, str(err))
        return
    await runtime.store.async_save(plan)
    connection.send_result(msg["id"], {"yaml": layout_yaml(plan)})


@require_admin
@websocket_command({probatio.Required("type"): WS_HISTORY, probatio.Required("day"): cv.date})
@async_response
async def ws_history(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the tracks of one day (UTC) and the days there are.

    A point is [unix time, x, y, room]; x and y are null while the tracker is
    not seen. Between two points the tracker stayed where the first one says.
    """
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    day = msg["day"].isoformat()
    tracks = await runtime.history.async_day(day)
    connection.send_result(
        msg["id"], {"day": day, "days": runtime.history.days, "tracks": to_wire(tracks)}
    )
