"""Fixtures: the example plan in storage, fake scanners, a controllable clock."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.ble_floorplan.const import DOMAIN, NAME, STORAGE_KEY

from . import FLOORPLAN, FakeScanner

ScannerDevices = dict[str, list[Any]]


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def stored_plan() -> dict[str, Any]:
    """The plan that is in storage before the entry is set up."""
    return FLOORPLAN


@pytest.fixture
def storage(hass_storage: dict[str, Any], stored_plan: dict[str, Any]) -> dict[str, Any]:
    """Storage with the plan in it."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": stored_plan,
    }
    return hass_storage


@pytest.fixture
async def bluetooth(hass: HomeAssistant, mock_bluetooth: None) -> None:
    """Home Assistant's Bluetooth stack with a simulated adapter, plus http for the card."""
    assert await async_setup_component(hass, "bluetooth", {})
    assert await async_setup_component(hass, "http", {})
    await hass.async_block_till_done()


@pytest.fixture
def clock() -> Generator[Callable[[float], None]]:
    """The monotonic clock of the engine; call the fixture's function to set it."""
    now = {"t": 1000.0}

    def _set(value: float) -> None:
        now["t"] = value

    with patch("custom_components.ble_floorplan.coordinator.MONOTONIC_TIME", lambda: now["t"]):
        yield _set


@pytest.fixture
def scanner_devices() -> Generator[ScannerDevices]:
    """What the scanners report per address; fill the dict in the test."""
    devices: ScannerDevices = {}
    with patch(
        "custom_components.ble_floorplan.coordinator.async_scanner_devices_by_address",
        lambda hass, address, connectable: list(devices.get(address, [])),
    ):
        yield devices


@pytest.fixture
def scanners() -> dict[str, FakeScanner]:
    """The three scanners of the example."""
    from . import SCANNER_BEDROOM, SCANNER_KITCHEN, SCANNER_LIVING

    return {
        "living": FakeScanner(SCANNER_LIVING, "Living room scanner"),
        "kitchen": FakeScanner(SCANNER_KITCHEN, "Kitchen plug"),
        "bedroom": FakeScanner(SCANNER_BEDROOM, "Bedroom proxy"),
    }


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """The entry, not yet added."""
    return MockConfigEntry(domain=DOMAIN, title=NAME, unique_id=DOMAIN, data={})


@pytest.fixture
async def entry(
    hass: HomeAssistant,
    bluetooth: None,
    storage: dict[str, Any],
    clock: Callable[[float], None],
    scanner_devices: ScannerDevices,
    config_entry: MockConfigEntry,
) -> AsyncGenerator[MockConfigEntry]:
    """The integration set up with the example plan."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    if (
        hass.config_entries.async_get_entry(config_entry.entry_id) is not None
        and config_entry.state.recoverable
    ):
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
