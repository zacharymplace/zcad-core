"""The shapes and checks Gridfinity bins and baseplates are built from.

A Gridfinity profile is a rounded square stepped in or out at 45 degrees and straight up; every
solid here is such a stack of rounded rectangles, lofted between their heights. The checks seat
one part in another and measure cross-sections of the built solid, so what is checked is what is
exported.

Frame: X and Y across the grid, centred on the footprint; Z up from the part's bottom.
Millimetres throughout.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from zcad_core.features.gridfinity_standard import (
    BASE_PROFILE_STEPS_MM,
    BASE_TOP_MM,
    BASE_TOP_RADIUS_MM,
    GRID_MM,
    MAGNET_INSET_MM,
    profile_insets,
)
from zcad_core.geometry.intersection import intersection_volume

# A seated or stacked base is clear of what holds it when raised this much, and meets it when
# pushed this far lower, which shows the slopes hold it.
CLEAR_LIFT_MM = 0.05
HELD_DROP_MM = 0.2
MAXIMUM_UNITS = 8
ARC_STEPS = 12
TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class GridfinityPart:
    """A built bin or baseplate, the checks on it, and what it was built to. A baseplate too
    large for the bed carries its pieces too."""

    kind: str
    body: cq.Workplane
    checks: dict[str, bool]
    settings: dict[str, Any]
    profile_id: str
    tolerance_status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    pieces: tuple[cq.Workplane, ...] = ()

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def size_mm(self) -> tuple[float, float, float]:
        return size_of(self.body)

    @property
    def printed(self) -> dict[str, cq.Workplane]:
        """What goes on the bed: the part, or its pieces."""

        if not self.pieces:
            return {self.kind: self.body}

        return {
            f"{self.kind}-{number}": piece
            for number, piece in enumerate(self.pieces, start=1)
        }


def size_of(body: cq.Workplane) -> tuple[float, float, float]:
    bounds = body.val().BoundingBox()  # type: ignore[union-attr]

    return bounds.xlen, bounds.ylen, bounds.zlen


def check_units(units_x: int, units_y: int, most: int = MAXIMUM_UNITS) -> None:
    for name, value in (("x", units_x), ("y", units_y)):
        if not 1 <= value <= most:
            raise ValueError(
                f"A Gridfinity part is 1 to {most} units along {name}, not {value}"
            )


def rounded_wire(width: float, depth: float, radius: float, z: float) -> cq.Wire:
    """A rounded rectangle at height ``z``, centred on the origin, its corners sampled so two at
    different sizes loft point to point."""

    r = max(radius, 0.05)
    hx, hy = width / 2 - r, depth / 2 - r
    points = []

    for cx, cy, start in ((hx, hy, 0), (-hx, hy, 90), (-hx, -hy, 180), (hx, -hy, 270)):
        for i in range(ARC_STEPS + 1):
            angle = math.radians(start + 90 * i / ARC_STEPS)
            points.append(
                cq.Vector(cx + r * math.cos(angle), cy + r * math.sin(angle), z)
            )

    return cq.Wire.makePolygon(points, close=True)


def stepped(
    width: float,
    depth: float,
    radius: float,
    insets: list[tuple[float, float]],
    *,
    at: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> cq.Workplane:
    """A solid whose cross-section at each (height, inset) is the rounded rectangle shrunk by the
    inset, lofted between them, and moved to ``at``."""

    body: cq.Workplane | None = None

    for (z0, i0), (z1, i1) in itertools.pairwise(insets):
        piece = cq.Solid.makeLoft(
            [
                rounded_wire(width - 2 * i0, depth - 2 * i0, radius - i0, z0),
                rounded_wire(width - 2 * i1, depth - 2 * i1, radius - i1, z1),
            ],
            True,
        )
        part = cq.Workplane("XY").add(piece)
        body = part if body is None else body.union(part)

    if body is None:
        raise ValueError("A stepped solid needs two heights")

    return body.translate(at)


def box(
    x0: float, x1: float, y0: float, y1: float, z0: float, z1: float
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def unit_centres(
    units_x: int, units_y: int, pitch: float = GRID_MM
) -> list[tuple[float, float]]:
    return [
        ((i - (units_x - 1) / 2) * pitch, (j - (units_y - 1) / 2) * pitch)
        for i in range(units_x)
        for j in range(units_y)
    ]


def corner_holes(units_x: int, units_y: int) -> list[tuple[float, float]]:
    """The four corners of every unit where magnets and screws go: 8 mm in from each side of the
    unit's 42 mm square."""

    offset = GRID_MM / 2 - MAGNET_INSET_MM

    return [
        (x + sx * offset, y + sy * offset)
        for x, y in unit_centres(units_x, units_y)
        for sx in (-1, 1)
        for sy in (-1, 1)
    ]


def base_unit(at: tuple[float, float, float], top: float = BASE_TOP_MM) -> cq.Workplane:
    """One unit's base profile, its bottom at ``at``; a half-grid base is the same profile on a
    smaller top."""

    return stepped(
        top,
        top,
        BASE_TOP_RADIUS_MM,
        profile_insets(BASE_PROFILE_STEPS_MM),
        at=at,
    )


def section(body: cq.Workplane, z: float) -> tuple[float, float]:
    """The width and depth of a body's cross-section in a thin slice at ``z``."""

    solid = body.val()

    if not isinstance(solid, cq.Shape):
        raise TypeError("Expected a shape")

    big = 1000.0
    cut = solid.intersect(
        cq.Solid.makeBox(2 * big, 2 * big, 0.01, pnt=cq.Vector(-big, -big, z))
    )
    bounds = cut.BoundingBox()

    return bounds.xlen, bounds.ylen


def near(found: tuple[float, ...], wanted: tuple[float, ...]) -> bool:
    return all(abs(a - b) <= 0.05 for a, b in zip(found, wanted, strict=True))


def empty_at(body: cq.Workplane, points: list[tuple[float, float, float]]) -> bool:
    """Whether every point is outside the body's material."""

    solid = body.val()

    if not isinstance(solid, cq.Shape):
        raise TypeError("Expected a shape")

    solids = solid.Solids()

    return not any(
        part.isInside(cq.Vector(*point), 1e-4) for point in points for part in solids
    )


def held(base: cq.Workplane, holder: cq.Workplane, seat_z: float) -> bool:
    """Whether a base set at ``seat_z`` in what holds it is clear of it when raised a little, and
    meets it when pushed lower: it rests on the slopes and cannot drop through."""

    moving, fixed = base.val(), holder.val()

    if not isinstance(moving, cq.Shape) or not isinstance(fixed, cq.Shape):
        raise TypeError("Expected a shape")

    def at(z: float) -> float:
        return intersection_volume(moving.moved(cq.Location(cq.Vector(0, 0, z))), fixed)

    return (
        at(seat_z + CLEAR_LIFT_MM) <= TOLERANCE_MM3
        and at(seat_z - HELD_DROP_MM) > TOLERANCE_MM3
    )


def bed_of(profile: dict[str, Any]) -> tuple[float, float, float] | None:
    volume = profile.get("build_volume_mm")

    if not volume:
        return None

    return float(volume["x"]), float(volume["y"]), float(volume["z"])


def require_fits_bed(part: GridfinityPart, profile: dict[str, Any]) -> None:
    """Refuse a part, or a piece of one, larger than the printer's bed."""

    bed = bed_of(profile)

    if bed is None:
        return

    for name, body in part.printed.items():
        width, depth, height = size_of(body)

        if width > bed[0] or depth > bed[1] or height > bed[2]:
            raise ValueError(
                f"The {name} is {width:.1f} x {depth:.1f} x {height:.1f} mm, larger than "
                f"the printer's {bed[0]:g} x {bed[1]:g} x {bed[2]:g} mm"
            )
