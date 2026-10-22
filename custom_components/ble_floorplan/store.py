"""Persistence of the floor plan in Home Assistant's storage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .model import Floorplan


class FloorplanStore:
    """The floor plan, loaded once and saved on every change."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._listeners: list[CALLBACK_TYPE] = []
        self.plan = Floorplan()

    async def async_load(self) -> Floorplan:
        """Load the plan; an empty plan when nothing was stored yet."""
        if (data := await self._store.async_load()) is not None:
            self.plan = Floorplan.from_dict(data)
        return self.plan

    async def async_save(self, plan: Floorplan) -> None:
        """Save a new plan and tell the listeners."""
        self.plan = plan
        await self._store.async_save(plan.as_dict())
        for listener in list(self._listeners):
            listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call the listener after every save; returns the function that removes it."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove
