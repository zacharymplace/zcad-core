"""The shapes an object holder is built from, in the holder's frame.

Frame: X along the wall (to the right seen from the room), Y out from the wall, Z up. The back
plate's front face is ``y == 0`` and the floor's top ``z == 0``. Millimetres throughout.

Every hole through the back plate is horizontal, since the holder prints as it hangs, so the
outlines here that a hole is cut to end in a 45-degree point at the top.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import cadquery as cq

from zcad_core.hardware.electronics import board_outline

Box = tuple[float, float, float, float, float, float]
Point = tuple[float, float]


@dataclass(frozen=True)
class Placed:
    """The object as it stands in the holder: its size along X, Y and Z, and its corners'
    radius seen from the room."""

    width_mm: float
    depth_mm: float
    height_mm: float
    radius_mm: float | None


def xz_prism(points: Sequence[Point], y0: float, y1: float) -> cq.Workplane:
    """A prism of an outline seen from the room, (X, Z) points, between two Y."""

    return (
        cq.Workplane("XY")
        .workplane(offset=-y1)
        .polyline(list(points))
        .close()
        .extrude(y1 - y0)
        .rotate((0, 0, 0), (1, 0, 0), 90)
    )


def box(
    x0: float, x1: float, y0: float, y1: float, z0: float, z1: float
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def outline(
    width: float, height: float, radius: float | None, grow: float
) -> list[Point]:
    """The object's outline seen from the room, grown by ``grow``, standing on ``z == 0``."""

    if radius is None:
        w, h = width + 2 * grow, height + grow
        return [(-w / 2, 0.0), (w / 2, 0.0), (w / 2, h), (-w / 2, h)]

    points = board_outline.rounded_rectangle_points(
        width + 2 * grow, height + 2 * grow, radius + grow
    )

    return [(x, z + height / 2 + grow) for x, z in points]


def teardrop(cx: float, cz: float, radius: float, steps: int = 24) -> list[Point]:
    """A circle with its top drawn as a 45-degree point, so a horizontal hole prints."""

    points = [(cx, cz + radius * math.sqrt(2.0))]

    for i in range(steps - 5):
        angle = math.radians(45.0 - i * 360.0 / steps)
        points.append((cx + radius * math.cos(angle), cz + radius * math.sin(angle)))

    return points


def pointed_slot(x: float, z0: float, z1: float, width: float) -> list[Point]:
    """A vertical slot from ``z0`` to ``z1``, its top a 45-degree point."""

    half = width / 2

    return [
        (x - half, z0),
        (x + half, z0),
        (x + half, z1),
        (x, z1 + half),
        (x - half, z1),
    ]


def object_solid(p: Placed, clearance: float) -> cq.Shape:
    """The object as it stands, its back ``clearance`` off the back plate."""

    solid = xz_prism(
        outline(p.width_mm, p.height_mm, p.radius_mm, 0.0),
        clearance,
        clearance + p.depth_mm,
    ).val()

    if not isinstance(solid, cq.Shape):
        raise TypeError("Expected a shape")

    return solid
