"""The floor plan in storage."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.const import STORAGE_KEY
from custom_components.ble_floorplan.model import Floorplan
from custom_components.ble_floorplan.store import FloorplanStore

from . import make_plan


async def test_load_empty(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Nothing stored yet: an empty plan."""
    store = FloorplanStore(hass)
    assert await store.async_load() == Floorplan()
    assert store.plan == Floorplan()


async def test_load_and_save(hass: HomeAssistant, storage: dict[str, Any]) -> None:
    """The stored plan is loaded; a save writes it and tells the listeners."""
    store = FloorplanStore(hass)
    plan = await store.async_load()
    assert plan == make_plan()
    listener = MagicMock()
    remove = store.async_add_listener(listener)
    new_plan = make_plan(settings={"max_distance": 9})
    await store.async_save(new_plan)
    assert store.plan == new_plan
    assert storage[STORAGE_KEY]["data"]["settings"]["max_distance"] == 9.0
    listener.assert_called_once_with()
    remove()
    await store.async_save(plan)
    listener.assert_called_once_with()
