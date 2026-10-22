"""Plane geometry of the floor plan: rooms as rectangles or polygons, all in metres.

The functions are ports of the card's JavaScript and give the same numbers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import math

type Point = tuple[float, float]


def point_in_polygon(points: Sequence[Point], x: float, y: float) -> bool:
    """Return whether (x, y) lies inside the polygon (even-odd rule, as in the card)."""
    inside = False
    j = len(points) - 1
    for i, (xi, yi) in enumerate(points):
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_rect(x0: float, y0: float, w: float, h: float, x: float, y: float) -> bool:
    """Return whether (x, y) lies in the rectangle, borders included."""
    return x0 <= x <= x0 + w and y0 <= y <= y0 + h


def closest_on_segment(p: Point, a: Point, b: Point) -> Point:
    """Return the point of the segment a-b that is closest to p."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    len2 = dx * dx + dy * dy
    t = min(1.0, max(0.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2)) if len2 else 0.0
    return (a[0] + t * dx, a[1] + t * dy)


def closest_on_outline(corners: Sequence[Point], x: float, y: float) -> tuple[Point, float]:
    """Return the closest point of the polygon's outline and its distance."""
    best: Point = corners[0]
    best_d = math.inf
    for i, a in enumerate(corners):
        q = closest_on_segment((x, y), a, corners[(i + 1) % len(corners)])
        d = math.hypot(q[0] - x, q[1] - y)
        if d < best_d:
            best_d = d
            best = q
    return best, best_d


def segment_intersection(p: Point, q: Point, a: Point, b: Point) -> tuple[float, Point] | None:
    """Return where the segment p-q crosses the segment a-b: (t along p-q, point), or None."""
    rx, ry = q[0] - p[0], q[1] - p[1]
    sx, sy = b[0] - a[0], b[1] - a[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-12:
        return None
    t = ((a[0] - p[0]) * sy - (a[1] - p[1]) * sx) / den
    u = ((a[0] - p[0]) * ry - (a[1] - p[1]) * rx) / den
    if not (0.0 <= t <= 1.0 and 0.0 <= u <= 1.0):
        return None
    return t, (p[0] + t * rx, p[1] + t * ry)


def bounds(outlines: Iterable[Sequence[Point]]) -> tuple[float, float]:
    """Return the extent (width, height) of the plan, from the origin."""
    max_x = 0.0
    max_y = 0.0
    for corners in outlines:
        for x, y in corners:
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    return max_x, max_y
