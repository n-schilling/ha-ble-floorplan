"""The engine gives the numbers of the card's JavaScript."""

from __future__ import annotations

import math

import pytest

from custom_components.ble_floorplan.engine import (
    Measurement,
    RoomTracker,
    Smoother,
    floor_distance,
    median,
    rssi_to_distance,
    trilaterate,
)

from . import make_plan

PLAN = make_plan()
# The card's engine: no robust weights, no jump rule, no speed limit
CARD_SETTINGS = {"robust_residual": 0, "jump_distance": 0, "max_speed": 0, "walls": False}
CARD = make_plan(settings=CARD_SETTINGS)
NO_CLAMP = make_plan(settings={**CARD_SETTINGS, "clamp": False})


def test_rssi_to_distance() -> None:
    """The log-distance model: ref_power at one metre, offset shifts it."""
    assert rssi_to_distance(-55, -55, 0, 3) == pytest.approx(1.0)
    assert rssi_to_distance(-85, -55, 0, 3) == pytest.approx(10.0)
    assert rssi_to_distance(-85, -55, -30, 3) == pytest.approx(1.0)
    assert rssi_to_distance(-75, -55, 0, 2) == pytest.approx(10.0)


def test_floor_distance() -> None:
    """Pythagoras with the height difference; never imaginary."""
    assert floor_distance(5, 4, 1) == pytest.approx(4.0)
    assert floor_distance(1, 2, 0) == 0.0
    assert floor_distance(3, 1, 1) == 3.0


def test_median() -> None:
    """Odd and even counts."""
    assert median([-60, -70, -50]) == -60
    assert median([-60, -70]) == -65


@pytest.mark.parametrize(
    ("measurements", "plan", "expected"),
    [
        ([((1, 1), 2.0), ((9, 1), 6.5), ((1, 8), 5.0)], CARD, (2.1611725513, 2.7064602714)),
        # Residuals below robust_residual: the robust weights change nothing
        ([((1, 1), 2.0), ((9, 1), 6.5), ((1, 8), 5.0)], PLAN, (2.1611725513, 2.7064602714)),
        ([((1, 1), 3.0), ((9, 1), 5.0)], CARD, (3.9999999903, 1.0)),
        ([((1, 1), 3.0), ((9, 1), 5.0)], PLAN, (3.9999999903, 1.0)),
        ([((9, 1), 3.0)], PLAN, (9.0, 1.0)),
        ([((1, 1), 14.0), ((9, 1), 14.0), ((1, 8), 14.0)], CARD, (10.0, 9.0)),
        ([((1, 8), 0.3), ((1, 1), 7.5)], NO_CLAMP, (1.0, 7.7035398398)),
        ([((1, 1), 14.0), ((9, 1), 14.0)], NO_CLAMP, (5.0, 1.0)),
    ],
)
def test_trilaterate(
    measurements: list[tuple[tuple[float, float], float]],
    plan: object,
    expected: tuple[float, float],
) -> None:
    """Weighted Gauss-Newton, bounds and clamping, as in the card."""
    result = trilaterate([Measurement(p[0], p[1], d) for p, d in measurements], plan)  # type: ignore[arg-type]
    assert result is not None
    assert result == pytest.approx(expected, abs=1e-6)


def test_trilaterate_nothing() -> None:
    """No measurements, no position."""
    assert trilaterate([], PLAN) is None


def test_trilaterate_robust() -> None:
    """With four scanners, the one the others contradict loses weight; with three nothing changes."""
    truth = (3.0, 3.0)
    off = make_plan(settings={"robust_residual": 0, "clamp": False})
    on = make_plan(settings={"clamp": False})
    good = [
        Measurement(1, 1, math.hypot(2, 2)),
        Measurement(9, 1, math.hypot(6, 2)),
        Measurement(9, 8, math.hypot(6, 5)),
    ]
    # The fourth scanner says 2.0 m, the truth is 5.4 m: it claims to be nearest and
    # would carry the largest weight
    liar = Measurement(1, 8, 2.0)
    naive = trilaterate([*good, liar], off)
    robust = trilaterate([*good, liar], on)
    assert naive is not None and robust is not None
    assert math.dist(naive, truth) > 2.0
    assert math.dist(robust, truth) < 0.3
    assert robust == pytest.approx((2.8353655309, 3.2027687107), abs=1e-6)
    # Claiming too far is caught as well
    far = trilaterate([*good, Measurement(1, 8, 9.0)], on)
    assert far is not None
    assert math.dist(far, truth) < 0.05
    # Consistent scanners: nothing to lose
    consistent = [*good, Measurement(1, 8, math.hypot(2, 5))]
    assert trilaterate(consistent, on) == trilaterate(consistent, off)
    # Three scanners: no way to tell which one is wrong, so nothing changes
    three = [*good[:2], liar]
    assert trilaterate(three, on) == trilaterate(three, off)


def test_trilaterate_singular() -> None:
    """Measurements with vanishing weights leave the system singular: the start point stands."""
    result = trilaterate([Measurement(0, 0, 1e4), Measurement(10, 0, 1e4)], NO_CLAMP)
    assert result == (5.0, 0.0)


def test_smoother() -> None:
    """First value as is, dead zone, time constant, reset: the card's numbers."""
    smoother = Smoother()
    assert smoother.smooth("t", (1, 1), 1.0, CARD) == (1, 1)
    # Within the dead zone: the shown position stays
    assert smoother.smooth("t", (1.1, 1.1), 2.0, CARD) == (1, 1)
    assert smoother.smooth("t", (5, 4), 7.0, CARD) == pytest.approx(
        (1.8847968677, 1.6635976508), abs=1e-6
    )
    assert smoother.smooth("t", (5, 4), 27.0, CARD) == pytest.approx(
        (3.8539808126, 3.1404856094), abs=1e-6
    )
    smoother.reset("t")
    smoother.reset("t")
    assert smoother.smooth("t", (5, 4), 28.0, CARD) == (5, 4)


def test_smoother_clamps() -> None:
    """A smoothed position that drifts out of the rooms is put back on a wall."""
    smoother = Smoother()
    smoother.smooth("t", (1, 8), 0.0, CARD)
    x, y = smoother.smooth("t", (1, 10.5), 1000.0, CARD)
    # The balcony is outdoors, so the closest wall is the bedroom's corner
    assert (x, y) == (2, 9)
    assert math.isfinite(x)


def test_smoother_jump_needs_confirmation() -> None:
    """A far raw position holds the shown one until it stayed there for the confirm time."""
    smoother = Smoother()
    assert smoother.smooth("t", (1, 1), 0.0, PLAN) == (1, 1)
    # 5 m away: a candidate, the position holds
    assert smoother.smooth("t", (5, 4), 1.0, PLAN) == (1, 1)
    # Near the candidate: still the same candidate, still holding
    assert smoother.smooth("t", (5.5, 4), 2.0, PLAN) == (1, 1)
    # Back home: the candidate is dropped, and 0.2 m is within the dead zone
    assert smoother.smooth("t", (1.2, 1), 3.0, PLAN) == (1, 1)
    # Away again: a new candidate …
    assert smoother.smooth("t", (5, 4), 4.0, PLAN) == (1, 1)
    # … replaced by one far from it, which restarts the clock
    assert smoother.smooth("t", (9, 8), 6.0, PLAN) == (1, 1)
    assert smoother.smooth("t", (9, 8), 8.0, PLAN) == (1, 1)
    # Confirmed after 3 s: the step is as if followed since the last accepted
    # position at t = 3, so dt = 6 and a = 1 - e^(-6/20)
    a = 1 - math.exp(-6 / 20)
    assert smoother.smooth("t", (9, 8), 9.0, PLAN) == pytest.approx(
        (1 + a * 8, 1 + a * 7), abs=1e-9
    )


def test_smoother_speed_limit() -> None:
    """The shown position never moves faster than max_speed."""
    fast = make_plan(settings={"smoothing_seconds": 0.1, "jump_distance": 0, "walls": False})
    smoother = Smoother()
    smoother.smooth("t", (1, 1), 0.0, fast)
    # A time constant of 0.1 s would follow at once: 10 m in one second, capped at 1.5 m
    assert smoother.smooth("t", (9, 7), 1.0, fast) == pytest.approx((2.2, 1.9), abs=1e-9)
    # Two seconds later: 3 m more along the same line
    assert smoother.smooth("t", (9, 7), 3.0, fast) == pytest.approx((4.6, 3.7), abs=1e-6)
    unlimited = make_plan(
        settings={"smoothing_seconds": 0.1, "jump_distance": 0, "max_speed": 0, "walls": False}
    )
    smoother.reset("t")
    smoother.smooth("t", (1, 1), 0.0, unlimited)
    assert smoother.smooth("t", (9, 7), 1.0, unlimited) == pytest.approx((9, 7), abs=1e-3)


def test_room_tracker_hysteresis() -> None:
    """The room changes after the hold time, and only from well inside the new room."""
    rooms = RoomTracker()
    assert rooms.room("t", 1, 1, 0.0, PLAN) == "Living room"
    # In the kitchen, but 0.1 m from its wall: not deep enough
    assert rooms.room("t", 6.1, 3, 1.0, PLAN) == "Living room"
    # Well inside: a candidate, confirmed after 5 s
    assert rooms.room("t", 7, 3, 2.0, PLAN) == "Living room"
    assert rooms.room("t", 7, 3, 6.0, PLAN) == "Living room"
    assert rooms.room("t", 7, 3, 7.0, PLAN) == "Kitchen"
    # Back near the wall of the kitchen: stays, and a pending change is dropped
    assert rooms.room("t", 1, 1, 8.0, PLAN) == "Kitchen"
    assert rooms.room("t", 6.2, 3, 9.0, PLAN) == "Kitchen"
    assert rooms.room("t", 1, 1, 10.0, PLAN) == "Kitchen"
    assert rooms.room("t", 1, 1, 14.0, PLAN) == "Kitchen"
    assert rooms.room("t", 1, 1, 15.0, PLAN) == "Living room"
    # A different candidate restarts the clock
    assert rooms.room("t", 7, 3, 16.0, PLAN) == "Living room"
    assert rooms.room("t", 7, 7, 18.0, PLAN) == "Living room"
    assert rooms.room("t", 7, 7, 22.0, PLAN) == "Living room"
    assert rooms.room("t", 7, 7, 23.0, PLAN) == "Hall"
    rooms.reset("t")
    assert rooms.room("t", 7, 3, 24.0, PLAN) == "Kitchen"


def test_room_tracker_outside_and_zones() -> None:
    """Outside every room counts as a room of its own; zones have their own walls."""
    plan = make_plan(settings={"clamp": False, "room_hold_seconds": 2})
    rooms = RoomTracker()
    assert rooms.room("t", 1, 1, 0.0, plan) == "Living room"
    assert rooms.room("t", 12, 12, 1.0, plan) == "Living room"
    assert rooms.room("t", 12, 12, 3.0, plan) is None
    # The dining zone lies in the living room; 0.1 m inside its line is not deep enough
    assert rooms.room("t", 3.1, 1, 4.0, plan) is None
    assert rooms.room("t", 3.1, 1, 7.0, plan) is None
    assert rooms.room("t", 4.5, 1, 8.0, plan) is None
    assert rooms.room("t", 4.5, 1, 10.0, plan) == "Dining"
    # No hold, no margin: the room follows at once
    plain = make_plan(settings={"room_hold_seconds": 0, "room_margin": 0})
    rooms.reset("t")
    assert rooms.room("t", 1, 1, 0.0, plain) == "Living room"
    assert rooms.room("t", 6.05, 3, 1.0, plain) == "Kitchen"


@pytest.mark.parametrize(
    ("x", "y", "room"),
    [
        (4, 1, "Dining"),
        (1, 1, "Living room"),
        (7, 2, "Kitchen"),
        (1, 7, "Bedroom"),
        (7, 7, "Hall"),
        (5, 10, "Balcony"),
        (12, 12, None),
        (6, 2, "Dining"),
    ],
)
def test_room_at(x: float, y: float, room: str | None) -> None:
    """Zones first, then the room drawn last."""
    assert PLAN.room_at(x, y) == room


def test_smoother_goes_round_through_the_door() -> None:
    """A tracker that moves from the living room to the hall walks through the doors."""
    plan = make_plan(settings={"jump_distance": 0, "smoothing_seconds": 0.1})
    smoother = Smoother()
    smoother.smooth("t", (5.5, 4.0), 0.0, plan)
    visited = []
    point = (5.5, 4.0)
    for i in range(1, 40):
        point = smoother.smooth("t", (8.0, 7.0), float(i), plan)
        room = plan.space_of(*point)
        visited.append(room.name if room else None)
    # Never through a wall: living room, then the kitchen through its door, the hall last
    order = [r for i, r in enumerate(visited) if i == 0 or visited[i - 1] != r]
    assert order[0] == "Living room"
    assert order[-1] == "Hall"
    assert "Kitchen" in order or "Bedroom" in order
    assert point == pytest.approx((8.0, 7.0), abs=0.3)
