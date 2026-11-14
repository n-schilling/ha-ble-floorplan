"""The system details of a scanner: its device, its entities and what Bluetooth knows of it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, CONNECTION_NETWORK_MAC

from custom_components.ble_floorplan.const import WS_SCANNER_SYSTEM
from custom_components.ble_floorplan.system import async_scanner_system

from . import SCANNER_KITCHEN, SCANNER_LIVING, FakeScanner

MODULE = "custom_components.ble_floorplan.system"


def _host(
    hass: HomeAssistant, domain: str, **device: Any
) -> tuple[MockConfigEntry, dr.DeviceEntry]:
    """Add the device a remote scanner runs on, under an entry of the domain."""
    entry = MockConfigEntry(domain=domain)
    entry.add_to_hass(hass)
    host = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:91")},
        name="Proxy",
        **device,
    )
    return entry, host


def _adapter(
    hass: HomeAssistant, source: str, via: str | None = None, **device: Any
) -> dr.DeviceEntry:
    """Add the scanner's own Bluetooth device, as Home Assistant's Bluetooth does, linked to the one it runs on."""
    entry = MockConfigEntry(domain="bluetooth", unique_id=source)
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    adapter = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_BLUETOOTH, source)},
        name="Adapter",
        **device,
    )
    if via is not None:
        linked = registry.async_update_device(adapter.id, via_device_id=via)
        assert linked is not None
        return linked
    return adapter


def _entity(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    device: dr.DeviceEntry,
    domain: str,
    unique_id: str,
    state: str | None,
    attributes: dict[str, Any] | None = None,
    **extra: Any,
) -> str:
    """Add an entity of the device with its state."""
    entity_id = (
        er.async_get(hass)
        .async_get_or_create(
            domain, entry.domain, unique_id, config_entry=entry, device_id=device.id, **extra
        )
        .entity_id
    )
    if state is not None:
        hass.states.async_set(entity_id, state, attributes or {})
    return entity_id


def _scanner(source: str, idle: float = 3.0, **extra: Any) -> FakeScanner:
    """Return a scanner as Bluetooth has it."""
    scanner = FakeScanner(source, "Proxy")
    scanner.idle = idle
    for name, value in extra.items():
        setattr(scanner, name, value)
    return scanner


def _manager(*allocations: SimpleNamespace) -> MagicMock:
    """Return Bluetooth's manager with the connection slot allocations."""
    manager = MagicMock()
    manager.async_current_allocations.return_value = list(allocations)
    return manager


@pytest.mark.usefixtures("entry")
async def test_remote_scanner(hass: HomeAssistant) -> None:
    """The device the scanner runs on: type, start, signal, firmware; Bluetooth: reception, mode, slots."""
    entry, host = _host(
        hass, "bluetooth", manufacturer="Espressif", model="esp32", sw_version="1.0 (build)"
    )
    _adapter(hass, SCANNER_LIVING, via=host.id)
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "proxy-sensor-last_start",
        "2026-11-13T18:18:40+00:00",
        original_device_class=SensorDeviceClass.TIMESTAMP,
    )
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "proxy-wifi",
        "-72.0",
        original_device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    )
    _entity(
        hass,
        entry,
        host,
        "update",
        "proxy-firmware",
        "on",
        {"installed_version": "2026.10.2", "latest_version": "2026.11.0"},
    )
    scanner = _scanner(
        SCANNER_LIVING,
        idle=2.04,
        current_mode=SimpleNamespace(value="active"),
        connectable=True,
    )
    scanner.discovered_device_timestamps.update({"A": 990.0, "B": 950.0, "C": 900.0})
    with (
        patch(f"{MODULE}.async_current_scanners", return_value=[scanner]),
        patch(f"{MODULE}.MONOTONIC_TIME", return_value=1000.0),
        patch(
            f"{MODULE}.get_manager",
            return_value=_manager(
                SimpleNamespace(slots=0, free=0), SimpleNamespace(slots=3, free=2)
            ),
        ),
    ):
        result = await async_scanner_system(hass, SCANNER_LIVING)
    assert result == {
        "model": "esp32",
        "manufacturer": "Espressif",
        "integration": "Bluetooth",
        "device_id": host.id,
        "started": "2026-11-13T18:18:40+00:00",
        "started_live": True,
        "signal": -72.0,
        "firmware": "2026.10.2",
        "firmware_latest": "2026.11.0",
        "last_seen": 2.0,
        "in_range": 2,
        "mode": "active",
        "connectable": True,
        "slots": 3,
        "slots_free": 2,
    }


@pytest.mark.usefixtures("entry")
async def test_builtin_adapter(hass: HomeAssistant) -> None:
    """A built-in adapter is its own device: no integration named, firmware from the device, no slots told."""
    adapter = _adapter(
        hass, SCANNER_LIVING, manufacturer="Raspberry Pi", model="bcm43438-bt", sw_version="6.18"
    )
    with (
        patch(f"{MODULE}.async_current_scanners", return_value=[_scanner(SCANNER_LIVING)]),
        patch(f"{MODULE}.get_manager", return_value=_manager()),
    ):
        result = await async_scanner_system(hass, SCANNER_LIVING)
    assert result["model"] == "bcm43438-bt"
    assert result["integration"] is None
    assert result["device_id"] == adapter.id
    assert result["firmware"] == "6.18"
    assert result["firmware_latest"] is None
    assert result["started"] is None
    assert result["signal"] is None
    assert result["mode"] is None
    assert result["connectable"] is False
    assert result["slots"] is None


@pytest.mark.usefixtures("entry")
async def test_unknown_scanner(hass: HomeAssistant) -> None:
    """Neither a device nor a scanner in Home Assistant: nothing is told."""
    with (
        patch(f"{MODULE}.async_current_scanners", return_value=[]),
        patch(f"{MODULE}.get_manager", return_value=_manager()),
    ):
        result = await async_scanner_system(hass, SCANNER_KITCHEN)
    assert all(value in (None, False) for value in result.values())


@pytest.mark.usefixtures("entry")
async def test_unavailable_device(hass: HomeAssistant) -> None:
    """The device is gone: the start is the last one known, the signal unknown; an integration not loaded is named by its domain."""
    entry, host = _host(hass, "esphome", manufacturer="Espressif", model="esp32")
    _adapter(hass, SCANNER_LIVING, via=host.id)
    start = _entity(
        hass,
        entry,
        host,
        "sensor",
        "proxy-sensor-uptime",
        "unavailable",
        original_device_class=SensorDeviceClass.TIMESTAMP,
    )
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "proxy-wifi",
        "unavailable",
        original_device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    )
    hass.config.components.add("recorder")
    history = {
        start: [
            State(start, "2026-11-12T08:00:00+00:00"),
            State(start, "2026-11-13T18:18:40+00:00"),
            State(start, "unavailable"),
        ]
    }
    recorder = MagicMock()

    async def run(func: Any, *args: Any) -> Any:
        return func(*args)

    recorder.async_add_executor_job = run
    with (
        patch(f"{MODULE}.async_current_scanners", return_value=[]),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder),
        patch(
            "homeassistant.components.recorder.history.get_last_state_changes", return_value=history
        ),
    ):
        result = await async_scanner_system(hass, SCANNER_LIVING)
    assert result["integration"] == "esphome"
    assert result["started"] == "2026-11-13T18:18:40+00:00"
    assert result["started_live"] is False
    assert result["signal"] is None
    assert result["last_seen"] is None

    # Nothing known in the recorder either
    with (
        patch(f"{MODULE}.async_current_scanners", return_value=[]),
        patch("homeassistant.components.recorder.get_instance", return_value=recorder),
        patch("homeassistant.components.recorder.history.get_last_state_changes", return_value={}),
    ):
        assert (await async_scanner_system(hass, SCANNER_LIVING))["started"] is None


@pytest.mark.usefixtures("entry")
async def test_start_sensor_choice(hass: HomeAssistant) -> None:
    """Without a named start sensor the only diagnostic timestamp counts; without a recorder no last start; a bad signal is none."""
    entry, host = _host(hass, "bluetooth", model="Plug")
    _adapter(hass, SCANNER_LIVING, via=host.id)
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "plug-boot-time",
        None,
        original_device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    # Renamed in the registry, but still not one about starting
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "plug-next",
        "2026-11-20T00:00:00+00:00",
        original_device_class=SensorDeviceClass.TIMESTAMP,
    )
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "plug-rssi",
        "strong",
        original_device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    )
    with patch(f"{MODULE}.async_current_scanners", return_value=[]):
        result = await async_scanner_system(hass, SCANNER_LIVING)
    # boot-time is the start sensor; without a state and without a recorder nothing is told
    assert result["started"] is None
    assert result["signal"] is None

    # Two diagnostic timestamps and none named: no start sensor
    entry2, host2 = _host_two(hass)
    _adapter(hass, SCANNER_KITCHEN, via=host2.id)
    for uid in ("a", "b"):
        _entity(
            hass,
            entry2,
            host2,
            "sensor",
            f"x-{uid}",
            "2026-11-13T18:18:40+00:00",
            original_device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
    with patch(f"{MODULE}.async_current_scanners", return_value=[]):
        assert (await async_scanner_system(hass, SCANNER_KITCHEN))["started"] is None

    # One diagnostic timestamp, not named: it is the start
    _entity(
        hass,
        entry2,
        host2,
        "sensor",
        "x-c",
        "2026-11-13T18:18:40+00:00",
        original_device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    er.async_get(hass).async_update_entity(
        er.async_get(hass).async_get_entity_id("sensor", "bluetooth", "x-a") or "",
        entity_category=None,
    )
    er.async_get(hass).async_update_entity(
        er.async_get(hass).async_get_entity_id("sensor", "bluetooth", "x-b") or "",
        entity_category=None,
    )
    with patch(f"{MODULE}.async_current_scanners", return_value=[]):
        assert (await async_scanner_system(hass, SCANNER_KITCHEN))[
            "started"
        ] == "2026-11-13T18:18:40+00:00"


def _host_two(hass: HomeAssistant) -> tuple[MockConfigEntry, dr.DeviceEntry]:
    """A second device a scanner runs on."""
    entry = MockConfigEntry(domain="bluetooth")
    entry.add_to_hass(hass)
    host = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:92")},
        name="Plug 2",
    )
    return entry, host


@pytest.mark.usefixtures("entry")
async def test_uptime_device_class_and_stable_firmware(hass: HomeAssistant) -> None:
    """A sensor of the uptime device class is the start; the stable firmware wins over a beta one."""
    entry, host = _host(hass, "bluetooth", model="Plug")
    _adapter(hass, SCANNER_LIVING, via=host.id)
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "plug-sys-started",
        "2026-11-01T00:00:00+00:00",
        original_device_class=SensorDeviceClass.TIMESTAMP,
    )
    _entity(
        hass,
        entry,
        host,
        "sensor",
        "plug-sys-up",
        "2026-11-14T10:00:00+00:00",
        original_device_class="uptime",
    )
    _entity(
        hass,
        entry,
        host,
        "update",
        "plug-fwupdate_beta",
        "on",
        {"installed_version": "2.2.0", "latest_version": "2.3.0-beta1"},
    )
    _entity(
        hass,
        entry,
        host,
        "update",
        "plug-fwupdate",
        "off",
        {"installed_version": "2.2.0", "latest_version": "2.2.0"},
    )
    with patch(f"{MODULE}.async_current_scanners", return_value=[]):
        result = await async_scanner_system(hass, SCANNER_LIVING)
    assert result["started"] == "2026-11-14T10:00:00+00:00"
    assert result["firmware"] == "2.2.0"
    assert result["firmware_latest"] is None


@pytest.mark.usefixtures("entry")
async def test_integration_without_entry(hass: HomeAssistant) -> None:
    """A device whose entry is gone names no integration."""
    _, host = _host(hass, "bluetooth", model="Plug")
    _adapter(hass, SCANNER_LIVING, via=host.id)
    with (
        patch(f"{MODULE}.async_current_scanners", return_value=[]),
        patch.object(hass.config_entries, "async_get_entry", return_value=None),
    ):
        assert (await async_scanner_system(hass, SCANNER_LIVING))["integration"] is None


async def test_ws_scanner_system(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """The page asks by the scanner's key; an unknown key is not found."""
    client = await hass_ws_client(hass)
    with patch(
        "custom_components.ble_floorplan.websocket.async_scanner_system",
        return_value={"model": "esp32"},
    ) as system:
        await client.send_json_auto_id({"type": WS_SCANNER_SYSTEM, "key": "living"})
        msg = await client.receive_json()
    assert msg["result"] == {"model": "esp32"}
    system.assert_called_once_with(hass, SCANNER_LIVING)

    await client.send_json_auto_id({"type": WS_SCANNER_SYSTEM, "key": "nope"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"

    await hass.config_entries.async_unload(entry.entry_id)
    await client.send_json_auto_id({"type": WS_SCANNER_SYSTEM, "key": "living"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_loaded"
