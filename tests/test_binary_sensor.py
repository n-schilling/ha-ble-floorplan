"""The problem sensor: on while a scanner of the plan receives nothing."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import FakeScanner

UNREACHABLE = "binary_sensor.ble_floorplan_scanners_unreachable"


async def test_unreachable(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanners: dict[str, FakeScanner],
    freezer: FrozenDateTimeFactory,
) -> None:
    """On while a scanner is silent, with the names; paused scanners do not count; polled."""

    async def poll() -> tuple[str, list[str]]:
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        state = hass.states.get(UNREACHABLE)
        assert state is not None
        return state.state, state.attributes["scanners"]

    registered = er.async_get(hass).async_get(UNREACHABLE)
    assert registered is not None
    assert registered.entity_category == "diagnostic"
    scanners["kitchen"].idle = 300.0
    current = [scanners["living"], scanners["kitchen"]]
    with patch(
        "custom_components.ble_floorplan.catalog.async_current_scanners",
        side_effect=lambda hass: list(current),
    ):
        # Silent for 5 minutes, and gone from Home Assistant
        assert await poll() == (STATE_ON, ["Kitchen plug", "Bedroom proxy"])
        state = hass.states.get(UNREACHABLE)
        assert state is not None
        assert state.attributes["device_class"] == "problem"

        # Paused scanners are not waited for
        store = entry.runtime_data.store
        await store.async_save(
            replace(
                store.plan,
                scanners=tuple(replace(s, paused=s.key == "bedroom") for s in store.plan.scanners),
            )
        )
        assert await poll() == (STATE_ON, ["Kitchen plug"])

        scanners["kitchen"].idle = 2.0
        assert await poll() == (STATE_OFF, [])

        # While Home Assistant starts, the scanners of other integrations are not there yet
        current.clear()
        hass.set_state(CoreState.starting)
        assert await poll() == (STATE_OFF, [])
        hass.set_state(CoreState.running)
        assert await poll() == (STATE_ON, ["Living room scanner", "Kitchen plug"])
