"""Presence per tracker: home while a scanner saw it within away_seconds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import BaseScannerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FloorplanCoordinator
from .entity import TrackerEntity, async_follow_trackers, tracker_device
from .model import Tracker

if TYPE_CHECKING:
    from . import FloorplanConfigEntry

# The coordinator updates every entity; nothing to limit
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloorplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the presence of every tracker, also of one added later."""
    coordinator = entry.runtime_data.coordinator
    async_follow_trackers(entry, async_add_entities, lambda t: [PresenceTracker(coordinator, t)])


class PresenceTracker(TrackerEntity, BaseScannerEntity):
    """Home while a scanner of the plan saw the tracker within away_seconds.

    Unknown right after a start of Home Assistant until the tracker is seen or
    away_seconds passed, so a restart does not look like leaving home.
    """

    _attr_source_type = SourceType.BLUETOOTH_LE

    def __init__(self, coordinator: FloorplanCoordinator, tracker: Tracker) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator, tracker, "presence")
        self._device = tracker_device(tracker)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the tracker's device, which the sensors share."""
        return self._device

    @property
    def is_connected(self) -> bool | None:
        """Return whether the tracker is home."""
        position = self.position
        return position.present if position is not None else None
