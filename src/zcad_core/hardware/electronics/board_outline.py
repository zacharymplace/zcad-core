"""A board's outline as a polygon about its centre: plain geometry, no CAD.

A board file gives its outline as ``"rectangle"`` (the default), a rounded
rectangle, or a polygon. Both of the latter become a list of points in the
board's frame (centre at the origin, +X right, +Y up the page, seen from
above), which the PCB solid, the snap-in cradle, and the checks read.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point = tuple[float, float]

# Segments in each 90 degree corner of a rounded rectangle.
CORNER_SEGMENTS = 8
MAXIMUM_POINTS = 500
# How far a polygon's bounding box may differ from the board's stated size.
SIZE_TOLERANCE_MM = 0.05


def rounded_rectangle_points(
    width_mm: float,
    length_mm: float,
    radius_mm: float,
    segments: int = CORNER_SEGMENTS,
) -> tuple[Point, ...]:
    """A rectangle with rounded corners, counter-clockwise from the bottom right."""

    half_w, half_l = width_mm / 2, length_mm / 2
    points: list[Point] = []
    corners = (
        (half_w - radius_mm, -half_l + radius_mm, -90.0),
        (half_w - radius_mm, half_l - radius_mm, 0.0),
        (-half_w + radius_mm, half_l - radius_mm, 90.0),
        (-half_w + radius_mm, -half_l + radius_mm, 180.0),
    )

    for cx, cy, start in corners:
        for step in range(segments + 1):
            angle = math.radians(start + 90.0 * step / segments)
            points.append(
                (
                    round(cx + radius_mm * math.cos(angle), 6),
                    round(cy + radius_mm * math.sin(angle), 6),
                )
            )

    return tuple(points)


def signed_area(points: Sequence[Point]) -> float:
    """Positive for a counter-clockwise polygon."""

    return (
        sum(
            a[0] * b[1] - b[0] * a[1]
            for a, b in zip(points, [*points[1:], points[0]], strict=True)
        )
        / 2
    )


def counter_clockwise(points: Sequence[Point]) -> tuple[Point, ...]:
    return tuple(points) if signed_area(points) >= 0 else tuple(reversed(points))


def bounding_box(points: Sequence[Point]) -> tuple[float, float, float, float]:
    """``(xmin, xmax, ymin, ymax)``."""

    xs, ys = [p[0] for p in points], [p[1] for p in points]

    return min(xs), max(xs), min(ys), max(ys)


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether two segments properly cross or touch at more than a shared end."""

    d1, d2 = _cross(c, d, a), _cross(c, d, b)
    d3, d4 = _cross(a, b, c), _cross(a, b, d)

    return (
        ((d1 > 0) != (d2 > 0))
        and ((d3 > 0) != (d4 > 0))
        and all(abs(v) > 1e-12 for v in (d1, d2, d3, d4))
    )


def is_simple(points: Sequence[Point]) -> bool:
    """Whether no two edges of the polygon cross."""

    count = len(points)
    edges = [(points[i], points[(i + 1) % count]) for i in range(count)]

    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue

            if _segments_cross(*edges[i], *edges[j]):
                return False

    return True


def contains(points: Sequence[Point], point: Point) -> bool:
    """Whether a point lies inside the polygon (ray casting)."""

    x, y = point
    inside = False

    for a, b in zip(points, [*points[1:], points[0]], strict=True):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (
            b[1] - a[1]
        ) + a[0]:
            inside = not inside

    return inside


def distance_to_boundary(points: Sequence[Point], point: Point) -> float:
    """How far a point is from the nearest edge of the polygon."""

    best = math.inf
    px, py = point

    for a, b in zip(points, [*points[1:], points[0]], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_squared = dx * dx + dy * dy
        t = (
            0.0
            if length_squared == 0
            else max(
                0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / length_squared)
            )
        )
        best = min(best, math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy)))

    return best


def depth_inside(points: Sequence[Point], point: Point) -> float:
    """How far inside the polygon a point is; negative outside it."""

    distance = distance_to_boundary(points, point)

    return distance if contains(points, point) else -distance


def chord(points: Sequence[Point], y: float) -> tuple[float, float] | None:
    """The leftmost and rightmost X at which the polygon crosses height ``y``."""

    crossings: list[float] = []

    for a, b in zip(points, [*points[1:], points[0]], strict=True):
        if (a[1] > y) != (b[1] > y):
            crossings.append(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))

    return (min(crossings), max(crossings)) if crossings else None


def _simplify_run(points: Sequence[Point], tolerance_mm: float) -> list[Point]:
    """Douglas-Peucker on an open run: keep the ends, and every point that
    strays further than the tolerance from the line between them."""

    first, last = points[0], points[-1]
    dx, dy = last[0] - first[0], last[1] - first[1]
    length = math.hypot(dx, dy)
    worst, index = 0.0, 0

    for position in range(1, len(points) - 1):
        px, py = points[position][0] - first[0], points[position][1] - first[1]
        distance = (
            math.hypot(px, py) if length == 0 else abs(px * dy - py * dx) / length
        )

        if distance > worst:
            worst, index = distance, position

    if worst <= tolerance_mm:
        return [first, last]

    return _simplify_run(points[: index + 1], tolerance_mm)[:-1] + _simplify_run(
        points[index:], tolerance_mm
    )


def simplified(points: Sequence[Point], tolerance_mm: float) -> tuple[Point, ...]:
    """A closed polygon with every point within the tolerance of its outline
    dropped, so a finely sampled curve keeps only the points that shape it."""

    count = len(points)

    if count < 4:
        return tuple(points)

    # Split the loop at its two furthest-apart points, which are always kept.
    far = max(range(1, count), key=lambda i: math.dist(points[0], points[i]))
    first = _simplify_run(points[: far + 1], tolerance_mm)
    second = _simplify_run([*points[far:], points[0]], tolerance_mm)
    result = first[:-1] + second[:-1]

    return tuple(result) if len(result) >= 3 else tuple(points)


def rotated(points: Sequence[Point], degrees: float) -> tuple[Point, ...]:
    """Points turned counter-clockwise about the origin."""

    cos, sin = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))

    return tuple((x * cos - y * sin, x * sin + y * cos) for x, y in points)
