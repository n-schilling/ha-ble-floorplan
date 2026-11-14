"""Paused scanners and trackers: left out until resumed, kept over a restart."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.catalog import offline_scanners
from custom_components.ble_floorplan.const import WS_SET_SCANNER, WS_SET_TRACKER
from custom_components.ble_floorplan.coverage import model
from custom_components.ble_floorplan.model import Floorplan

from . import SCANNERS, TAG, TRACKERS, FakeScanner, make_plan, rssi_exact, scanner_device
from .conftest import ScannerDevices


def _paused(
    plan: Floorplan, scanners: tuple[str, ...] = (), trackers: tuple[str, ...] = ()
) -> Floorplan:
    """Return the plan with the scanners and trackers paused."""
    return replace(
        plan,
        scanners=tuple(replace(s, paused=s.key in scanners) for s in plan.scanners),
        trackers=tuple(replace(t, paused=t.key in trackers) for t in plan.trackers),
    )


def _adverts(scanners: dict[str, FakeScanner], stamp: float) -> list:
    """Adverts of the tag from all three scanners."""
    return [
        scanner_device(scanners["living"], TAG, rssi_exact(2.0, -60, 0.8, 0.3), stamp),  # type: ignore[arg-type]
        scanner_device(scanners["kitchen"], TAG, rssi_exact(6.5, -60, 2.0, 0.3), stamp),  # type: ignore[arg-type]
        scanner_device(scanners["bedroom"], TAG, rssi_exact(5.0, -60, 0.5, 0.3), stamp),  # type: ignore[arg-type]
    ]


def test_stored_only_when_paused() -> None:
    """The plan keeps paused only when set, and reads it back."""
    plan = make_plan(
        scanners=[{**SCANNERS[0], "paused": True}, *SCANNERS[1:]],
        trackers=[{**TRACKERS[0], "paused": True}, *TRACKERS[1:]],
    )
    data = plan.as_dict()
    assert data["scanners"][0]["paused"] is True
    assert "paused" not in data["scanners"][1]
    assert data["trackers"][0]["paused"] is True
    assert "paused" not in data["trackers"][1]
    assert Floorplan.from_dict(data) == plan


def test_paused_scanner_not_offline_nor_in_the_model(hass: HomeAssistant) -> None:
    """A paused scanner is not reported silent and adds nothing to the coverage model."""
    plan = _paused(make_plan(), scanners=("kitchen",))
    with patch("custom_components.ble_floorplan.catalog.async_current_scanners", return_value=[]):
        assert offline_scanners(hass, plan) == ["living", "bedroom"]
    with_all = model(make_plan())
    without = model(plan)
    assert sum(c[3] for c in without["cells"]) < sum(c[3] for c in with_all["cells"])


async def test_paused_scanner_left_out(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """The readings of a paused scanner do not go into the position."""
    coordinator = entry.runtime_data.coordinator
    await entry.runtime_data.store.async_save(_paused(coordinator.plan, scanners=("bedroom",)))
    scanner_devices[TAG] = _adverts(scanners, 1000.0)
    clock(1001.0)
    await coordinator.async_refresh()
    tag = coordinator.data["tag"]
    assert tag.seen
    assert tag.scanner_count == 2
    assert tag.readings["bedroom"].rssi is None


async def test_paused_tracker_unavailable(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """A paused tracker has no position and its entities are unavailable; resumed, it starts afresh."""
    coordinator = entry.runtime_data.coordinator
    scanner_devices[TAG] = _adverts(scanners, 1000.0)
    clock(1001.0)
    await coordinator.async_refresh()
    assert coordinator.data["tag"].seen

    await entry.runtime_data.store.async_save(_paused(coordinator.plan, trackers=("tag",)))
    clock(1002.0)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    tag = coordinator.data["tag"]
    assert not tag.seen
    assert tag.present is None
    assert tag.room is None
    for entity_id in ("sensor.tag_room", "device_tracker.tag_presence"):
        state = hass.states.get(entity_id)
        assert state is not None and state.state == STATE_UNAVAILABLE, entity_id

    await entry.runtime_data.store.async_save(_paused(coordinator.plan))
    scanner_devices[TAG] = _adverts(scanners, 1003.0)
    clock(1004.0)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    back = coordinator.data["tag"]
    assert back.seen
    # Taken as is: no smoothing carried over from before the pause
    assert back.x == back.raw_x
    state = hass.states.get("sensor.tag_room")
    assert state is not None and state.state == "Living room"


async def test_active_scanners_leave_paused_out(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanners: dict[str, FakeScanner],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A paused scanner counts neither as active nor as missing; it is listed apart."""
    await entry.runtime_data.store.async_save(
        _paused(entry.runtime_data.store.plan, scanners=("kitchen",))
    )
    with patch(
        "custom_components.ble_floorplan.catalog.async_current_scanners",
        return_value=[scanners["living"]],
    ):
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    state = hass.states.get("sensor.ble_floorplan_active_scanners")
    assert state is not None
    assert state.state == "1"
    assert state.attributes["total"] == 2
    assert state.attributes["inactive"] == ["Bedroom proxy"]
    assert state.attributes["paused"] == ["Kitchen plug"]


async def test_ws_pause_and_resume(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    """set_scanner and set_tracker take paused; the plan for everyone shows it."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SET_SCANNER, "key": "kitchen", "paused": True})
    msg = await client.receive_json()
    assert msg["result"]["paused"] is True
    await client.send_json_auto_id({"type": WS_SET_TRACKER, "key": "tag", "paused": True})
    msg = await client.receive_json()
    assert msg["result"]["paused"] is True
    plan = entry.runtime_data.store.plan
    assert plan.scanner("kitchen").paused  # type: ignore[union-attr]
    assert plan.tracker("tag").paused  # type: ignore[union-attr]

    await client.send_json_auto_id({"type": WS_SET_TRACKER, "key": "tag", "paused": False})
    msg = await client.receive_json()
    assert "paused" not in msg["result"]
    assert not entry.runtime_data.store.plan.tracker("tag").paused  # type: ignore[union-attr]
