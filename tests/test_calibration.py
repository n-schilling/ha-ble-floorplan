"""The calibration runs in storage."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import probatio
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant

from custom_components.ble_floorplan.calibration import CalibrationRun, CalibrationStore
from custom_components.ble_floorplan.const import CALIBRATION_STORAGE_KEY

RUN: dict[str, Any] = {
    "id": "01RUN",
    "tracker": "tag",
    "x": 2.0,
    "y": 2.0,
    "height": 0.3,
    "started": "2026-01-01T00:00:00+00:00",
    "duration": 42.0,
    "samples": {"living": [[0.5, -60], [1.5, -61]]},
}


def _stored(hass_storage: dict[str, Any], runs: list[dict[str, Any]]) -> None:
    hass_storage[CALIBRATION_STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": CALIBRATION_STORAGE_KEY,
        "data": {"runs": runs},
    }


async def test_load_empty(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Nothing stored: no runs, nothing active."""
    store = CalibrationStore(hass)
    assert await store.async_load() == []
    assert store.active is None
    assert store.finished == []
    assert store.as_event() == {"active": None, "runs": []}
    assert store.get("x") is None


async def test_load_round_trip(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """A stored run is loaded with its samples as tuples; summaries carry the counts."""
    _stored(hass_storage, [RUN])
    store = CalibrationStore(hass)
    runs = await store.async_load()
    assert len(runs) == 1
    run = runs[0]
    assert run.samples == {"living": [(0.5, -60.0), (1.5, -61.0)]}
    assert not run.running
    assert run.as_dict() == {**RUN, "samples": {"living": [[0.5, -60.0], [1.5, -61.0]]}}
    assert run.summary() == {
        "id": "01RUN",
        "tracker": "tag",
        "x": 2.0,
        "y": 2.0,
        "height": 0.3,
        "started": "2026-01-01T00:00:00+00:00",
        "duration": 42.0,
        "running": False,
        "counts": {"living": 2},
    }
    assert store.get("01RUN") is run
    assert store.finished == [run]
    # Nothing was written back
    assert hass_storage[CALIBRATION_STORAGE_KEY]["data"] == {"runs": [RUN]}


async def test_load_closes_a_run_that_was_going(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Home Assistant stopped during a run: it ends with its last sample, and is saved so."""
    _stored(
        hass_storage,
        [
            {**RUN, "duration": None},
            {**RUN, "id": "02RUN", "duration": None, "samples": {}},
        ],
    )
    store = CalibrationStore(hass)
    runs = await store.async_load()
    assert runs[0].duration == 1.5
    assert runs[1].duration == 0.0
    assert store.active is None
    stored = hass_storage[CALIBRATION_STORAGE_KEY]["data"]["runs"]
    assert stored[0]["duration"] == 1.5
    assert stored[1]["duration"] == 0.0


async def test_load_invalid(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Broken storage is refused rather than guessed at."""
    _stored(hass_storage, [{**RUN, "samples": {"living": [[1]]}}])
    with pytest.raises(probatio.Invalid):
        await CalibrationStore(hass).async_load()


async def test_start_record_stop(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """A run is written at the start, along the way after a delay, and at the stop."""
    store = CalibrationStore(hass)
    await store.async_load()
    listener = MagicMock()
    remove = store.async_add_listener(listener)
    run = await store.async_start("tag", 2.0, 3.0, 0.4, 1000.0)
    assert store.active is run
    assert run.running
    assert run.summary()["running"]
    assert run.started.endswith("+00:00")
    assert store.as_event() == {"active": run.id, "runs": [run.summary()]}
    listener.assert_called_once_with()
    stored = hass_storage[CALIBRATION_STORAGE_KEY]["data"]["runs"]
    assert stored[0]["duration"] is None
    assert stored[0]["samples"] == {}
    # A sample from before the start is not the run's
    store.add_sample("living", 999.0, -50)
    store.add_sample("living", 1000.5, -60)
    store.add_sample("kitchen", 1002.0, -70)
    store.add_sample("living", 1003.0, -62)
    assert run.samples == {"living": [(0.5, -60), (3.0, -62)], "kitchen": [(2.0, -70)]}
    assert run.summary()["counts"] == {"living": 2, "kitchen": 1}
    # Not written yet, then written after the delay, with what came in the meantime
    assert hass_storage[CALIBRATION_STORAGE_KEY]["data"]["runs"][0]["samples"] == {}
    freezer.tick(5)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass_storage[CALIBRATION_STORAGE_KEY]["data"]["runs"][0]["samples"] == {}
    store.add_sample("living", 1004.0, -63)
    freezer.tick(6)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    written = hass_storage[CALIBRATION_STORAGE_KEY]["data"]["runs"][0]["samples"]
    assert written["kitchen"] == [[2.0, -70]]
    assert written["living"] == [[0.5, -60], [3.0, -62], [4.0, -63]]
    # The next sample schedules the next write
    store.add_sample("living", 1005.0, -64)
    freezer.tick(11)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(hass_storage[CALIBRATION_STORAGE_KEY]["data"]["runs"][0]["samples"]["living"]) == 4
    with pytest.raises(RuntimeError):
        await store.async_start("tag", 0.0, 0.0, 0.0, 1004.0)
    stopped = await store.async_stop(1010.0)
    assert stopped is run
    assert run.duration == 10.0
    assert store.active is None
    assert store.finished == [run]
    assert listener.call_count == 2
    assert hass_storage[CALIBRATION_STORAGE_KEY]["data"]["runs"][0]["duration"] == 10.0
    # No run going: nothing is recorded, nothing to stop
    store.add_sample("living", 1011.0, -60)
    assert run.summary()["counts"] == {"living": 4, "kitchen": 1}
    with pytest.raises(RuntimeError):
        await store.async_stop(1012.0)
    remove()
    await store.async_start("tag", 0.0, 0.0, 0.0, 1020.0)
    assert listener.call_count == 2


async def test_stop_never_negative(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """A clock that went backwards still gives a duration of zero."""
    store = CalibrationStore(hass)
    await store.async_start("tag", 0.0, 0.0, 0.0, 1000.0)
    run = await store.async_stop(999.0)
    assert run.duration == 0.0


async def test_delete(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Deleting a finished run, the active run, and one that is not there."""
    _stored(hass_storage, [RUN])
    store = CalibrationStore(hass)
    await store.async_load()
    listener = MagicMock()
    store.async_add_listener(listener)
    active = await store.async_start("tag", 1.0, 1.0, 0.0, 1000.0)
    assert len(store.runs) == 2
    assert await store.async_delete(active.id)
    assert store.active is None
    assert [r.id for r in store.runs] == ["01RUN"]
    assert await store.async_delete("01RUN")
    assert store.runs == []
    assert not await store.async_delete("01RUN")
    assert hass_storage[CALIBRATION_STORAGE_KEY]["data"] == {"runs": []}
    assert listener.call_count == 3


def test_run_from_dict_defaults() -> None:
    """Height, duration and samples are optional in storage."""
    run = CalibrationRun.from_dict(
        {
            "id": "x",
            "tracker": "tag",
            "x": 1.0,
            "y": 2.0,
            "height": 0.0,
            "started": "s",
            "duration": None,
            "samples": {},
        }
    )
    assert run.running
    assert run.samples == {}
