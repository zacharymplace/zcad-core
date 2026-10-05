"""The holes a part already has where an insert could go: round holes open at its top face.

An insert jig can take its insert positions from the part's own model instead of from typed
numbers. A hole counts when it is a cylinder about the vertical axis whose upper end is at the
part's top face and whose axis lies in the void, whether it runs through the part or stops short
as a blind pocket, and whose faces go all the way round it: a pocket's rounded corner or a slot's
rounded end is part of a cylinder too, but only an arc of one, and is not a hole. Each comes with its diameter and depth, so the jig can check it against the
catalogued insert. The shape is in the part's frame, with its top at ``z == 0``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[import-untyped]

# A hole's upper end is at the top face within this much.
TOP_TOLERANCE_MM = 0.05
# Narrower than this is a pin or a via, not somewhere for an insert.
MINIMUM_HOLE_MM = 1.0
# A hole this share of the part's height, or more, runs through it.
THROUGH_SHARE = 0.9
# A hole's faces must go round its axis to within this much of a full turn, in radians.
FULL_TURN_TOLERANCE = 1e-3


@dataclass(frozen=True)
class PartHole:
    """A round hole open at the part's top face."""

    identifier: str
    x_mm: float
    y_mm: float
    diameter_mm: float
    depth_mm: float
    through: bool


def part_holes(
    shape: cq.Shape, height_mm: float, minimum_diameter_mm: float = MINIMUM_HOLE_MM
) -> list[PartHole]:
    """The part's round holes open at its top face, named H01, H02 and so on in order of
    their place (lowest Y first, then X), the way the guide import orders its holes."""

    bounds = shape.BoundingBox()
    found: dict[tuple[float, float, float], tuple[float, float, float, float]] = {}
    # How far round its axis each candidate's faces go, in radians.
    turned: dict[tuple[float, float, float], float] = {}

    for face in shape.Faces():
        if face.geomType() != "CYLINDER":
            continue

        # The face's own vertices, not its bounding box, which is padded a little.
        heights = [vertex.Z for vertex in face.Vertices()]

        if not heights:
            continue

        top, bottom = max(heights), min(heights)

        if top < -TOP_TOLERANCE_MM:
            continue

        surface = BRepAdaptor_Surface(face.wrapped)
        cylinder = surface.Cylinder()
        axis = cylinder.Axis()

        if abs(axis.Direction().Z()) < 0.999:
            continue

        x, y, radius = axis.Location().X(), axis.Location().Y(), cylinder.Radius()
        inside = (
            bounds.xmin + radius <= x <= bounds.xmax - radius
            and bounds.ymin + radius <= y <= bounds.ymax - radius
        )

        if (
            2 * radius < minimum_diameter_mm
            or not inside
            or cast(cq.Solid, shape).isInside(cq.Vector(x, y, (top + bottom) / 2), 1e-3)
        ):
            continue

        key = (round(x, 2), round(y, 2), round(2 * radius, 2))
        depth = max(top - bottom, found[key][3] if key in found else 0.0)
        found[key] = (x, y, 2 * radius, depth)
        turned[key] = turned.get(key, 0.0) + (
            surface.LastUParameter() - surface.FirstUParameter()
        )

    ordered = sorted(
        (
            hole
            for key, hole in found.items()
            if turned[key] >= 2 * math.pi - FULL_TURN_TOLERANCE
        ),
        key=lambda hole: (hole[1], hole[0]),
    )

    return [
        PartHole(
            f"H{number:02d}",
            x,
            y,
            diameter,
            depth,
            depth >= THROUGH_SHARE * height_mm,
        )
        for number, (x, y, diameter, depth) in enumerate(ordered, start=1)
    ]
