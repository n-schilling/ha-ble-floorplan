"""Sensors per tracker: the room, and on request the position for diagnostics; the trackers at home."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .catalog import alive_sources
from .const import CONF_POSITION_SENSORS, DEFAULT_POSITION_SENSORS, DOMAIN, NAME
from .coordinator import FloorplanCoordinator
from .entity import HUB, TrackerEntity, async_follow_trackers, async_remove_stale_devices
from .model import Floorplan, Tracker

if TYPE_CHECKING:
    from . import FloorplanConfigEntry

# The coordinator updates every entity; nothing to limit
PARALLEL_UPDATES = 0

KINDS = ("room", "presence")
POSITION_KINDS = ("position_x", "position_y")
ACTIVE_SCANNERS = "active_scanners"
TRACKERS_HOME = "trackers_home"
# The problem sensor of binary_sensor.py: kept when the stale entities are removed
UNREACHABLE = "unreachable"
# Decimals of the position sensors
POSITION_DIGITS = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloorplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors of every tracker, also of one added later, and drop those no longer wanted."""
    coordinator = entry.runtime_data.coordinator
    positions = entry.options.get(CONF_POSITION_SENSORS, DEFAULT_POSITION_SENSORS)
    kinds = KINDS + POSITION_KINDS if positions else KINDS
    _async_remove_stale(hass, entry.entry_id, coordinator.plan, kinds)
    async_add_entities([ActiveScannersSensor(coordinator), TrackersHomeSensor(coordinator)])

    def _create(tracker: Tracker) -> list[SensorEntity]:
        entities: list[SensorEntity] = [RoomSensor(coordinator, tracker)]
        if positions:
            entities.extend(PositionSensor(coordinator, tracker, kind) for kind in POSITION_KINDS)
        return entities

    async_follow_trackers(entry, async_add_entities, _create)


@callback
def _async_remove_stale(
    hass: HomeAssistant, entry_id: str, plan: Floorplan, kinds: tuple[str, ...]
) -> None:
    """Remove the devices of trackers no longer in the plan and the entities not wanted."""
    wanted_ids = {f"{t.key}_{kind}" for t in plan.trackers for kind in kinds} | {
        ACTIVE_SCANNERS,
        TRACKERS_HOME,
        UNREACHABLE,
    }
    entities = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(entities, entry_id):
        if entry.unique_id not in wanted_ids:
            entities.async_remove(entry.entity_id)
    async_remove_stale_devices(hass, entry_id, plan)


class RoomSensor(TrackerEntity, SensorEntity):
    """The room the tracker is in; unknown once it counts as away or the room has no name.

    A short gap in the readings keeps the last room. The state changes only
    with the room: the position, the nearest scanner and the distances change
    with every advertisement and would write a recorder row each time, so
    they are on the page and in the timeline instead.
    """

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, tracker, "room")

    @property
    def native_value(self) -> str | None:
        """Return the room name."""
        position = self.position
        return (position.room or None) if position is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the Home Assistant area of the room."""
        room = self.native_value
        return {"area_id": self.coordinator.plan.area_of(room)} if room is not None else {}


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
        alive = alive_sources(self.hass)
        watched = [s for s in plan.scanners if not s.paused]
        active = [s.name for s in watched if s.source in alive]
        inactive = [s.name for s in watched if s.source not in alive]
        self._attr_native_value = len(active)
        self._attr_extra_state_attributes = {
            "total": len(watched),
            "paused": [s.name for s in plan.scanners if s.paused],
            "active": active,
            "inactive": inactive,
        }


class TrackersHomeSensor(CoordinatorEntity[FloorplanCoordinator], SensorEntity):
    """How many trackers are home, with the list of all trackers for dashboards.

    The list names every tracker with the entities that tell where it is, so a
    card needs no search by name. It follows the registries: a tracker's
    entities registered later, another entity ID or another name of its device
    write it again.
    """

    _attr_has_entity_name = True
    _attr_translation_key = TRACKERS_HOME
    _attr_unique_id = TRACKERS_HOME
    _attr_state_class = SensorStateClass.MEASUREMENT
    # Names and entity IDs are for dashboards now, not for the history
    _unrecorded_attributes = frozenset({"tracker_list"})

    def __init__(self, coordinator: FloorplanCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, HUB)}, name=NAME)

    async def async_added_to_hass(self) -> None:
        """Follow the registries."""
        await super().async_added_to_hass()
        for event_type in (er.EVENT_ENTITY_REGISTRY_UPDATED, dr.EVENT_DEVICE_REGISTRY_UPDATED):
            self.async_on_remove(self.hass.bus.async_listen(event_type, self._registry_changed))

    @callback
    def _registry_changed(self, event: Event[Any]) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        """Return the number of trackers a scanner saw within away_seconds."""
        positions = self.coordinator.data
        return sum(
            1
            for tracker in self.coordinator.plan.trackers
            if not tracker.paused
            and (position := positions.get(tracker.key)) is not None
            and position.present
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return every tracker with its name and the entities of its room and presence."""
        entities = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        trackers = []
        for tracker in self.coordinator.plan.trackers:
            device = devices.async_get_device(identifiers={(DOMAIN, tracker.key)})
            name = (device.name_by_user or device.name) if device is not None else None
            trackers.append(
                {
                    "name": name or tracker.name,
                    "room_entity": entities.async_get_entity_id(
                        "sensor", DOMAIN, f"{tracker.key}_room"
                    ),
                    "presence_entity": entities.async_get_entity_id(
                        "device_tracker", DOMAIN, f"{tracker.key}_presence"
                    ),
                }
            )
        return {"tracker_list": trackers}
