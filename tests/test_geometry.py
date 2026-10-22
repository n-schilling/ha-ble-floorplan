"""The geometry gives the numbers of the card's JavaScript."""

from __future__ import annotations

import pytest

from custom_components.ble_floorplan.geometry import (
    bounds,
    closest_on_outline,
    closest_on_segment,
    point_in_polygon,
    point_in_rect,
)

from . import make_plan

BEDROOM = ((0, 5), (6, 5), (6, 9), (2, 9), (2, 8), (0, 8))


@pytest.mark.parametrize(
    ("x", "y", "inside"),
    [(0.5, 7.9, True), (1, 8.5, False), (3, 6, True), (5, 8.9, True), (6, 9, False), (7, 7, False)],
)
def test_point_in_polygon(x: float, y: float, inside: bool) -> None:
    """Even-odd rule on the L-shaped bedroom."""
    assert point_in_polygon(BEDROOM, x, y) is inside


def test_point_in_rect() -> None:
    """Borders count as inside."""
    assert point_in_rect(0, 0, 6, 5, 6, 5)
    assert not point_in_rect(0, 0, 6, 5, 6.01, 5)


def test_closest_on_segment() -> None:
    """Projection onto the segment, clamped to its ends; a degenerate segment is its point."""
    assert closest_on_segment((5, 5), (0, 0), (10, 0)) == (5, 0)
    assert closest_on_segment((-3, 5), (0, 0), (10, 0)) == (0, 0)
    assert closest_on_segment((5, 5), (2, 2), (2, 2)) == (2, 2)


def test_closest_on_outline() -> None:
    """The closest wall point and the distance to it."""
    point, distance = closest_on_outline(BEDROOM, 1, 8.5)
    assert point == (1, 8)
    assert distance == 0.5


def test_bounds() -> None:
    """The extent from the origin."""
    assert bounds([((0, 0), (6, 5)), ((2, 9), (10, 11))]) == (10, 11)
    assert bounds([]) == (0, 0)


def test_plan_extent_and_clamp() -> None:
    """The plan clamps a point outside the rooms to the closest wall; none when off."""
    plan = make_plan()
    assert plan.extent == (10, 11)
    assert plan.clamp(1, 1) == (1, 1)
    assert plan.clamp(1, 10.3) == (2, 9)
    assert plan.clamp(1, 8.5) == (1, 8)
    assert make_plan(settings={"clamp": False}).clamp(1, 10.3) == (1, 10.3)
    assert make_plan(settings={"clamp_outdoor": True}).clamp(1, 10.3) == (1, 10.3)
