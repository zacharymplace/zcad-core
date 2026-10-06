"""Gridfinity bins and baseplates, built to the figures in :mod:`gridfinity_standard`.

A **bin** is ``x`` by ``y`` units and ``u`` units tall. Every unit has the standard's base: its
profile swept round the unit's 41.5 mm square, joined above by the base's bridge. Walls stand
round the whole footprint to ``7u`` mm from the bin's bottom, and a stacking lip, if asked for,
stands above them with a 45-degree shoulder under its inner tip so it prints. Magnet holes, if
asked for, open on the underside in the four corners of every unit.

A **baseplate** is ``x`` by ``y`` cells, each a 42 mm socket cut to the baseplate's own profile
over a straight clearance, open through the plate. A one-unit bin's base rests on the socket's
slopes. The ridges between cells peak at the plate's 5 mm, above the 4.75 mm where a bin's bridge
joins its units, so a bin of more than one unit rests on the ridges, 0.25 mm above its slopes:
that is what the figures give, and the checks seat each bin where it rests.

Both print as they stand: a bin on its base, a baseplate flat. The interface (the bin's base and
the socket) is the standard's and is never changed for the printer; a printer whose measured side
gap closes by more than the 0.25 mm a side the standard leaves gets a warning that its bins will
bind.

Frame: X and Y across the grid, centred on the footprint; Z up from the bin's or the plate's
bottom. Millimetres throughout.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.gridfinity_standard import (
    BASE_HEIGHT_MM,
    BASE_PROFILE_DEPTH_MM,
    BASE_PROFILE_HEIGHT_MM,
    BASE_PROFILE_STEPS_MM,
    BASE_TOP_MM,
    BASE_TOP_RADIUS_MM,
    BASEPLATE_CELL_RADIUS_MM,
    BASEPLATE_CLEARANCE_MM,
    BASEPLATE_HEIGHT_MM,
    BASEPLATE_PROFILE_DEPTH_MM,
    BASEPLATE_PROFILE_STEPS_MM,
    GRID_MM,
    HEIGHT_UNIT_MM,
    LIP_DEPTH_MM,
    LIP_HEIGHT_MM,
    LIP_STEPS_MM,
    MAGNET_HOLE_DEPTH_MM,
    MAGNET_HOLE_MM,
    MAGNET_INSET_MM,
    REBUILT,
    SPECIFICATION,
    profile_insets,
)
from zcad_core.geometry.intersection import intersection_volume

GRIDFINITY_RECORD = "gridfinity.json"
RECORD_SCHEMA_VERSION = "1.0.0"
NOT_CLAIMED = (
    "The engine keeps to the cited Gridfinity figures and checks its solids against them; it "
    "says nothing about whether a part fits a baseplate or a bin from another generator, what "
    "a bin or a stack bears, or how well a magnet holds. A part is unverified until printed "
    "trials have passed."
)
# The engine's own choices, which neither source gives.
DEFAULT_WALL_MM = 1.2
# A seated or stacked base is clear of what holds it when raised this much, and meets it when
# pushed this far lower, which shows the slopes hold it.
CLEAR_LIFT_MM = 0.05
HELD_DROP_MM = 0.2
MINIMUM_HEIGHT_UNITS = 2
MAXIMUM_UNITS = 8
ARC_STEPS = 12
TOLERANCE_MM3 = 1e-6


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


def unit_centres(units_x: int, units_y: int) -> list[tuple[float, float]]:
    return [
        ((i - (units_x - 1) / 2) * GRID_MM, (j - (units_y - 1) / 2) * GRID_MM)
        for i in range(units_x)
        for j in range(units_y)
    ]


def base_unit(at: tuple[float, float, float]) -> cq.Workplane:
    """One unit's base profile, its bottom at ``at``."""

    return stepped(
        BASE_TOP_MM,
        BASE_TOP_MM,
        BASE_TOP_RADIUS_MM,
        profile_insets(BASE_PROFILE_STEPS_MM),
        at=at,
    )


@dataclass(frozen=True)
class BinSpec:
    """A bin: its units, its height in units, and its options."""

    units_x: int
    units_y: int
    height_units: int
    lip: bool = True
    magnets: bool = False
    wall_mm: float = DEFAULT_WALL_MM

    @property
    def height_mm(self) -> float:
        return self.height_units * HEIGHT_UNIT_MM

    @property
    def footprint_mm(self) -> tuple[float, float]:
        gap = GRID_MM - BASE_TOP_MM
        return self.units_x * GRID_MM - gap, self.units_y * GRID_MM - gap


@dataclass(frozen=True)
class GridfinityPart:
    """A built bin or baseplate, the checks on it, and what it was built to."""

    kind: str
    body: cq.Workplane
    checks: dict[str, bool]
    settings: dict[str, Any]
    profile_id: str
    tolerance_status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def size_mm(self) -> tuple[float, float, float]:
        bounds = self.body.val().BoundingBox()  # type: ignore[union-attr]

        return bounds.xlen, bounds.ylen, bounds.zlen


def _check_units(units_x: int, units_y: int) -> None:
    for name, value in (("x", units_x), ("y", units_y)):
        if not 1 <= value <= MAXIMUM_UNITS:
            raise ValueError(
                f"A Gridfinity part is 1 to {MAXIMUM_UNITS} units along {name}, not {value}"
            )


def _bin_cavity(spec: BinSpec, width: float, depth: float) -> cq.Workplane:
    """The bin's inside: straight walls from the base's top, a 45-degree shoulder up to the lip's
    inner tip, and the lip's socket above, open at the top."""

    wall, top = spec.wall_mm, spec.height_mm
    radius = BASE_TOP_RADIUS_MM

    if not spec.lip:
        return stepped(
            width, depth, radius, [(BASE_HEIGHT_MM, wall), (top + 1.0, wall)]
        )

    shoulder = max(0.0, LIP_DEPTH_MM - wall)
    insets = [(BASE_HEIGHT_MM, wall)]

    if shoulder > 0:
        insets.append((top - shoulder, wall))

    insets.append((top, LIP_DEPTH_MM))
    insets += [
        (top + height, inset) for height, inset in profile_insets(LIP_STEPS_MM)[1:]
    ]
    insets.append((top + LIP_HEIGHT_MM + 1.0, 0.0))

    return stepped(width, depth, radius, insets)


def build_bin(
    spec: BinSpec,
    profile: dict[str, Any],
    *,
    side_shortfall_mm: float | None = None,
) -> GridfinityPart:
    """A bin to the standard; refused if its units, height or wall cannot be built."""

    _check_units(spec.units_x, spec.units_y)
    least_wall = float(profile.get("minimums_mm", {}).get("wall", 1.2))

    if spec.height_units < MINIMUM_HEIGHT_UNITS:
        raise ValueError(
            f"A bin is at least {MINIMUM_HEIGHT_UNITS} units tall: one unit is all base"
        )

    if spec.wall_mm < least_wall:
        raise ValueError(
            f"A {spec.wall_mm:g} mm wall is under the printer's {least_wall:g} mm minimum"
        )

    width, depth = spec.footprint_mm
    top = spec.height_mm + (LIP_HEIGHT_MM if spec.lip else 0.0)
    body = stepped(
        width,
        depth,
        BASE_TOP_RADIUS_MM,
        [(BASE_PROFILE_HEIGHT_MM, 0.0), (top, 0.0)],
    )

    for x, y in unit_centres(spec.units_x, spec.units_y):
        body = body.union(base_unit((x, y, 0.0)))

    body = body.cut(_bin_cavity(spec, width, depth))

    if spec.magnets:
        offset = GRID_MM / 2 - MAGNET_INSET_MM

        for x, y in unit_centres(spec.units_x, spec.units_y):
            for sx in (-1, 1):
                for sy in (-1, 1):
                    hole = cq.Solid.makeCylinder(
                        MAGNET_HOLE_MM / 2,
                        MAGNET_HOLE_DEPTH_MM + 0.01,
                        pnt=cq.Vector(x + sx * offset, y + sy * offset, -0.01),
                    )
                    body = body.cut(cq.Workplane("XY").add(hole))

    plate = build_baseplate(spec.units_x, spec.units_y, profile, check=False).body
    rest = seat_height_mm(spec.units_x, spec.units_y)
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "base_to_standard": _base_to_standard(body, spec),
        "seats_in_baseplate": _held(body, plate, rest),
    }

    if spec.lip:
        corner = (
            -(spec.units_x - 1) * GRID_MM / 2,
            -(spec.units_y - 1) * GRID_MM / 2,
            0.0,
        )
        checks["stacks"] = _held(base_unit(corner), body, stack_seat_mm(spec))

    warnings = []
    gap = (GRID_MM - BASE_TOP_MM) / 2

    if side_shortfall_mm is not None and side_shortfall_mm > gap:
        warnings.append(
            f"The coupon measured this printer closing a side gap by {side_shortfall_mm:.2f} mm, "
            f"more than the {gap:g} mm a side the standard leaves between a bin and its cell: "
            "its bins may bind. The bin is built to the standard regardless"
        )

    return GridfinityPart(
        kind="bin",
        body=body,
        checks=checks,
        settings={
            "units": [spec.units_x, spec.units_y],
            "seat_height_mm": rest,
            "height_units": spec.height_units,
            "height_mm": spec.height_mm,
            "lip": spec.lip,
            "magnets": spec.magnets,
            "wall_mm": spec.wall_mm,
        },
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        warnings=tuple(warnings),
    )


def seat_height_mm(units_x: int, units_y: int) -> float:
    """How far above the plate's bottom a bin's bottom rests: on the socket's slopes for one unit,
    on the ridges between cells for more."""

    if units_x == 1 and units_y == 1:
        return 0.0

    return BASEPLATE_HEIGHT_MM - BASE_PROFILE_HEIGHT_MM


def stack_seat_mm(spec: BinSpec) -> float:
    """Where a base set in a bin's lip rests: below the lip's foot by as much as the base's bottom
    is narrower than the lip's tip, where the two 45-degree slopes meet."""

    return spec.height_mm - (BASE_PROFILE_DEPTH_MM - LIP_DEPTH_MM)


def _socket(at: tuple[float, float]) -> cq.Workplane:
    """One cell's socket, cut through the plate: the baseplate's profile over its straight
    clearance."""

    depth = BASEPLATE_PROFILE_DEPTH_MM
    insets = [(-1.0, depth), (BASEPLATE_CLEARANCE_MM, depth)]
    insets += [
        (BASEPLATE_CLEARANCE_MM + height, inset)
        for height, inset in profile_insets(BASEPLATE_PROFILE_STEPS_MM)[1:]
    ]
    insets.append((BASEPLATE_HEIGHT_MM + 1.0, 0.0))

    return stepped(
        GRID_MM, GRID_MM, BASEPLATE_CELL_RADIUS_MM, insets, at=(at[0], at[1], 0.0)
    )


def build_baseplate(
    units_x: int, units_y: int, profile: dict[str, Any], *, check: bool = True
) -> GridfinityPart:
    """A plain baseplate of ``units_x`` by ``units_y`` cells."""

    _check_units(units_x, units_y)
    plate = stepped(
        units_x * GRID_MM,
        units_y * GRID_MM,
        BASEPLATE_CELL_RADIUS_MM,
        [(0.0, 0.0), (BASEPLATE_HEIGHT_MM, 0.0)],
    )

    for x, y in unit_centres(units_x, units_y):
        plate = plate.cut(_socket((x, y)))

    checks: dict[str, bool] = {}

    if check:
        checks = {
            "one_solid": len(plate.solids().vals()) == 1,
            "cells_to_standard": _cells_to_standard(plate, units_x, units_y),
            "holds_a_bin": _held(
                base_unit(
                    (-(units_x - 1) * GRID_MM / 2, -(units_y - 1) * GRID_MM / 2, 0.0)
                ),
                plate,
                0.0,
            ),
        }

    return GridfinityPart(
        kind="baseplate",
        body=plate,
        checks=checks,
        settings={"units": [units_x, units_y], "height_mm": BASEPLATE_HEIGHT_MM},
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
    )


# --- checks on the built solids ------------------------------------------------------


def _section(body: cq.Workplane, z: float) -> tuple[float, float]:
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


def _near(found: tuple[float, float], wanted: tuple[float, float]) -> bool:
    return all(abs(a - b) <= 0.05 for a, b in zip(found, wanted, strict=True))


def _base_to_standard(body: cq.Workplane, spec: BinSpec) -> bool:
    """The base's bottom is the profile's bottom and its top the standard's 41.5 mm units, each
    measured across the whole bin."""

    pitch_x, pitch_y = (spec.units_x - 1) * GRID_MM, (spec.units_y - 1) * GRID_MM
    bottom = BASE_TOP_MM - 2 * BASE_PROFILE_DEPTH_MM

    return _near(_section(body, 0.0), (pitch_x + bottom, pitch_y + bottom)) and _near(
        _section(body, BASE_PROFILE_HEIGHT_MM - 0.01), spec.footprint_mm
    )


def _cells_to_standard(plate: cq.Workplane, units_x: int, units_y: int) -> bool:
    """The plate is the cells' 42 mm grid across and the standard's 5 mm tall."""

    bounds = plate.val().BoundingBox()  # type: ignore[union-attr]

    return _near(
        (bounds.xlen, bounds.ylen), (units_x * GRID_MM, units_y * GRID_MM)
    ) and (abs(bounds.zlen - BASEPLATE_HEIGHT_MM) <= 0.01)


def _held(base: cq.Workplane, holder: cq.Workplane, seat_z: float) -> bool:
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


def require_fits_bed(part: GridfinityPart, profile: dict[str, Any]) -> None:
    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, height = part.size_mm
    bed = (float(volume["x"]), float(volume["y"]), float(volume["z"]))

    if width > bed[0] or depth > bed[1] or height > bed[2]:
        raise ValueError(
            f"The {part.kind} is {width:.1f} x {depth:.1f} x {height:.1f} mm, larger than the "
            f"printer's {bed[0]:g} x {bed[1]:g} x {bed[2]:g} mm"
        )


def gridfinity_record(
    part: GridfinityPart, files: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    width, depth, height = part.size_mm

    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "record_kind": f"gridfinity-{part.kind}-build",
        "kind": part.kind,
        "settings": part.settings,
        "standard": {
            "grid_mm": GRID_MM,
            "height_unit_mm": HEIGHT_UNIT_MM,
            "base_top_mm": BASE_TOP_MM,
            "base_top_radius_mm": BASE_TOP_RADIUS_MM,
            "base_profile_steps_mm": [list(step) for step in BASE_PROFILE_STEPS_MM],
            "lip_steps_mm": [list(step) for step in LIP_STEPS_MM],
            "baseplate_profile_steps_mm": [
                list(step) for step in BASEPLATE_PROFILE_STEPS_MM
            ],
            "sources": [SPECIFICATION, REBUILT],
        },
        "size_mm": [round(width, 3), round(depth, 3), round(height, 3)],
        "printer_profile_id": part.profile_id,
        "tolerance_status": part.tolerance_status,
        "parts": files,
        "fit_checks": part.checks,
        "warnings": list(part.warnings),
        "verified": False,
        "not_claimed": NOT_CLAIMED,
    }


def write_gridfinity_record(
    part: GridfinityPart, files: dict[str, dict[str, Any]], output_directory: Path
) -> Path:
    path = output_directory / GRIDFINITY_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(gridfinity_record(part, files), indent=2, sort_keys=True) + "\n",
        "utf-8",
    )

    return path
