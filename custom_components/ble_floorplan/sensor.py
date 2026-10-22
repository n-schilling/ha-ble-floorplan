"""Sensors per tracker: the room, and the position for diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FloorplanCoordinator, TrackerPosition
from .model import Floorplan, Tracker

if TYPE_CHECKING:
    from . import FloorplanConfigEntry

KINDS = ("room", "position_x", "position_y")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloorplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors of every tracker and drop those of trackers that are gone."""
    coordinator = entry.runtime_data.coordinator
    plan = coordinator.plan
    _async_remove_stale(hass, entry.entry_id, plan)
    entities: list[SensorEntity] = []
    for tracker in plan.trackers:
        entities.append(RoomSensor(coordinator, tracker))
        entities.append(PositionSensor(coordinator, tracker, "position_x"))
        entities.append(PositionSensor(coordinator, tracker, "position_y"))
    async_add_entities(entities)


@callback
def _async_remove_stale(hass: HomeAssistant, entry_id: str, plan: Floorplan) -> None:
    """Remove the entities and devices of trackers that are no longer in the plan."""
    wanted_ids = {f"{t.key}_{kind}" for t in plan.trackers for kind in KINDS}
    entities = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(entities, entry_id):
        if entry.unique_id not in wanted_ids:
            entities.async_remove(entry.entity_id)
    wanted_devices = {(DOMAIN, t.key) for t in plan.trackers}
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry_id):
        if not device.identifiers & wanted_devices:
            devices.async_update_device(device.id, remove_config_entry_id=entry_id)


class TrackerEntity(CoordinatorEntity[FloorplanCoordinator]):
    """A sensor of one tracker."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker, kind: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = tracker.key
        self._attr_unique_id = f"{tracker.key}_{kind}"
        self._attr_translation_key = kind
        connections = {(CONNECTION_BLUETOOTH, tracker.address)} if tracker.address else set()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tracker.key)}, connections=connections, name=tracker.name
        )

    @property
    def position(self) -> TrackerPosition | None:
        """Return the computed position of the tracker."""
        return self.coordinator.data.get(self._key)


class RoomSensor(TrackerEntity, SensorEntity):
    """The room the tracker is in; unknown while no scanner sees it."""

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, tracker, "room")

    @property
    def native_value(self) -> str | None:
        """Return the room name."""
        position = self.position
        return position.room if position is not None and position.seen else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the position, the nearest scanner and the distance of every scanner."""
        position = self.position
        if position is None or not position.seen:
            return {}
        plan = self.coordinator.plan
        nearest = plan.scanner(position.nearest) if position.nearest is not None else None
        distances = {}
        for key, reading in position.readings.items():
            scanner = plan.scanner(key)
            name = scanner.name if scanner is not None else key
            distances[name] = round(reading.distance, 2) if reading.distance is not None else None
        return {
            "x": round(position.x, 2) if position.x is not None else None,
            "y": round(position.y, 2) if position.y is not None else None,
            "nearest_scanner": nearest.name if nearest is not None else None,
            "scanner_count": position.scanner_count,
            "distances": distances,
        }


class PositionSensor(TrackerEntity, SensorEntity):
    """One coordinate of the tracker on the plan, in metres."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker, kind: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, tracker, kind)
        self._axis = kind[-1]

    @property
    def native_value(self) -> float | None:
        """Return the coordinate."""
        position = self.position
        if position is None or not position.seen:
            return None
        return position.x if self._axis == "x" else position.y
