"""The problem sensor: on while a scanner of the plan receives nothing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .catalog import alive_sources
from .const import DOMAIN, NAME
from .coordinator import FloorplanCoordinator
from .entity import HUB
from .sensor import UNREACHABLE

if TYPE_CHECKING:
    from . import FloorplanConfigEntry

# Reads what Home Assistant's Bluetooth stack holds; nothing to limit
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FloorplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the problem sensor."""
    async_add_entities([UnreachableSensor(entry.runtime_data.coordinator)])


class UnreachableSensor(BinarySensorEntity):
    """On while a scanner of the plan received nothing within the last minute.

    The positions then lack what that scanner would hear. Off until Home
    Assistant has started: before that the scanners of other integrations are
    not there yet, which is no problem to report. Paused scanners do not count.
    Polled, because a scanner that falls silent changes no position.
    """

    _attr_has_entity_name = True
    _attr_translation_key = UNREACHABLE
    _attr_unique_id = UNREACHABLE
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True
    # The names are for automations now, not for the history
    _unrecorded_attributes = frozenset({"scanners"})

    def __init__(self, coordinator: FloorplanCoordinator) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, HUB)}, name=NAME)

    async def async_added_to_hass(self) -> None:
        """Take the first value at once."""
        self._update()

    async def async_update(self) -> None:
        """Look for silent scanners."""
        self._update()

    @callback
    def _update(self) -> None:
        silent: list[str] = []
        if self.hass.state is CoreState.running:
            alive = alive_sources(self.hass)
            silent = [
                s.name
                for s in self.coordinator.plan.scanners
                if not s.paused and s.source not in alive
            ]
        self._attr_is_on = bool(silent)
        self._attr_extra_state_attributes = {"scanners": silent}
