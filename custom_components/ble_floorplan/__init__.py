"""BLE Floorplan: Bluetooth trackers placed on a floor plan by trilateration over the scanners."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calibration import CalibrationStore
from .const import (
    CALIBRATION_STORAGE_KEY,
    CALIBRATION_STORAGE_VERSION,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import FloorplanCoordinator
from .frontend import async_register_frontend
from .history import HistoryStore
from .store import FloorplanStore
from .websocket import async_rebind_subscriptions, async_register_websocket

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.DEVICE_TRACKER]


@dataclass(slots=True)
class RuntimeData:
    """What the entities and the WebSocket commands share."""

    store: FloorplanStore
    calibration: CalibrationStore
    history: HistoryStore
    coordinator: FloorplanCoordinator


type FloorplanConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> bool:
    """Set up the floor plan: load it, start the engine, serve the card."""
    store = FloorplanStore(hass)
    await store.async_load()
    calibration = CalibrationStore(hass)
    await calibration.async_load()
    history = HistoryStore(hass)
    await history.async_load(dt_util.utcnow().timestamp(), store.plan.settings.history_days)
    coordinator = FloorplanCoordinator(hass, entry, store, calibration, history)
    entry.runtime_data = RuntimeData(store, calibration, history, coordinator)

    @callback
    def _prune() -> None:
        """Drop the days a shorter timeline no longer keeps."""
        days = store.plan.settings.history_days
        entry.async_create_task(hass, history.async_prune(dt_util.utcnow().timestamp(), days))

    @callback
    def _stop(event: Event) -> None:
        history.close(dt_util.utcnow().timestamp())

    entry.async_on_unload(store.async_add_listener(_prune))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    await coordinator.async_config_entry_first_refresh()
    await async_register_frontend(hass)
    async_register_websocket(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Cards subscribed before a reload follow to this coordinator
    async_rebind_subscriptions(hass, entry.runtime_data)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> bool:
    """Unload the entry, ending a calibration run and the tracks; the card stays served until the next restart."""
    if entry.runtime_data.calibration.active is not None:
        await entry.runtime_data.coordinator.async_stop_calibration()
    await entry.runtime_data.history.async_close(dt_util.utcnow().timestamp())
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> None:
    """Remove the stored floor plan, the calibration runs and the timeline with the entry."""
    store: Store[dict[str, object]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    await store.async_remove()
    calibration: Store[dict[str, object]] = Store(
        hass, CALIBRATION_STORAGE_VERSION, CALIBRATION_STORAGE_KEY
    )
    await calibration.async_remove()
    await HistoryStore(hass).async_remove()
