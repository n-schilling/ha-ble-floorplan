"""BLE Floorplan: Bluetooth trackers placed on a floor plan by trilateration over the scanners."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .calibration import CalibrationStore
from .const import (
    CALIBRATION_STORAGE_KEY,
    CALIBRATION_STORAGE_VERSION,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import FloorplanCoordinator
from .frontend import async_register_frontend
from .store import FloorplanStore
from .websocket import async_rebind_subscriptions, async_register_websocket

PLATFORMS: list[Platform] = [Platform.SENSOR]


@dataclass(slots=True)
class RuntimeData:
    """What the entities and the WebSocket commands share."""

    store: FloorplanStore
    calibration: CalibrationStore
    coordinator: FloorplanCoordinator


type FloorplanConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> bool:
    """Set up the floor plan: load it, start the engine, serve the card."""
    store = FloorplanStore(hass)
    await store.async_load()
    calibration = CalibrationStore(hass)
    await calibration.async_load()
    coordinator = FloorplanCoordinator(hass, entry, store, calibration)
    entry.runtime_data = RuntimeData(store, calibration, coordinator)
    await coordinator.async_config_entry_first_refresh()
    await async_register_frontend(hass)
    async_register_websocket(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Cards subscribed before a reload follow to this coordinator
    async_rebind_subscriptions(hass, entry.runtime_data)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> bool:
    """Unload the entry, ending a calibration run; the card stays served until the next restart."""
    if entry.runtime_data.calibration.active is not None:
        await entry.runtime_data.coordinator.async_stop_calibration()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> None:
    """Remove the stored floor plan and the calibration runs with the entry."""
    store: Store[dict[str, object]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    await store.async_remove()
    calibration: Store[dict[str, object]] = Store(
        hass, CALIBRATION_STORAGE_VERSION, CALIBRATION_STORAGE_KEY
    )
    await calibration.async_remove()
