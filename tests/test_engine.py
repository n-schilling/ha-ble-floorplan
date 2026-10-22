"""The engine gives the numbers of the card's JavaScript."""

from __future__ import annotations

import math

import pytest

from custom_components.ble_floorplan.engine import (
    Measurement,
    Smoother,
    floor_distance,
    median,
    rssi_to_distance,
    trilaterate,
)

from . import make_plan

PLAN = make_plan()
NO_CLAMP = make_plan(settings={"clamp": False})


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
        ([((1, 1), 2.0), ((9, 1), 6.5), ((1, 8), 5.0)], PLAN, (2.1611725513, 2.7064602714)),
        ([((1, 1), 3.0), ((9, 1), 5.0)], PLAN, (3.9999999903, 1.0)),
        ([((9, 1), 3.0)], PLAN, (9.0, 1.0)),
        ([((1, 1), 14.0), ((9, 1), 14.0), ((1, 8), 14.0)], PLAN, (10.0, 9.0)),
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


def test_trilaterate_singular() -> None:
    """Measurements with vanishing weights leave the system singular: the start point stands."""
    result = trilaterate([Measurement(0, 0, 1e4), Measurement(10, 0, 1e4)], NO_CLAMP)
    assert result == (5.0, 0.0)


def test_smoother() -> None:
    """First value as is, dead zone, time constant, reset."""
    smoother = Smoother()
    assert smoother.smooth("t", (1, 1), 1.0, PLAN) == (1, 1)
    # Within the dead zone: the shown position stays
    assert smoother.smooth("t", (1.1, 1.1), 2.0, PLAN) == (1, 1)
    assert smoother.smooth("t", (5, 4), 7.0, PLAN) == pytest.approx(
        (1.8847968677, 1.6635976508), abs=1e-6
    )
    assert smoother.smooth("t", (5, 4), 27.0, PLAN) == pytest.approx(
        (3.8539808126, 3.1404856094), abs=1e-6
    )
    smoother.reset("t")
    smoother.reset("t")
    assert smoother.smooth("t", (5, 4), 28.0, PLAN) == (5, 4)


def test_smoother_clamps() -> None:
    """A smoothed position that drifts out of the rooms is put back on a wall."""
    smoother = Smoother()
    smoother.smooth("t", (1, 8), 0.0, PLAN)
    x, y = smoother.smooth("t", (1, 10.5), 1000.0, PLAN)
    # The balcony is outdoors, so the closest wall is the bedroom's corner
    assert (x, y) == (2, 9)
    assert math.isfinite(x)


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
