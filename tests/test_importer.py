"""Mapping the earlier card's configuration to scanners and trackers of Home Assistant."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH

from custom_components.ble_floorplan.importer import ImportProblem, build_floorplan

from . import ROOMS, SCANNER_BEDROOM, SCANNER_KITCHEN, SCANNER_LIVING, TAG, FakeScanner

CARD: dict[str, Any] = {
    "rooms": ROOMS,
    "openings": [[6, 1, 6, 2.5]],
    "scanners": [
        {"key": "living", "name": "Living", "suffix": "living_room_scanner", "default": [1, 1]},
        {"key": "kitchen", "name": "Kitchen", "suffix": "kitchen_plug", "default": [9, 1], "z": 2},
        {"key": "bedroom", "name": "Bedroom", "suffix": "bedroom_proxy"},
    ],
    "trackers": [{"prefix": "tag", "name": "Tag"}, {"prefix": "phone", "name": "Phone"}],
    "positions": {"living": [1.5, 1.2]},
    "smoothing_seconds": 10,
    "clamp": False,
    "settings": {"attenuation": 2.5},
}


@pytest.fixture
def current_scanners(scanners: dict[str, FakeScanner]) -> list[FakeScanner]:
    """Home Assistant's scanners: the three of the example."""
    return list(scanners.values())


@pytest.fixture(autouse=True)
def _patch_scanners(current_scanners: list[FakeScanner]) -> Any:
    with patch(
        "custom_components.ble_floorplan.importer.async_current_scanners",
        return_value=current_scanners,
    ):
        yield


@pytest.fixture
async def registry(hass: HomeAssistant, bluetooth: None) -> MockConfigEntry:
    """Devices as Home Assistant has them: the scanners' Bluetooth devices, Tag, Phone."""
    other = MockConfigEntry(domain="other", data={})
    other.add_to_hass(hass)
    devices = dr.async_get(hass)
    # The kitchen plug's Bluetooth device carries its address in the name, as Shelly proxies do
    devices.async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(CONNECTION_BLUETOOTH, SCANNER_KITCHEN)},
        name=f"Kitchen plug ({SCANNER_KITCHEN})",
    )
    devices.async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(CONNECTION_BLUETOOTH, SCANNER_BEDROOM.lower())},
        name="Bedroom proxy",
    )
    # A device named Tag with a Bluetooth address, as Bermuda or BTHome create it
    devices.async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(CONNECTION_BLUETOOTH, TAG)},
        identifiers={("other", "tag")},
        name="Tag",
    )
    # A Private BLE Device with its device tracker
    pbd = MockConfigEntry(domain="private_ble_device", data={})
    pbd.add_to_hass(hass)
    phone = devices.async_get_or_create(
        config_entry_id=pbd.entry_id, identifiers={("private_ble_device", "irk")}, name="Phone BLE"
    )
    er.async_get(hass).async_get_or_create(
        "device_tracker",
        "private_ble_device",
        "irk",
        suggested_object_id="phone",
        config_entry=pbd,
        device_id=phone.id,
    )
    return pbd


async def test_import(hass: HomeAssistant, registry: MockConfigEntry) -> None:
    """Scanners by suffix, trackers by device, positions, settings from the card."""
    hass.states.async_set("number.tag_calibration_ref_power_at_1m_0_for_default", "-42.0")
    hass.states.async_set("number.phone_calibration_ref_power_at_1m_0_for_default", "0.0")
    plan = build_floorplan(hass, CARD)
    living, kitchen, bedroom = plan.scanners
    assert (living.source, living.x, living.y, living.z) == (SCANNER_LIVING, 1.5, 1.2, 0.0)
    assert (kitchen.source, kitchen.x, kitchen.y, kitchen.z) == (SCANNER_KITCHEN, 9.0, 1.0, 2.0)
    assert (bedroom.source, bedroom.x, bedroom.y) == (SCANNER_BEDROOM, 0.0, 0.0)
    tag, phone = plan.trackers
    assert (tag.key, tag.name, tag.address, tag.ref_power) == ("tag", "Tag", TAG, -42.0)
    devices = dr.async_get(hass)
    phone_device = devices.async_get_device_by_identifier(
        ("private_ble_device", "irk"), registry.entry_id
    )
    assert phone_device is not None
    assert (phone.key, phone.name, phone.device_id, phone.ref_power) == (
        "phone",
        "Phone BLE",
        phone_device.id,
        None,
    )
    assert plan.settings.smoothing_seconds == 10.0
    assert plan.settings.clamp is False
    assert plan.settings.attenuation == 2.5
    assert plan.rooms[0].name == "Living room"
    assert plan.openings == ((6, 1, 6, 2.5),)


async def test_explicit_values(hass: HomeAssistant, registry: MockConfigEntry) -> None:
    """source, address, device_id, entity_id, ref_power and height given outright."""
    devices = dr.async_get(hass)
    phone_device = devices.async_get_device_by_identifier(
        ("private_ble_device", "irk"), registry.entry_id
    )
    assert phone_device is not None
    card = {
        **CARD,
        "scanners": [{"key": "living", "source": SCANNER_LIVING.lower()}],
        "trackers": [
            {"key": "a", "address": TAG, "ref_power": -50, "height": 0.4},
            {"key": "b", "device_id": phone_device.id, "ref_power": None},
            {"key": "c", "entity_id": "device_tracker.phone", "name": "Card name"},
        ],
        "positions": None,
    }
    plan = build_floorplan(hass, card)
    assert plan.scanners[0].name == "living"
    assert plan.scanners[0].source == SCANNER_LIVING
    assert (plan.scanners[0].x, plan.scanners[0].y) == (0.0, 0.0)
    a, b, c = plan.trackers
    assert (a.name, a.address, a.ref_power, a.height) == ("a", TAG, -50.0, 0.4)
    assert (b.name, b.device_id, b.ref_power) == ("Phone BLE", phone_device.id, None)
    assert (c.name, c.device_id) == ("Phone BLE", phone_device.id)


async def test_bermuda_calibration_unreadable(
    hass: HomeAssistant, registry: MockConfigEntry
) -> None:
    """A calibration that is no number is ignored."""
    hass.states.async_set("number.tag_calibration_ref_power_at_1m_0_for_default", "unavailable")
    plan = build_floorplan(hass, CARD)
    assert plan.trackers[0].ref_power is None


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"scanners": [{"key": "x", "name": "X"}]}, "neither source nor suffix"),
        ({"scanners": [{"key": "x", "suffix": "nowhere"}]}, "matches 0 scanners"),
        ({"trackers": [{"name": "no key"}]}, "without key"),
        ({"trackers": [{"key": "ghost", "device_id": "no-such-device"}]}, "does not exist"),
        ({"trackers": [{"key": "ghost"}]}, "give address or device_id"),
    ],
)
async def test_problems(
    hass: HomeAssistant, registry: MockConfigEntry, change: dict[str, Any], text: str | None
) -> None:
    """Unmapped scanners and trackers stop the import with a reason."""
    with pytest.raises(ImportProblem) as err:
        build_floorplan(hass, {**CARD, **change})
    if text is not None:
        assert text in str(err.value)


async def test_ambiguous_suffix_is_fine_when_unique(
    hass: HomeAssistant, registry: MockConfigEntry
) -> None:
    """A suffix that matches two scanners is refused; the message lists the known slugs."""
    current = [
        FakeScanner(SCANNER_LIVING, "Kitchen plug A"),
        FakeScanner(SCANNER_KITCHEN, "Kitchen plug B"),
    ]
    with (
        patch(
            "custom_components.ble_floorplan.importer.async_current_scanners", return_value=current
        ),
        pytest.raises(ImportProblem) as err,
    ):
        build_floorplan(hass, {**CARD, "scanners": [{"key": "k", "suffix": "kitchen_plug"}]})
    assert "matches 2 scanners" in str(err.value)
    assert "kitchen_plug_a" in str(err.value)


async def test_invalid_result(hass: HomeAssistant, registry: MockConfigEntry) -> None:
    """A mapped plan that is no valid floor plan raises probatio's error."""
    with pytest.raises(probatio.Invalid):
        build_floorplan(hass, {**CARD, "rooms": [{"name": "Broken"}]})


async def test_device_without_bluetooth_connection(
    hass: HomeAssistant, registry: MockConfigEntry
) -> None:
    """A device of the tracker's name without a Bluetooth address does not count."""
    other = MockConfigEntry(domain="other2", data={})
    other.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other2", "keys")}, name="Keys"
    )
    with pytest.raises(ImportProblem):
        build_floorplan(hass, {**CARD, "trackers": [{"key": "keys"}]})
