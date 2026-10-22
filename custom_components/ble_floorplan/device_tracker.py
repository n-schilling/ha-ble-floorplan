"""Presence per tracker: home while a scanner saw it within away_seconds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import BaseScannerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FloorplanCoordinator
from .model import Tracker

if TYPE_CHECKING:
    from . import FloorplanConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloorplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the presence of every tracker."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(PresenceTracker(coordinator, t) for t in coordinator.plan.trackers)


class PresenceTracker(CoordinatorEntity[FloorplanCoordinator], BaseScannerEntity):
    """Home while a scanner of the plan saw the tracker within away_seconds.

    Unknown right after a start of Home Assistant until the tracker is seen or
    away_seconds passed, so a restart does not look like leaving home.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "presence"
    _attr_source_type = SourceType.BLUETOOTH_LE

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator)
        self._key = tracker.key
        self._attr_unique_id = f"{tracker.key}_presence"
        connections = {(CONNECTION_BLUETOOTH, tracker.address)} if tracker.address else set()
        self._device = DeviceInfo(
            identifiers={(DOMAIN, tracker.key)}, connections=connections, name=tracker.name
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the tracker's device, which the sensors share."""
        return self._device

    @property
    def is_connected(self) -> bool | None:
        """Return whether the tracker is home."""
        position = self.coordinator.data.get(self._key)
        return position.present if position is not None else None
