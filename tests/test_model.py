"""Validation and round trips of the floor plan model."""

from __future__ import annotations

from typing import Any

import probatio
import pytest

from custom_components.ble_floorplan.model import (
    Floorplan,
    Scanner,
    mac_address,
    replace_scanner,
    with_calibration,
    with_scanner_position,
)

from . import FLOORPLAN, SCANNER_LIVING, TAG, make_plan


def test_round_trip() -> None:
    """What goes in comes out, with the defaults filled in and nothing personal added."""
    plan = make_plan()
    data = plan.as_dict()
    assert data["rooms"][0] == {
        "name": "Living room",
        "x": 0.0,
        "y": 0.0,
        "w": 6.0,
        "h": 5.0,
        "zone": False,
        "outdoor": False,
        "label": True,
    }
    assert data["rooms"][2]["points"] == [[0, 5], [6, 5], [6, 9], [2, 9], [2, 8], [0, 8]]
    assert data["rooms"][3]["fs"] == 0.3
    assert data["rooms"][5]["label"] is False
    assert data["openings"][0] == [6, 1, 6, 2.5]
    assert data["scanners"][0] == {
        "key": "living",
        "name": "Living room scanner",
        "source": SCANNER_LIVING,
        "x": 1.0,
        "y": 1.0,
        "z": 0.8,
        "rssi_offset": 0.0,
    }
    assert data["trackers"][0] == {
        "key": "tag",
        "name": "Tag",
        "address": TAG,
        "height": 0.3,
        "ref_power": -60.0,
    }
    assert data["trackers"][1] == {
        "key": "phone",
        "name": "Phone",
        "device_id": "phone-device-id",
        "height": 1.0,
    }
    assert data["settings"] == {
        "attenuation": 3.0,
        "ref_power_default": -55.0,
        "smoothing_seconds": 20.0,
        "min_move": 0.25,
        "max_distance": 15.0,
        "clamp": True,
        "clamp_outdoor": False,
    }
    assert Floorplan.from_dict(data) == plan


def test_empty() -> None:
    """An empty dict is an empty plan."""
    plan = Floorplan.from_dict({})
    assert plan == Floorplan()
    assert plan.extent == (0, 0)
    assert plan.room_at(1, 1) is None
    assert plan.scanner("x") is None
    assert plan.tracker("x") is None


def test_lookups() -> None:
    """Scanners and trackers by key, the rooms a tracker may be in."""
    plan = make_plan()
    assert plan.scanner("kitchen") is not None
    assert plan.tracker("phone") is not None
    assert [r.name for r in plan.inside_rooms] == ["Living room", "Kitchen", "Bedroom", "Hall"]
    assert [r.name for r in make_plan(settings={"clamp_outdoor": True}).inside_rooms][
        -1
    ] == "Balcony"
    assert make_plan(settings={"clamp": False}).inside_rooms == ()


def test_room_without_name_is_fine() -> None:
    """A corridor needs no label."""
    plan = make_plan(rooms=[{"x": 0, "y": 0, "w": 1, "h": 1}])
    assert plan.rooms[0].name == ""
    assert plan.room_at(0.5, 0.5) == ""


@pytest.mark.parametrize(
    "bad",
    [
        {"rooms": [{"name": "A", "x": 0, "y": 0, "w": 1}]},
        {
            "rooms": [
                {"name": "A", "x": 0, "y": 0, "w": 1, "h": 1, "points": [[0, 0], [1, 0], [1, 1]]}
            ]
        },
        {"rooms": [{"name": "A", "x": 0, "y": 0, "w": 0, "h": 1}]},
        {"rooms": [{"name": "A", "points": [[0, 0], [1, 0]]}]},
        {"openings": [[0, 0, 1]]},
        {"scanners": [{"key": "a", "name": "A", "source": "nonsense"}]},
        {"scanners": [{"key": "a", "name": "A", "source": "AA:BB:CC:DD:EE:0G"}]},
        {"scanners": [{"key": "Bad Key", "name": "A", "source": SCANNER_LIVING}]},
        {
            "scanners": [
                {"key": "a", "name": "A", "source": SCANNER_LIVING},
                {"key": "a", "name": "B", "source": SCANNER_LIVING},
            ]
        },
        {"trackers": [{"key": "t", "name": "T"}]},
        {"trackers": [{"key": "t", "name": "T", "address": TAG, "device_id": "x"}]},
        {
            "trackers": [
                {"key": "t", "name": "T", "address": TAG},
                {"key": "t", "name": "U", "address": TAG},
            ]
        },
        {"settings": {"attenuation": 0.5}},
        {"settings": {"ref_power_default": 5}},
        {"settings": {"max_distance": 0}},
        {"settings": {"unknown": 1}},
        {"unknown": 1},
    ],
)
def test_invalid(bad: dict[str, Any]) -> None:
    """Bad data is refused as a whole."""
    with pytest.raises(probatio.Invalid):
        Floorplan.from_dict({**FLOORPLAN, **bad})


def test_mac_address() -> None:
    """Addresses are kept upper case, as Home Assistant has them."""
    assert mac_address("aa:bb:cc:dd:ee:01") == SCANNER_LIVING
    with pytest.raises(probatio.Invalid):
        mac_address("AABBCCDDEE01")


def test_move_scanner() -> None:
    """Moving keeps everything but the place, and the height when not given."""
    plan = make_plan()
    scanner = plan.scanner("living")
    assert scanner is not None
    moved = with_scanner_position(scanner, 2.5, 3.5)
    assert (moved.x, moved.y, moved.z, moved.source) == (2.5, 3.5, 0.8, SCANNER_LIVING)
    lifted = with_scanner_position(scanner, 2.5, 3.5, 1.9)
    assert lifted.z == 1.9
    new_plan = replace_scanner(plan, lifted)
    assert new_plan.scanner("living") == lifted
    assert new_plan.scanner("kitchen") == plan.scanner("kitchen")
    assert new_plan.rooms == plan.rooms
    assert isinstance(lifted, Scanner)


def test_pair_offsets_round_trip() -> None:
    """The corrections per pair are stored as a table and looked up with a default of zero."""
    plan = make_plan(pair_offsets={"living": {"tag": -2.5, "phone": 1}})
    assert plan.pair_offset("living", "tag") == -2.5
    assert plan.pair_offset("living", "phone") == 1.0
    assert plan.pair_offset("kitchen", "tag") == 0.0
    assert plan.pair_offset("nowhere", "tag") == 0.0
    data = plan.as_dict()
    assert data["pair_offsets"] == {"living": {"tag": -2.5, "phone": 1.0}}
    assert Floorplan.from_dict(data) == plan
    assert make_plan().as_dict()["pair_offsets"] == {}
    with pytest.raises(probatio.Invalid):
        make_plan(pair_offsets={"living": {"Bad Key": 1}})
    with pytest.raises(probatio.Invalid):
        make_plan(pair_offsets={"living": {"tag": "loud"}})


def test_ref_power() -> None:
    """A tracker's own reference power, else the default."""
    plan = make_plan()
    tag = plan.tracker("tag")
    phone = plan.tracker("phone")
    assert tag is not None and phone is not None
    assert plan.ref_power(tag) == -60.0
    assert plan.ref_power(phone) == -55.0


def test_with_calibration() -> None:
    """Values named are written, others kept, pairs merged; unknown keys are refused."""
    plan = make_plan(pair_offsets={"living": {"tag": -2.0, "phone": 1.0}})
    new = with_calibration(
        plan,
        2.7,
        {"phone": -66.0},
        {"kitchen": -3.0},
        {"living": {"tag": 0.5}, "bedroom": {"phone": 2.0}},
    )
    assert new.settings.attenuation == 2.7
    assert new.settings.max_distance == plan.settings.max_distance
    assert [t.ref_power for t in new.trackers] == [-60.0, -66.0]
    assert [s.rssi_offset for s in new.scanners] == [0.0, -3.0, 0.0]
    assert new.pair_offsets == {"living": {"tag": 0.5, "phone": 1.0}, "bedroom": {"phone": 2.0}}
    assert new.rooms == plan.rooms
    # The plan given is untouched
    assert plan.pair_offsets == {"living": {"tag": -2.0, "phone": 1.0}}
    assert with_calibration(plan, None, {}, {}, {}) == plan
    for args in (
        ({"nope": -1.0}, {}, {}),
        ({}, {"nope": 1.0}, {}),
        ({}, {}, {"nope": {"tag": 1.0}}),
        ({}, {}, {"living": {"nope": 1.0}}),
    ):
        with pytest.raises(LookupError, match="nope"):
            with_calibration(plan, None, *args)
