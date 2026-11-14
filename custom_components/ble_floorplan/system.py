"""The system details of a scanner: what it is and how it is doing.

Secondary to the plan: the type of the device behind the scanner, when it
last started, its Wi-Fi signal and firmware, read from the entities of that
device, and what Home Assistant's Bluetooth knows of the scanner itself:
when it last received anything, how many devices it hears, how it scans and
its connection slots.

Home Assistant gives a remote scanner (an ESPHome proxy, a Shelly) a
Bluetooth device of its own, linked to the device it runs on; the entities
are read from that device. A built-in adapter has only its Bluetooth device.
"""

from __future__ import annotations

from typing import Any

from habluetooth import get_manager

from homeassistant.components.bluetooth import MONOTONIC_TIME, async_current_scanners
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.loader import async_get_loaded_integration

from .const import SCANNER_ACTIVE_SECONDS

# Words in the unique id or translation key of the sensor that says when the device started
_START_WORDS = ("uptime", "restart", "boot", "start")

_NO_VALUE = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _devices(
    hass: HomeAssistant, source: str
) -> tuple[dr.DeviceEntry | None, dr.DeviceEntry | None]:
    """Return the scanner's Bluetooth device and the device it runs on (the same for a built-in adapter)."""
    registry = dr.async_get(hass)
    adapter = next(
        (
            device
            for device in registry.devices
            if any(
                kind == CONNECTION_BLUETOOTH and value.upper() == source
                for kind, value in device.connections
            )
        ),
        None,
    )
    if adapter is None:
        return None, None
    host = registry.async_get(adapter.via_device_id) if adapter.via_device_id else None
    return adapter, host if isinstance(host, dr.DeviceEntry) else adapter


def _integration_name(hass: HomeAssistant, device: dr.DeviceEntry) -> str | None:
    """Return the name of the integration the device belongs to."""
    if (entry := hass.config_entries.async_get_entry(device.config_entry_id)) is None:
        return None
    try:
        return async_get_loaded_integration(hass, entry.domain).name
    except Exception:
        return entry.domain


def _start_entity(entries: list[er.RegistryEntry]) -> er.RegistryEntry | None:
    """Return the sensor that says when the device last started.

    A timestamp sensor named for it (uptime, last restart, …); without one,
    the device's only diagnostic timestamp sensor.
    """
    stamps = [
        e
        for e in entries
        if e.domain == "sensor"
        and (e.device_class or e.original_device_class) == SensorDeviceClass.TIMESTAMP
    ]
    for entry in stamps:
        words = f"{entry.unique_id} {entry.translation_key or ''}".lower()
        if any(w in words for w in _START_WORDS):
            return entry
    diagnostic = [e for e in stamps if e.entity_category == EntityCategory.DIAGNOSTIC]
    return diagnostic[0] if len(diagnostic) == 1 else None


async def _last_known(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return the last value the entity had, from the recorder; None without one."""
    if "recorder" not in hass.config.components:
        return None
    from homeassistant.components.recorder import get_instance, history

    changes = await get_instance(hass).async_add_executor_job(
        history.get_last_state_changes, hass, 10, entity_id
    )
    for state in reversed(changes.get(entity_id, [])):
        if state.state not in _NO_VALUE:
            return state.state
    return None


def _number(hass: HomeAssistant, entity_id: str) -> float | None:
    """Return the entity's state as a number, None without one."""
    state = hass.states.get(entity_id)
    if state is None or state.state in _NO_VALUE:
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


def _device_part(
    hass: HomeAssistant, adapter: dr.DeviceEntry, host: dr.DeviceEntry
) -> dict[str, Any]:
    """Return what the device behind the scanner says of itself, except when it started."""
    entries = er.async_entries_for_device(er.async_get(hass), host.id)
    signal = next(
        (
            e.entity_id
            for e in entries
            if e.domain == "sensor"
            and (e.device_class or e.original_device_class) == SensorDeviceClass.SIGNAL_STRENGTH
        ),
        None,
    )
    firmware: str | None = host.sw_version
    latest: str | None = None
    update = next((e.entity_id for e in entries if e.domain == "update"), None)
    if update is not None and (state := hass.states.get(update)) is not None:
        firmware = state.attributes.get("installed_version") or firmware
        if state.state == STATE_ON:
            latest = state.attributes.get("latest_version")
    builtin = host.id == adapter.id
    return {
        "model": host.model,
        "manufacturer": host.manufacturer,
        "integration": None if builtin else _integration_name(hass, host),
        "device_id": host.id,
        "signal": _number(hass, signal) if signal else None,
        "firmware": firmware,
        "firmware_latest": latest,
    }


def _scanner_part(hass: HomeAssistant, source: str) -> dict[str, Any]:
    """Return what Home Assistant's Bluetooth knows of the scanner; None for each without it."""
    scanner = next((s for s in async_current_scanners(hass) if s.source.upper() == source), None)
    if scanner is None:
        return {
            "last_seen": None,
            "in_range": None,
            "mode": None,
            "connectable": None,
            "slots": None,
            "slots_free": None,
        }
    now = MONOTONIC_TIME()
    in_range = sum(
        1
        for stamp in scanner.discovered_device_timestamps.values()
        if now - stamp <= SCANNER_ACTIVE_SECONDS
    )
    mode = getattr(scanner, "current_mode", None)
    slots: int | None = None
    free: int | None = None
    for allocation in get_manager().async_current_allocations(scanner.source) or []:
        if allocation.slots > 0:
            slots, free = allocation.slots, allocation.free
    return {
        "last_seen": round(scanner.time_since_last_detection(), 1),
        "in_range": in_range,
        "mode": getattr(mode, "value", None),
        "connectable": bool(getattr(scanner, "connectable", False)),
        "slots": slots,
        "slots_free": free,
    }


async def async_scanner_system(hass: HomeAssistant, source: str) -> dict[str, Any]:
    """Return the system details of the scanner with the source (its address, upper case).

    Each value is None when nothing tells it. When the device is unavailable,
    the time it started is the last one known, marked as not live.
    """
    result: dict[str, Any] = {
        "model": None,
        "manufacturer": None,
        "integration": None,
        "device_id": None,
        "started": None,
        "started_live": False,
        "signal": None,
        "firmware": None,
        "firmware_latest": None,
    }
    adapter, host = _devices(hass, source)
    if adapter is not None and host is not None:
        result |= _device_part(hass, adapter, host)
        entries = er.async_entries_for_device(er.async_get(hass), host.id)
        if (start := _start_entity(entries)) is not None:
            state = hass.states.get(start.entity_id)
            if state is not None and state.state not in _NO_VALUE:
                result["started"], result["started_live"] = state.state, True
            else:
                result["started"] = await _last_known(hass, start.entity_id)
    return result | _scanner_part(hass, source)
