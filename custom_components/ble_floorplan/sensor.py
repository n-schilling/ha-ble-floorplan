"""Sensors per tracker: the room, and the position for diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.bluetooth import async_current_scanners
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, SCANNER_ACTIVE_SECONDS
from .coordinator import FloorplanCoordinator, TrackerPosition
from .model import Floorplan, Tracker

if TYPE_CHECKING:
    from . import FloorplanConfigEntry

KINDS = ("room", "position_x", "position_y", "presence")
HUB = "hub"
ACTIVE_SCANNERS = "active_scanners"
# Decimals of the position sensors
POSITION_DIGITS = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloorplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors of every tracker and drop those of trackers that are gone."""
    coordinator = entry.runtime_data.coordinator
    plan = coordinator.plan
    _async_remove_stale(hass, entry.entry_id, plan)
    entities: list[SensorEntity] = [ActiveScannersSensor(coordinator)]
    for tracker in plan.trackers:
        entities.append(RoomSensor(coordinator, tracker))
        entities.append(PositionSensor(coordinator, tracker, "position_x"))
        entities.append(PositionSensor(coordinator, tracker, "position_y"))
    async_add_entities(entities)


@callback
def _async_remove_stale(hass: HomeAssistant, entry_id: str, plan: Floorplan) -> None:
    """Remove the entities and devices of trackers that are no longer in the plan."""
    wanted_ids = {f"{t.key}_{kind}" for t in plan.trackers for kind in KINDS} | {ACTIVE_SCANNERS}
    entities = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(entities, entry_id):
        if entry.unique_id not in wanted_ids:
            entities.async_remove(entry.entity_id)
    wanted_devices = {(DOMAIN, t.key) for t in plan.trackers} | {(DOMAIN, HUB)}
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
    """The room the tracker is in; unknown while no scanner sees it or the room has no name.

    The attributes change with every advertisement: the recorder keeps the
    room only, the timeline keeps the way.
    """

    _unrecorded_attributes = frozenset({"x", "y", "nearest_scanner", "scanner_count", "distances"})

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, tracker, "room")

    @property
    def native_value(self) -> str | None:
        """Return the room name."""
        position = self.position
        return (position.room or None) if position is not None and position.seen else None

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
            "area_id": plan.area_of(position.room),
        }


class PositionSensor(TrackerEntity, SensorEntity):
    """One coordinate of the tracker on the plan, in metres.

    Rounded to a decimetre: the smoothed position creeps by millimetres, and
    every new value would be a row in the recorder.
    """

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_suggested_display_precision = POSITION_DIGITS

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker, kind: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, tracker, kind)
        self._axis = kind[-1]

    @property
    def native_value(self) -> float | None:
        """Return the coordinate."""
        position = self.position
        if position is None or position.x is None or position.y is None:
            return None
        return round(position.x if self._axis == "x" else position.y, POSITION_DIGITS)


class ActiveScannersSensor(SensorEntity):
    """How many scanners of the plan received anything within the last minute.

    Polled, because a scanner that falls silent changes no position.
    """

    _attr_has_entity_name = True
    _attr_translation_key = ACTIVE_SCANNERS
    _attr_unique_id = ACTIVE_SCANNERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = True

    def __init__(self, coordinator: FloorplanCoordinator) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, HUB)}, name=NAME)

    async def async_added_to_hass(self) -> None:
        """Take the first value at once."""
        self._update()

    async def async_update(self) -> None:
        """Count the scanners."""
        self._update()

    @callback
    def _update(self) -> None:
        plan = self.coordinator.plan
        alive = {
            scanner.source.upper()
            for scanner in async_current_scanners(self.hass)
            if scanner.time_since_last_detection() <= SCANNER_ACTIVE_SECONDS
        }
        active = [s.name for s in plan.scanners if s.source in alive]
        inactive = [s.name for s in plan.scanners if s.source not in alive]
        self._attr_native_value = len(active)
        self._attr_extra_state_attributes = {
            "total": len(plan.scanners),
            "active": active,
            "inactive": inactive,
        }
