"""WebSocket commands: the card reads the plan and the positions, admins change the plan."""

from __future__ import annotations

from collections.abc import Callable
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

from .const import (
    DOMAIN,
    WS_CALIBRATION_APPLY,
    WS_CALIBRATION_DELETE,
    WS_CALIBRATION_LIST,
    WS_CALIBRATION_SOLVE,
    WS_CALIBRATION_START,
    WS_CALIBRATION_STOP,
    WS_GET_FLOORPLAN,
    WS_IMPORT,
    WS_SET_FLOORPLAN,
    WS_SET_SCANNER,
    WS_SUBSCRIBE,
)
from .importer import ImportProblem, build_floorplan
from .model import NUMBER, Floorplan, replace_scanner, with_calibration, with_scanner_position
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
ERR_IMPORT = "import_failed"
ERR_RUNNING = "calibration_running"
ERR_NOT_RUNNING = "no_calibration"
ERR_CALIBRATION = "calibration_failed"

# Keys of the card's configuration that have no meaning on the server
CARD_ONLY_KEYS = (
    "title",
    "positions_entity",
    "rotation",
    "show_room_labels",
    "show_scanner_labels",
    "show_tracker_labels",
)


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
    async_register_command(hass, ws_set_floorplan)
    async_register_command(hass, ws_import)
    async_register_command(hass, ws_calibration_start)
    async_register_command(hass, ws_calibration_stop)
    async_register_command(hass, ws_calibration_list)
    async_register_command(hass, ws_calibration_delete)
    async_register_command(hass, ws_calibration_solve)
    async_register_command(hass, ws_calibration_apply)


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


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_SET_SCANNER,
        probatio.Required("key"): cv.string,
        probatio.Required("x"): NUMBER,
        probatio.Required("y"): NUMBER,
        probatio.Optional("z"): NUMBER,
    }
)
@async_response
async def ws_set_scanner(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Move a scanner, and set its height when given."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    if (scanner := runtime.store.plan.scanner(msg["key"])) is None:
        connection.send_error(msg["id"], ERR_NOT_FOUND, f"no scanner {msg['key']}")
        return
    moved = with_scanner_position(scanner, msg["x"], msg["y"], msg.get("z"))
    await runtime.store.async_save(replace_scanner(runtime.store.plan, moved))
    connection.send_result(msg["id"], moved.as_dict())


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
        plan = Floorplan.from_dict(msg["floorplan"])
    except probatio.Invalid as err:
        connection.send_error(msg["id"], ERR_INVALID, str(err))
        return
    await _async_replace(hass, runtime, plan)
    connection.send_result(msg["id"], plan.as_dict())


@require_admin
@websocket_command(
    {
        probatio.Required("type"): WS_IMPORT,
        probatio.Required("rooms"): [dict],
        probatio.Optional("openings"): [list],
        probatio.Required("scanners"): [dict],
        probatio.Required("trackers"): [dict],
        probatio.Optional("positions"): {cv.string: list},
        probatio.Optional("settings"): dict,
        probatio.Optional("max_distance"): NUMBER,
        probatio.Optional("smoothing_seconds"): NUMBER,
        probatio.Optional("min_move"): NUMBER,
        probatio.Optional("clamp"): cv.boolean,
        probatio.Optional("clamp_outdoor"): cv.boolean,
        **{probatio.Optional(key): object for key in CARD_ONLY_KEYS},
    }
)
@async_response
async def ws_import(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Import the configuration of the earlier card plus the saved scanner positions.

    Replaces the stored floor plan; nothing is written when something cannot
    be mapped.
    """
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return
    try:
        plan = build_floorplan(hass, msg)
    except ImportProblem as err:
        connection.send_error(msg["id"], ERR_IMPORT, str(err))
        return
    except probatio.Invalid as err:
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
