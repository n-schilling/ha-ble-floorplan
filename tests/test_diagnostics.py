"""Diagnostics and repair issues."""

from __future__ import annotations

from collections.abc import Callable
import json

from pytest_homeassistant.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from custom_components.ble_floorplan.const import DOMAIN
from custom_components.ble_floorplan.diagnostics import async_get_config_entry_diagnostics
from custom_components.ble_floorplan.model import Floorplan

from . import (
    PHONE_DEVICE_ID,
    ROOMS,
    SCANNERS,
    TAG,
    TRACKERS,
    FakeScanner,
    rssi_exact,
    scanner_device,
)
from .conftest import ScannerDevices


async def test_diagnostics_without_who_lives_where(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """Settings, scanners, trackers and readings; no name, address, device id, room or area."""
    runtime = entry.runtime_data
    plan = runtime.store.plan.as_dict()
    plan["rooms"][0]["area"] = "living_room"
    plan["pair_offsets"] = {"kitchen": {"tag": -1.5}, "nowhere": {"tag": 1.0}}
    await runtime.store.async_save(Floorplan.from_dict(plan))
    await runtime.calibration.async_start("tag", 1.0, 1.0, 0.3, 1000.0)
    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0),  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await runtime.coordinator.async_refresh()

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["version"] == runtime.about["version"]
    assert result["floor_plan"]["rooms"] == 5
    assert result["floor_plan"]["zones"] == 1
    assert result["floor_plan"]["linked_to_areas"] == 1
    assert set(result["scanners"]) == {"Scanner 1", "Scanner 2", "Scanner 3"}
    tag = result["trackers"]["Tracker 1"]
    assert tag["kind"] == "fixed address"
    assert tag["seen"] and tag["in_a_room"]
    assert tag["pair_offsets"] == {"Scanner 2": -1.5, "Scanner ?": 1.0}
    assert "Scanner 1" in tag["readings"]
    assert result["trackers"]["Tracker 2"]["kind"] == "Private BLE Device"
    assert result["calibration"] == {"running": True, "runs": {"Tracker 1": 1}}

    text = json.dumps(result)
    secrets = [PHONE_DEVICE_ID, "living_room", *(r["name"] for r in ROOMS)]
    secrets += [s["name"] for s in SCANNERS] + [s["source"] for s in SCANNERS]
    secrets += [t["name"] for t in TRACKERS] + [t.get("address", "") or "-" for t in TRACKERS]
    secrets += [s["key"] for s in SCANNERS] + [t["key"] for t in TRACKERS]
    for secret in secrets:
        assert f'"{secret}"' not in text, secret


async def test_diagnostics_before_the_first_position(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A tracker without a computed position is listed with its settings only."""
    entry.runtime_data.coordinator.data = {}
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert set(result["trackers"]["Tracker 1"]) == {"kind", "height", "ref_power", "pair_offsets"}


async def test_repair_for_a_tracker_without_device(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A Private BLE Device that is gone is a repair issue until it is back or off the plan."""
    issues = ir.async_get(hass)
    # The phone of the example names a device that does not exist
    assert issues.async_get_issue(DOMAIN, "tracker_device_missing_phone") is not None
    other = MockConfigEntry(domain="private_ble_device", data={})
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("private_ble_device", "irk")}, name="Phone"
    )
    plan = entry.runtime_data.store.plan.as_dict()
    plan["trackers"][1]["device_id"] = device.id
    await entry.runtime_data.store.async_save(Floorplan.from_dict(plan))
    assert issues.async_get_issue(DOMAIN, "tracker_device_missing_phone") is None
    # The device goes: the issue comes back with the registry event
    dr.async_get(hass).async_remove_device(device.id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, "tracker_device_missing_phone") is not None
    # Removing the entry removes its issues
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not [i for i in issues.issues if i[0] == DOMAIN]
