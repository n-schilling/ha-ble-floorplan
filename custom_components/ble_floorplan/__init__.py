"""BLE Floorplan: Bluetooth trackers placed on a floor plan by trilateration over the scanners."""

from __future__ import annotations

from dataclasses import dataclass

import probatio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calibration import CalibrationStore
from .const import (
    CALIBRATION_STORAGE_KEY,
    CALIBRATION_STORAGE_VERSION,
    DOMAIN,
    HISTORY_STORAGE_KEY,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import FloorplanCoordinator
from .entity import async_name_devices, async_remove_stale_devices
from .frontend import (
    async_about,
    async_register_frontend,
    async_register_panel,
    async_remove_resource,
    async_unregister_panel,
)
from .history import HistoryStore
from .issues import async_check_trackers, async_clear_issues
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
    # Shown at the bottom of the page: the version, and the commit of a test deployment
    about: dict[str, str | None]


type FloorplanConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> bool:
    """Set up the floor plan: load it, start the engine, serve the card and the panel."""
    store = FloorplanStore(hass)
    calibration = CalibrationStore(hass)
    history = HistoryStore(hass)
    key = STORAGE_KEY
    try:
        await store.async_load()
        key = CALIBRATION_STORAGE_KEY
        await calibration.async_load()
        key = HISTORY_STORAGE_KEY
        await history.async_load(dt_util.utcnow().timestamp(), store.plan.settings.history_days)
    except probatio.Invalid as err:
        # Nothing is replaced: the file stays as it is for a look or a repair by hand
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="invalid_storage",
            translation_placeholders={"file": f".storage/{key}", "error": str(err)},
        ) from err
    coordinator = FloorplanCoordinator(hass, entry, store, calibration, history)
    entry.runtime_data = RuntimeData(
        store, calibration, history, coordinator, await async_about(hass)
    )
    kept_days = store.plan.settings.history_days

    @callback
    def _prune() -> None:
        """Drop the days a shorter timeline no longer keeps; only when the days change."""
        nonlocal kept_days
        if (days := store.plan.settings.history_days) == kept_days:
            return
        kept_days = days
        entry.async_create_task(hass, history.async_prune(dt_util.utcnow().timestamp(), days))

    @callback
    def _stop(event: Event) -> None:
        history.close(dt_util.utcnow().timestamp())

    @callback
    def _plan_changed() -> None:
        """A tracker taken off the plan loses its device, a renamed one renames it; a missing device is a repair issue."""
        async_remove_stale_devices(hass, entry.entry_id, store.plan)
        async_name_devices(hass, entry.entry_id, store.plan)
        async_check_trackers(hass, store.plan)

    @callback
    def _device_changed(event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        async_check_trackers(hass, store.plan)

    entry.async_on_unload(store.async_add_listener(_prune))
    entry.async_on_unload(store.async_add_listener(_plan_changed))
    entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _device_changed))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    await coordinator.async_config_entry_first_refresh()
    await async_register_frontend(hass)
    await async_register_panel(hass)
    async_register_websocket(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_check_trackers(hass, store.plan)
    # Cards and pages subscribed before a reload follow to this coordinator
    async_rebind_subscriptions(hass, entry.runtime_data)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> bool:
    """Unload the entry, ending a calibration run and the tracks; the card and the page stay served until the next restart.

    A run that a reload ends saves the tracker's values, as a stop on the page does.
    """
    if entry.runtime_data.calibration.active is not None:
        await entry.runtime_data.coordinator.async_stop_calibration()
    await entry.runtime_data.history.async_close(dt_util.utcnow().timestamp())
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: FloorplanConfigEntry) -> None:
    """Remove the panel, the dashboard resource, the stored floor plan, the calibration runs, the timeline and the repair issues with the entry."""
    async_unregister_panel(hass)
    async_clear_issues(hass)
    await async_remove_resource(hass)
    store: Store[dict[str, object]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    await store.async_remove()
    calibration: Store[dict[str, object]] = Store(
        hass, CALIBRATION_STORAGE_VERSION, CALIBRATION_STORAGE_KEY
    )
    await calibration.async_remove()
    await HistoryStore(hass).async_remove()
