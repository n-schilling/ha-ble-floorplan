"""What the entities of a tracker share: the device, and following the trackers of the plan."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FloorplanCoordinator, TrackerPosition
from .model import Floorplan, Tracker

if TYPE_CHECKING:
    from . import FloorplanConfigEntry

# The integration's own device, with the entities about the scanners
HUB = "hub"


def tracker_device(tracker: Tracker) -> DeviceInfo:
    """Return the device of a tracker, which its entities share."""
    connections = {(CONNECTION_BLUETOOTH, tracker.address)} if tracker.address else set()
    return DeviceInfo(
        identifiers={(DOMAIN, tracker.key)}, connections=connections, name=tracker.name
    )


class TrackerEntity(CoordinatorEntity[FloorplanCoordinator]):
    """An entity of one tracker, on the tracker's device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker, kind: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._key = tracker.key
        self._attr_unique_id = f"{tracker.key}_{kind}"
        self._attr_translation_key = kind
        self._attr_device_info = tracker_device(tracker)

    @property
    def available(self) -> bool:
        """Return False while the tracker is paused: it is not measured, not away."""
        tracker = self.coordinator.plan.tracker(self._key)
        return super().available and not (tracker is not None and tracker.paused)

    @property
    def position(self) -> TrackerPosition | None:
        """Return the computed position of the tracker."""
        return self.coordinator.data.get(self._key)


@callback
def async_follow_trackers(
    entry: FloorplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    create: Callable[[Tracker], Iterable[Entity]],
) -> None:
    """Add the entities of every tracker, now and whenever one is added to the plan.

    A tracker taken off the plan loses its device, and with it its entities,
    through async_remove_stale_devices.
    """
    store = entry.runtime_data.store
    added: set[str] = set()

    @callback
    def _add() -> None:
        # A tracker taken off the plan and put back gets its entities again
        added.intersection_update(t.key for t in store.plan.trackers)
        new = [t for t in store.plan.trackers if t.key not in added]
        added.update(t.key for t in new)
        entities = [entity for tracker in new for entity in create(tracker)]
        if entities:
            async_add_entities(entities)

    _add()
    entry.async_on_unload(store.async_add_listener(_add))


@callback
def async_remove_stale_devices(hass: HomeAssistant, entry_id: str, plan: Floorplan) -> None:
    """Remove the devices of trackers no longer on the plan, with their entities."""
    wanted = {(DOMAIN, t.key) for t in plan.trackers} | {(DOMAIN, HUB)}
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry_id):
        if not device.identifiers & wanted:
            devices.async_remove_device(device.id)


@callback
def async_name_devices(hass: HomeAssistant, entry_id: str, plan: Floorplan) -> None:
    """Give the devices of renamed trackers their new names; the entities follow.

    A name the user gave the device in Home Assistant stays on top of it.
    """
    devices = dr.async_get(hass)
    for tracker in plan.trackers:
        device = devices.async_get_device_by_identifier((DOMAIN, tracker.key), entry_id)
        if device is not None and device.name != tracker.name:
            devices.async_update_device(device.id, name=tracker.name)
