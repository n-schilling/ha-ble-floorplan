"""The problem sensor: on while a scanner of the plan receives nothing."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .catalog import alive_sources
from .const import DOMAIN, NAME, SCANNER_ACTIVE_SECONDS
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

    The positions then lack what that scanner would hear. Off until a minute
    after Home Assistant has started: before the start the scanners of other
    integrations are not there yet, and after it each gets the minute it is
    judged by to connect and receive something. Neither is a problem to
    report. A reload of the entry waits for nothing: the scanners are there.
    Paused scanners do not count. Polled, because a scanner that falls silent
    changes no position.
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
        # From when a silent scanner counts; None until Home Assistant has started
        self._judged_from: datetime | None = None
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, HUB)}, name=NAME)

    async def async_added_to_hass(self) -> None:
        """Take the first value at once; after a start of Home Assistant, give the scanners their minute."""
        if self.hass.state is CoreState.running:
            self._judged_from = dt_util.utcnow()
        else:
            self.async_on_remove(async_at_started(self.hass, self._started))
        self._update()

    @callback
    def _started(self, hass: HomeAssistant) -> None:
        self._judged_from = dt_util.utcnow() + timedelta(seconds=SCANNER_ACTIVE_SECONDS)

    async def async_update(self) -> None:
        """Look for silent scanners."""
        self._update()

    @callback
    def _update(self) -> None:
        silent: list[str] = []
        if self._judged_from is not None and dt_util.utcnow() >= self._judged_from:
            alive = alive_sources(self.hass)
            silent = [
                s.name
                for s in self.coordinator.plan.scanners
                if not s.paused and s.source not in alive
            ]
        self._attr_is_on = bool(silent)
        self._attr_extra_state_attributes = {"scanners": silent}
