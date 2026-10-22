"""The engine on Home Assistant's scanners: windows, staleness, Private BLE Devices."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.ble_floorplan.const import DOMAIN

from . import (
    PHONE_ADDRESS,
    PHONE_DEVICE_ID,
    SCANNER_BEDROOM,
    SCANNER_KITCHEN,
    SCANNER_LIVING,
    TAG,
    FakeScanner,
    make_plan,
    rssi_exact,
    scanner_device,
)
from .conftest import ScannerDevices


def _tag_adverts(
    scanners: dict[str, FakeScanner], stamp: float, distances: tuple[float, float, float]
) -> list:
    """Adverts of the tag giving the floor distances to the three scanners."""
    ref = -60
    return [
        scanner_device(scanners["living"], TAG, rssi_exact(distances[0], ref, 0.8, 0.3), stamp),  # type: ignore[arg-type]
        scanner_device(scanners["kitchen"], TAG, rssi_exact(distances[1], ref, 2.0, 0.3), stamp),  # type: ignore[arg-type]
        scanner_device(scanners["bedroom"], TAG, rssi_exact(distances[2], ref, 0.5, 0.3), stamp),  # type: ignore[arg-type]
    ]


async def test_position_from_three_scanners(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """Distances 2.0 / 6.5 / 5.0 give the card's position; the first position is not smoothed."""
    coordinator = entry.runtime_data.coordinator
    tag = coordinator.data["tag"]
    assert not tag.seen
    assert tag.address == TAG
    assert tag.readings["living"].distance is None
    scanner_devices[TAG] = _tag_adverts(scanners, 1000.0, (2.0, 6.5, 5.0))
    clock(1001.0)
    await coordinator.async_refresh()
    tag = coordinator.data["tag"]
    assert tag.seen
    assert (tag.x, tag.y) == pytest.approx((2.1611725513, 2.7064602714), abs=1e-6)
    assert (tag.raw_x, tag.raw_y) == (tag.x, tag.y)
    assert tag.room == "Living room"
    assert tag.nearest == "living"
    assert tag.scanner_count == 3
    assert tag.readings["kitchen"].distance == pytest.approx(6.5)
    assert tag.readings["kitchen"].used
    assert tag.readings["kitchen"].rssi == pytest.approx(rssi_exact(6.5, -60, 2.0, 0.3))
    assert tag.as_dict()["readings"]["bedroom"]["distance"] == pytest.approx(5.0)


async def test_window_median_and_dedupe(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """The same advertisement is counted once; the RSSI is the median of the window."""
    coordinator = entry.runtime_data.coordinator
    living = scanners["living"]
    # One advertisement, read in three refreshes: still one sample
    scanner_devices[TAG] = [scanner_device(living, TAG, -60, 1000.0)]
    for t in (1001.0, 1002.0, 1003.0):
        clock(t)
        await coordinator.async_refresh()
    assert coordinator.data["tag"].readings["living"].rssi == -60
    # Two more samples within the window: median of three
    scanner_devices[TAG] = [scanner_device(living, TAG, -70, 1004.0)]
    clock(1005.0)
    await coordinator.async_refresh()
    scanner_devices[TAG] = [scanner_device(living, TAG, -65, 1006.0)]
    clock(1007.0)
    await coordinator.async_refresh()
    assert coordinator.data["tag"].readings["living"].rssi == -65
    # A sample 10 s later pushes the first out of the window: median of -70, -65, -50 = -65
    scanner_devices[TAG] = [scanner_device(living, TAG, -50, 1011.0)]
    clock(1012.0)
    await coordinator.async_refresh()
    assert coordinator.data["tag"].readings["living"].rssi == -65
    # One scanner only: the tracker sits at that scanner
    tag = coordinator.data["tag"]
    assert tag.scanner_count == 1
    assert tag.nearest == "living"


async def test_stale_and_reset(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """After 30 s without an advertisement the tracker is not seen, and the smoothing restarts."""
    coordinator = entry.runtime_data.coordinator
    scanner_devices[TAG] = _tag_adverts(scanners, 1000.0, (2.0, 6.5, 5.0))
    clock(1001.0)
    await coordinator.async_refresh()
    assert coordinator.data["tag"].seen
    # A move within the time constant is smoothed
    scanner_devices[TAG] = _tag_adverts(scanners, 1005.0, (7.0, 1.0, 9.0))
    clock(1006.0)
    await coordinator.async_refresh()
    smoothed = coordinator.data["tag"]
    assert smoothed.raw_x is not None and smoothed.x is not None
    assert smoothed.x < smoothed.raw_x
    # Nothing new for 30 s: gone
    clock(1036.0)
    await coordinator.async_refresh()
    gone = coordinator.data["tag"]
    assert not gone.seen
    assert gone.room is None
    assert gone.readings["living"].distance is None
    # Back: the position is taken as is
    scanner_devices[TAG] = _tag_adverts(scanners, 1040.0, (7.0, 1.0, 9.0))
    clock(1041.0)
    await coordinator.async_refresh()
    back = coordinator.data["tag"]
    assert back.x == back.raw_x


async def test_far_scanner_ignored(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """A distance beyond max_distance is shown but not used."""
    coordinator = entry.runtime_data.coordinator
    scanner_devices[TAG] = _tag_adverts(scanners, 1000.0, (2.0, 40.0, 5.0))
    clock(1001.0)
    await coordinator.async_refresh()
    tag = coordinator.data["tag"]
    assert tag.readings["kitchen"].distance == pytest.approx(40.0)
    assert not tag.readings["kitchen"].used
    assert tag.scanner_count == 2


async def test_timestamp_missing(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """A scanner without timestamps: every read counts as a fresh sample at the current time."""
    coordinator = entry.runtime_data.coordinator
    scanner_devices[TAG] = [scanner_device(scanners["living"], TAG, -60, None)]
    clock(1001.0)
    await coordinator.async_refresh()
    assert coordinator.data["tag"].seen
    clock(1050.0)
    await coordinator.async_refresh()
    assert coordinator.data["tag"].seen


async def test_unknown_scanner_ignored(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    clock: Callable[[float], None],
) -> None:
    """A scanner that is not in the plan contributes nothing."""
    coordinator = entry.runtime_data.coordinator
    other = FakeScanner("AA:BB:CC:DD:EE:99", "Somewhere")
    scanner_devices[TAG] = [scanner_device(other, TAG, -40, 1000.0)]
    clock(1001.0)
    await coordinator.async_refresh()
    assert not coordinator.data["tag"].seen


async def test_private_ble_device(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """A Private BLE Device is tracked at the address its device tracker currently reports."""
    coordinator = entry.runtime_data.coordinator
    phone = coordinator.data["phone"]
    assert phone.address is None
    # The device and its tracker appear
    devices = dr.async_get(hass)
    other_entry = MockConfigEntry(domain="private_ble_device", data={})
    other_entry.add_to_hass(hass)
    device = devices.async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={("private_ble_device", "irk")},
        name="Phone",
    )
    entities = er.async_get(hass)
    entities.async_get_or_create(
        "device_tracker",
        "private_ble_device",
        "irk",
        suggested_object_id="phone",
        config_entry=other_entry,
        device_id=device.id,
    )
    plan = coordinator.plan
    tracker = plan.tracker("phone")
    assert tracker is not None
    object.__setattr__(tracker, "device_id", device.id)
    # No state yet: no address
    clock(1001.0)
    await coordinator.async_refresh()
    assert coordinator.data["phone"].address is None
    # State without the attribute
    hass.states.async_set("device_tracker.phone", "home", {})
    clock(1002.0)
    await coordinator.async_refresh()
    assert coordinator.data["phone"].address is None
    # The current address, lower case as some integrations write it
    hass.states.async_set(
        "device_tracker.phone", "home", {"current_address": PHONE_ADDRESS.lower()}
    )
    scanner_devices[PHONE_ADDRESS] = [
        scanner_device(scanners["kitchen"], PHONE_ADDRESS, rssi_exact(1.5, -55, 2.0, 1.0), 1002.0)  # type: ignore[arg-type]
    ]
    clock(1003.0)
    await coordinator.async_refresh()
    phone = coordinator.data["phone"]
    assert phone.address == PHONE_ADDRESS
    assert phone.seen
    assert phone.room == "Kitchen"
    assert phone.readings["kitchen"].distance == pytest.approx(1.5)
    assert device.id != PHONE_DEVICE_ID


async def test_private_ble_device_without_tracker(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A device without a device tracker of Private BLE Device has no address."""
    coordinator = entry.runtime_data.coordinator
    devices = dr.async_get(hass)
    other_entry = MockConfigEntry(domain="other", data={})
    other_entry.add_to_hass(hass)
    device = devices.async_get_or_create(
        config_entry_id=other_entry.entry_id, identifiers={("other", "x")}, name="Other"
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "other", "x", config_entry=other_entry, device_id=device.id
    )
    tracker = coordinator.plan.tracker("phone")
    assert tracker is not None
    object.__setattr__(tracker, "device_id", device.id)
    await coordinator.async_refresh()
    assert coordinator.data["phone"].address is None
    assert DOMAIN == "ble_floorplan"
    assert {SCANNER_LIVING, SCANNER_KITCHEN, SCANNER_BEDROOM} == {
        s.source for s in coordinator.plan.scanners
    }


async def test_calibration_records_new_advertisements(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """While a run goes, every new advertisement of a plan scanner is a sample of the run."""
    coordinator = entry.runtime_data.coordinator
    calibration = entry.runtime_data.calibration
    # Seen before the run: that advertisement is not part of it
    scanner_devices[TAG] = [scanner_device(scanners["living"], TAG, -50, 1000.0)]
    clock(1001.0)
    await coordinator.async_refresh()
    run = await coordinator.async_start_calibration("tag", 2.0, 2.0, 0.4)
    assert calibration.active is run
    assert run.x == 2.0 and run.height == 0.4
    other = FakeScanner("AA:BB:CC:DD:EE:99", "Somewhere")
    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, -60, 1002.0),
        scanner_device(scanners["kitchen"], TAG, -70, 1002.5),
        scanner_device(other, TAG, -40, 1002.0),
    ]
    # Read twice: the same advertisements count once
    for t in (1003.0, 1004.0):
        clock(t)
        await coordinator.async_refresh()
    scanner_devices[TAG] = [scanner_device(scanners["living"], TAG, -62, 1005.0)]
    clock(1006.0)
    await coordinator.async_refresh()
    assert run.samples == {"living": [(1.0, -60), (4.0, -62)], "kitchen": [(1.5, -70)]}
    # The phone is not the run's tracker
    hass.states.async_set("device_tracker.phone", "home", {"current_address": PHONE_ADDRESS})
    stopped = await coordinator.async_stop_calibration()
    assert stopped is run
    assert run.duration == 5.0
    assert calibration.active is None
    # After the stop nothing is added
    scanner_devices[TAG] = [scanner_device(scanners["living"], TAG, -63, 1007.0)]
    clock(1008.0)
    await coordinator.async_refresh()
    assert run.summary()["counts"] == {"living": 2, "kitchen": 1}


async def test_pair_offset_shortens_a_scanner_distance(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """A pair correction adds to the scanner's offset for that tracker only."""
    coordinator = entry.runtime_data.coordinator
    await entry.runtime_data.store.async_save(
        make_plan(pair_offsets={"living": {"tag": -30.0}, "kitchen": {"phone": 5.0}})
    )
    scanner_devices[TAG] = [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), 1000.0),  # type: ignore[arg-type]
        scanner_device(scanners["kitchen"], TAG, rssi_exact(6.5, -60, 2.0, 0.3), 1000.0),  # type: ignore[arg-type]
    ]
    clock(1001.0)
    await coordinator.async_refresh()
    tag = coordinator.data["tag"]
    # -30 dB at exponent 3 is a tenth of the line-of-sight distance, then projected
    assert tag.readings["living"].distance == pytest.approx(0.0)
    assert tag.readings["kitchen"].distance == pytest.approx(6.5)
