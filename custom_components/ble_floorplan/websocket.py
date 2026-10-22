"""WebSocket commands: the card reads the plan and the positions, admins change the plan."""

from __future__ import annotations

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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util.hass_dict import HassKey

from .const import (
    DOMAIN,
    WS_GET_FLOORPLAN,
    WS_IMPORT,
    WS_SET_FLOORPLAN,
    WS_SET_SCANNER,
    WS_SUBSCRIBE,
)
from .importer import ImportProblem, build_floorplan
from .model import NUMBER, Floorplan, replace_scanner, with_scanner_position

if TYPE_CHECKING:
    from . import RuntimeData

DATA_WEBSOCKET: HassKey[bool] = HassKey(f"{DOMAIN}_websocket")

ERR_NOT_LOADED = "not_loaded"
ERR_NOT_FOUND = "not_found"
ERR_INVALID = "invalid_format"
ERR_IMPORT = "import_failed"

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
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands once."""
    if DATA_WEBSOCKET in hass.data:
        return
    hass.data[DATA_WEBSOCKET] = True
    async_register_command(hass, ws_get_floorplan)
    async_register_command(hass, ws_subscribe)
    async_register_command(hass, ws_set_scanner)
    async_register_command(hass, ws_set_floorplan)
    async_register_command(hass, ws_import)


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
    return {"floorplan": runtime.store.plan.as_dict(), "positions": _positions(runtime)}


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
    """Send the plan and the positions now, then every change of either."""
    if (runtime := _runtime(hass)) is None:
        connection.send_error(msg["id"], ERR_NOT_LOADED, "BLE Floorplan is not set up")
        return

    @callback
    def _send_positions() -> None:
        connection.send_message(event_message(msg["id"], {"positions": _positions(runtime)}))

    @callback
    def _send_floorplan() -> None:
        connection.send_message(
            event_message(msg["id"], {"floorplan": runtime.store.plan.as_dict()})
        )

    remove_positions = runtime.coordinator.async_add_listener(_send_positions)
    remove_floorplan = runtime.store.async_add_listener(_send_floorplan)

    @callback
    def _unsubscribe() -> None:
        remove_positions()
        remove_floorplan()

    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])
    connection.send_message(event_message(msg["id"], _snapshot(runtime)))


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
