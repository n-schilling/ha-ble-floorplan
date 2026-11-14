"""Floors, buildings and stairs: one site, levels above each other, the level that fits."""

from __future__ import annotations

from collections.abc import Callable
import math
from typing import Any

import probatio
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import floor_registry as fr

from custom_components.ble_floorplan.catalog import (
    LayoutProblem,
    layout_yaml,
    with_areas,
    with_layout,
)
from custom_components.ble_floorplan.engine import Heard, LevelTracker, misfit
from custom_components.ble_floorplan.model import DEFAULT_FLOOR, Floorplan

from . import SCANNER_BEDROOM, SCANNER_KITCHEN, SCANNER_LIVING, TAG, FakeScanner, scanner_device
from .conftest import ScannerDevices

OFFICE_SOURCE = "AA:BB:CC:DD:EE:05"

HOUSE: dict[str, Any] = {
    "floors": [
        {"key": "eg", "name": "Ground floor", "building": "House"},
        {"key": "og", "name": "Upper floor", "building": "House", "elevation": 3.0},
        {"key": "garage", "name": "Garage", "building": "Garage"},
    ],
    "rooms": [
        {"name": "Living room", "x": 0, "y": 0, "w": 6, "h": 5},
        {"name": "Kitchen", "x": 6, "y": 0, "w": 4, "h": 5},
        {"name": "Bedroom", "x": 0, "y": 0, "w": 6, "h": 5, "floor": "og"},
        {"name": "Office", "x": 6, "y": 0, "w": 4, "h": 5, "floor": "og"},
        {"name": "Garden", "x": 0, "y": 5, "w": 14, "h": 4, "outdoor": True},
        {"name": "Garage", "x": 11, "y": 0, "w": 3, "h": 5, "floor": "garage"},
    ],
    "openings": [[6, 1, 6, 2.5], [6, 1, 6, 2.5, "og"], [2, 5, 3, 5]],
    "stairs": [{"floor": "eg", "to": "og", "x": 4, "y": 3, "w": 1.5, "h": 1.5}],
    "scanners": [
        {"key": "living", "name": "Living", "source": SCANNER_LIVING, "x": 1, "y": 1, "z": 1},
        {"key": "kitchen", "name": "Kitchen", "source": SCANNER_KITCHEN, "x": 9, "y": 1, "z": 1},
        {
            "key": "bedroom",
            "name": "Bedroom",
            "source": SCANNER_BEDROOM,
            "x": 1,
            "y": 4,
            "z": 1,
            "floor": "og",
        },
        {
            "key": "office",
            "name": "Office",
            "source": OFFICE_SOURCE,
            "x": 9,
            "y": 4,
            "z": 1,
            "floor": "og",
        },
    ],
    "trackers": [{"key": "tag", "name": "Tag", "address": TAG, "height": 1.0, "ref_power": -60}],
    "settings": {"floor_hold_seconds": 5, "jump_distance": 0, "smoothing_seconds": 0.1},
}


def _plan(**overrides: Any) -> Floorplan:
    return Floorplan.from_dict({**HOUSE, **overrides})


def test_round_trip_and_defaults() -> None:
    """Floors and stairs survive a round trip; things without a floor lie on the first."""
    plan = _plan()
    data = plan.as_dict()
    assert data["floors"][1] == {
        "key": "og",
        "name": "Upper floor",
        "building": "House",
        "elevation": 3.0,
        "height": 2.5,
    }
    assert data["rooms"][0]["floor"] == "eg"
    assert data["openings"][0] == [6, 1, 6, 2.5, "eg"]
    assert data["scanners"][0]["floor"] == "eg"
    assert data["stairs"][0]["points"] == [[4, 3], [5.5, 3], [5.5, 4.5], [4, 4.5]]
    assert Floorplan.from_dict(data) == plan
    # A plan without floors has the default floor, and nothing of it in the stored data
    single = Floorplan.from_dict({"rooms": HOUSE["rooms"][:2], "openings": [[6, 1, 6, 2.5]]})
    assert single.floor_list == (DEFAULT_FLOOR,)
    assert single.levels == (0.0,)
    assert single.on_level(0.0) is single
    stored = single.as_dict()
    assert "floors" not in stored and "stairs" not in stored
    assert "floor" not in stored["rooms"][0]
    assert stored["openings"] == [[6, 1, 6, 2.5]]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"rooms": [{"name": "A", "x": 0, "y": 0, "w": 1, "h": 1, "floor": "attic"}]}, "no floor"),
        ({"openings": [[0, 0, 1, 0, "attic"]]}, "no floor"),
        ({"stairs": [{"floor": "eg", "to": "eg", "x": 0, "y": 0, "w": 1, "h": 1}]}, "different"),
        ({"stairs": [{"floor": "eg", "to": "attic", "x": 0, "y": 0, "w": 1, "h": 1}]}, "no floor"),
        ({"floors": [{"key": "eg"}, {"key": "eg"}]}, "unique"),
    ],
)
def test_invalid_floors(change: dict[str, Any], message: str) -> None:
    """References to floors are checked."""
    data = {**HOUSE, "scanners": [], **change}
    with pytest.raises(probatio.Invalid, match=message):
        Floorplan.from_dict(data)


def test_levels_and_lookups() -> None:
    """Floors at one elevation form a level; the plan of a level holds only its rooms."""
    plan = _plan()
    assert plan.levels == (0.0, 3.0)
    upper = plan.on_level(3.0)
    assert [r.name for r in upper.rooms] == ["Bedroom", "Office"]
    assert upper.openings == ((6, 1, 6, 2.5, "og"),)
    assert len(upper.stairs) == 1
    ground = plan.on_level(0.0)
    assert [r.name for r in ground.rooms] == ["Living room", "Kitchen", "Garden", "Garage"]
    assert plan.floor("nope") is plan.floors[0]
    assert plan.scanner_height(plan.scanners[2]) == 4.0
    assert plan.building_of(plan.rooms[0]) == "House"
    assert plan.building_of(plan.rooms[4]) is None
    assert plan.building_of(None) is None
    assert plan.stairs_between("og", "eg") == plan.stairs
    stairs = plan.stairs[0]
    assert stairs.near(4.5, 3.5)
    assert stairs.near(3.2, 3.5)
    assert not stairs.near(1.0, 1.0)


def test_exterior_doors_without_inner_walls() -> None:
    """With walls off, only a step that leaves the building needs a door."""
    plan = _plan(settings={"walls": False}).on_level(0.0)
    # Inside the house: straight through the wall
    assert plan.move((5.5, 4), (6.5, 4), (7, 4)) == (6.5, 4)
    # Out into the garden: through the door instead
    out = plan.move((0.5, 4.5), (0.5, 5.5), (0.5, 6))
    assert out != (0.5, 5.5)
    # From the garden nothing holds it: an outdoor room is no building
    assert plan.move((0.5, 6), (0.5, 4.5), (0.5, 4)) == (0.5, 4.5)
    # Both off: anywhere
    free = _plan(settings={"walls": False, "exterior_doors": False}).on_level(0.0)
    assert free.move((0.5, 4.5), (0.5, 5.5), (0.5, 6)) == (0.5, 5.5)


def test_misfit() -> None:
    """The misfit counts the height: the right level fits exactly, the other not."""
    heard = [Heard(1, 1, 4, math.dist((2, 2, 4), (1, 1, 4))), Heard(9, 1, 1, 9.0)]
    assert misfit((2, 2), heard[:1], 4.0) == pytest.approx(0.0)
    assert misfit((2, 2), heard[:1], 1.0) > 1.0
    # Nearer than heard counts a quarter
    assert misfit((9, 1), heard[1:], 1.0) == pytest.approx(9.0)


def test_level_tracker() -> None:
    """First the best; then another level only better by the margin, held, and over stairs."""
    plan = _plan()
    levels = LevelTracker()
    assert levels.current("tag") is None
    assert levels.level("tag", {0.0: 0.4, 3.0: 2.0}, 0.0, plan, None) == 0.0
    # Better, but not by the margin
    assert levels.level("tag", {0.0: 0.4, 3.0: 0.1}, 1.0, plan, (1, 1)) == 0.0
    # Better by the margin, not yet held long enough
    assert levels.level("tag", {0.0: 2.0, 3.0: 0.2}, 2.0, plan, (1, 1)) == 0.0
    assert levels.level("tag", {0.0: 2.0, 3.0: 0.2}, 6.0, plan, (1, 1)) == 0.0
    # Held, but far from the stairs; at the stairs it goes up
    assert levels.level("tag", {0.0: 2.0, 3.0: 0.2}, 8.0, plan, (4.5, 3.5)) == 3.0
    assert levels.current("tag") == 3.0
    # Without stairs on the way, it changes after six times the hold time anyway
    assert levels.level("tag", {0.0: 0.1, 3.0: 2.0}, 10.0, plan, (1, 1)) == 3.0
    assert levels.level("tag", {0.0: 0.1, 3.0: 2.0}, 20.0, plan, (1, 1)) == 3.0
    assert levels.level("tag", {0.0: 0.1, 3.0: 2.0}, 40.0, plan, None) == 0.0
    # A level that no longer fits at all keeps the current one
    assert levels.level("tag", {3.0: 0.1}, 41.0, plan, None) == 0.0
    # Stairs off or no stairs: held long enough is enough
    for other in (
        _plan(settings={"stairs_only": False, "floor_hold_seconds": 5}),
        _plan(stairs=[]),
    ):
        levels.reset("tag")
        levels.level("tag", {0.0: 0.1, 3.0: 2.0}, 0.0, other, None)
        levels.level("tag", {0.0: 2.0, 3.0: 0.1}, 1.0, other, (1, 1))
        assert levels.level("tag", {0.0: 2.0, 3.0: 0.1}, 7.0, other, (1, 1)) == 3.0


@pytest.fixture
def stored_plan() -> dict[str, Any]:
    """The house in storage."""
    return HOUSE


def _hear(
    scanners: dict[str, FakeScanner], office: FakeScanner, x: float, y: float, z: float, t: float
) -> list[Any]:
    """Adverts of the tag at x, y and the height z above the ground, exactly as the model has it.

    A scanner on the other floor hears it 10 dB weaker, through the ceiling.
    """
    places = {
        "living": (1, 1, 1),
        "kitchen": (9, 1, 1),
        "bedroom": (1, 4, 4),
        "office": (9, 4, 4),
    }
    found = {**scanners, "office": office}
    return [
        scanner_device(
            found[key],
            TAG,
            -60  # type: ignore[arg-type]
            - 30 * math.log10(math.dist((x, y, z), place))
            - (10 if (place[2] > 3) != (z > 3) else 0),
            t,
        )
        for key, place in places.items()
    ]


async def test_coordinator_finds_the_level(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    scanner_devices: ScannerDevices,
    scanners: dict[str, FakeScanner],
    clock: Callable[[float], None],
) -> None:
    """The tag upstairs is placed on the upper floor, in its room; a short gap keeps the floor."""
    coordinator = entry.runtime_data.coordinator
    office = FakeScanner(OFFICE_SOURCE, "Office")
    scanner_devices[TAG] = _hear(scanners, office, 2.0, 2.0, 4.0, 1000.0)
    clock(1001.0)
    await coordinator.async_refresh()
    tag = coordinator.data["tag"]
    assert tag.level == 3.0
    assert tag.floor == "og"
    assert tag.room == "Bedroom"
    assert tag.as_dict()["floor"] == "og"
    # To the stairs upstairs, then down: after the hold time it follows to the ground floor
    for t in range(2, 22):
        z = 4.0 if t < 8 else 1.0
        scanner_devices[TAG] = _hear(scanners, office, 4.5, 3.5, z, 1000.0 + t)
        clock(1001.0 + t)
        await coordinator.async_refresh()
        if t == 7:
            assert coordinator.data["tag"].level == 3.0
    tag = coordinator.data["tag"]
    assert tag.level == 0.0
    assert tag.floor == "eg"
    # Not heard for a moment: room and floor stay
    scanner_devices[TAG] = []
    clock(1100.0)
    await coordinator.async_refresh()
    tag = coordinator.data["tag"]
    assert not tag.seen
    assert (tag.room, tag.floor, tag.level) == ("Living room", "eg", 0.0)
    # Away: all of it gone
    clock(1300.0)
    await coordinator.async_refresh()
    tag = coordinator.data["tag"]
    assert (tag.room, tag.floor, tag.level) == (None, None, None)


async def test_ha_floors(hass: HomeAssistant) -> None:
    """A floor names its floor of Home Assistant by id or name; an unknown one is refused."""
    registry = fr.async_get(hass)
    upstairs = registry.async_create("Obergeschoss")
    plan = _plan(
        floors=[
            {"key": "eg", "ha_floor": None} if False else {"key": "eg"},
            {"key": "og", "elevation": 3, "ha_floor": "Obergeschoss"},
            {"key": "garage", "ha_floor": upstairs.floor_id},
        ]
    )
    resolved = with_areas(hass, plan)
    assert resolved.floors[1].ha_floor == upstairs.floor_id
    assert resolved.floors[2].ha_floor == upstairs.floor_id
    with pytest.raises(LayoutProblem, match="no floor Keller"):
        with_areas(hass, _plan(floors=[*HOUSE["floors"], {"key": "k", "ha_floor": "Keller"}]))


def test_layout_with_floors() -> None:
    """The layout text holds floors and stairs; a scanner on a floor left out is refused."""
    plan = _plan()
    text = layout_yaml(plan)
    assert "floors:" in text and "stairs:" in text
    assert with_layout(plan, text) == plan
    without_upper = text.replace("floor: og", "floor: eg")
    with pytest.raises(LayoutProblem, match="no floor og"):
        with_layout(plan, "floors:\n  - {key: eg}\nrooms: []\n")
    assert with_layout(plan, without_upper).rooms[2].floor == "eg"


def test_calibration_on_floors() -> None:
    """A run upstairs: the guide counts it there; the solver measures in 3D and gives back the ceiling."""
    from custom_components.ble_floorplan.calibration import CalibrationRun, guide, setup_matches
    from custom_components.ble_floorplan.solver import observations

    plan = _plan()
    setup = {s.key: (s.x, s.y, plan.scanner_height(s)) for s in plan.scanners}
    samples = {"living": [(float(i), -80.0) for i in range(5)]}
    run = CalibrationRun(
        "r", "tag", 2, 2, 1.0, "2026-11-14T10:00:00+00:00", 60.0, samples, setup, "og"
    )
    assert setup_matches(run, plan) is True
    assert run.summary()["floor"] == "og"
    assert CalibrationRun.from_dict({**run.as_dict(), "duration": 60.0}).floor == "og"
    rooms = guide(plan, [run])["tag"]
    assert {"room": "Bedroom", "floor": "og", "runs": 1} in rooms
    assert {"room": "Living room", "floor": "eg", "runs": 0} in rooms
    (obs,) = observations(plan, [run])
    assert obs.distance == pytest.approx(math.dist((2, 2, 4), (1, 1, 1)))
    assert obs.rssi == -70.0
    # A run without a floor lies on the first
    ground = CalibrationRun(
        "g", "tag", 2, 2, 1.0, "2026-11-14T10:00:00+00:00", 60.0, samples, setup
    )
    (obs,) = observations(plan, [ground])
    assert obs.rssi == -80.0
    assert "floor" not in ground.summary()


async def test_ws_start_on_a_floor(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any
) -> None:
    """calibration/start takes the floor; an unknown floor is refused."""
    from custom_components.ble_floorplan.const import WS_CALIBRATION_START

    client = await hass_ws_client(hass)
    base = {"type": WS_CALIBRATION_START, "tracker": "tag", "x": 2, "y": 2}
    await client.send_json_auto_id({**base, "floor": "attic"})
    msg = await client.receive_json()
    assert msg["error"]["code"] == "not_found"
    await client.send_json_auto_id({**base, "floor": "og"})
    msg = await client.receive_json()
    assert msg["result"]["floor"] == "og"
    assert msg["result"]["scanners"]["bedroom"] == [1.0, 4.0, 4.0]


async def test_history_keeps_the_level(hass: HomeAssistant) -> None:
    """A point upstairs keeps its level; a change of level alone is a point; 0 is left out."""
    from custom_components.ble_floorplan.coordinator import TrackerPosition
    from custom_components.ble_floorplan.history import HistoryStore, to_wire

    history = HistoryStore(hass)
    now = 1793016000.0
    await history.async_load(now, 7)

    def at(level: float) -> dict[str, TrackerPosition]:
        return {
            "tag": TrackerPosition("tag", None, 1.0, 1.0, 1.0, 1.0, "Hall", None, 2, level=level)
        }

    await history.async_record(at(0.0), now, 7)
    await history.async_record(at(3.0), now + 1, 7)
    tracks = await history.async_day("2026-10-26")
    assert [p[4] for p in tracks["tag"]] == [None, 3.0]
    assert to_wire(tracks)["tag"] == [[now, 1.0, 1.0, "Hall"], [now + 1, 1.0, 1.0, "Hall", 3.0]]


def test_coverage_per_level() -> None:
    """The model and the measurement are per level; ceilings cost signal; cells keep their level."""
    from custom_components.ble_floorplan.coordinator import Reading, TrackerPosition
    from custom_components.ble_floorplan.coverage import (
        Probe,
        basis,
        cell_key,
        model,
        parse_cell,
        sample,
    )

    plan = _plan()
    ground = model(plan)
    upper = model(plan, plan.trackers[0], [Probe(2, 2)], 3.0)
    assert {r["name"] for r in ground["rooms"]} == {"Living room", "Kitchen", "Garden", "Garage"}
    assert {r["name"] for r in upper["rooms"]} == {"Bedroom", "Office"}
    # Without ceiling loss the scanners downstairs help more upstairs
    lossless = model(_plan(settings={"floor_loss": 0}), plan.trackers[0], (), 3.0)
    assert sum(c[3] for c in lossless["cells"]) > sum(
        c[3] for c in model(plan, plan.trackers[0], (), 3.0)["cells"]
    )
    assert cell_key(1, 2) == "1,2"
    assert cell_key(1, 2, 3.0) == "1,2/3.0"
    assert parse_cell("1,2/3.0") == (1, 2, 3.0)
    assert parse_cell("1,2") == (1, 2, 0.0)
    reading = Reading(-60.0, 1.0, True)
    position = TrackerPosition(
        "tag", None, 2.0, 2.0, 2.0, 2.0, "Bedroom", "bedroom", 1, {"bedroom": reading}, level=3.0
    )
    got = sample(plan, position)
    assert got is not None and got[0] == "4,4/3.0"
    assert "floor_loss" in basis(plan)["calibration"]
    single = Floorplan.from_dict({"rooms": HOUSE["rooms"][:2]})
    assert "floor_loss" not in basis(single)["calibration"]


async def test_measured_per_level(hass: HomeAssistant) -> None:
    """The measurement of a level shows only the cells sampled on it."""
    from custom_components.ble_floorplan.coverage import CoverageStore

    plan = _plan()
    store = CoverageStore(hass)
    await store.async_load(1793016000.0, 7)
    store.days["2026-10-26"] = {"tag": {"4,4/3.0": [60, 120, 120, 30.0], "4,4": [60, 60, 60, 30.0]}}
    upper = store.measured(plan, None, 3.0)
    assert [c[:2] for c in upper["cells"]] == [[4, 4]]
    assert upper["rooms"][0]["name"] == "Bedroom"
    assert store.measured(plan)["rooms"][0]["name"] == "Living room"


async def test_ws_scanner_floor(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any
) -> None:
    """set_scanner and add_scanner take a floor; unknown floors are refused."""
    from custom_components.ble_floorplan.const import WS_ADD_SCANNER, WS_SET_SCANNER

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SET_SCANNER, "key": "living", "floor": "attic"})
    assert (await client.receive_json())["error"]["code"] == "not_found"
    await client.send_json_auto_id({"type": WS_SET_SCANNER, "key": "living", "floor": "og"})
    assert (await client.receive_json())["result"]["floor"] == "og"
    base = {"type": WS_ADD_SCANNER, "source": "AA:BB:CC:DD:EE:07", "name": "Attic"}
    await client.send_json_auto_id({**base, "floor": "attic"})
    assert (await client.receive_json())["error"]["code"] == "not_found"
    await client.send_json_auto_id({**base, "floor": "garage"})
    assert (await client.receive_json())["result"]["floor"] == "garage"
    await client.send_json_auto_id({**base, "source": "AA:BB:CC:DD:EE:08"})
    assert (await client.receive_json())["result"]["floor"] == "eg"


async def test_ws_set_layout_as_data(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any
) -> None:
    """set_layout takes the drawing as data; one of yaml or layout is needed."""
    from custom_components.ble_floorplan.const import WS_SET_LAYOUT

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": WS_SET_LAYOUT})
    assert (await client.receive_json())["error"]["code"] == "invalid_format"
    layout = {k: HOUSE[k] for k in ("floors", "rooms", "openings", "stairs")}
    layout["rooms"] = [
        *layout["rooms"],
        {"name": "Attic", "x": 0, "y": 0, "w": 3, "h": 3, "floor": "og"},
    ]
    await client.send_json_auto_id({"type": WS_SET_LAYOUT, "layout": layout})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["floorplan"]["rooms"][-1]["name"] == "Attic"
    await client.send_json_auto_id({"type": WS_SET_LAYOUT, "layout": {"walls": []}})
    assert (await client.receive_json())["error"]["code"] == "invalid_format"
    await client.send_json_auto_id(
        {"type": WS_SET_LAYOUT, "layout": {"rooms": [{"name": "A", "floor": "x"}]}}
    )
    assert (await client.receive_json())["error"]["code"] == "invalid_format"


def test_layout_back_to_one_floor() -> None:
    """A layout without floors takes the scanners along to the one floor left."""
    plan = with_layout(_plan(), "rooms:\n  - {name: A, x: 0, y: 0, w: 3, h: 3}\n")
    assert plan.floors == ()
    assert {s.floor for s in plan.scanners} == {""}
