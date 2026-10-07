"""Gridfinity bins, built to the figures in :mod:`gridfinity_standard`.

A **bin** is ``x`` by ``y`` units and ``u`` units tall. Every unit has the standard's base: its
profile swept round the unit's 41.5 mm square, joined above by the base's bridge. Walls stand
round the whole footprint to ``7u`` mm from the bin's bottom, and a stacking lip, if asked for,
stands above them with a 45-degree shoulder under its inner tip so it prints. Magnet and screw
holes, if asked for, open on the underside in the four corners of every unit. Dividers and label
tabs are :mod:`gridfinity_inside`'s; baseplates are :mod:`gridfinity_baseplate`'s.

A one-unit bin rests on its cell's slopes. The ridges between cells peak at the plate's 5 mm,
above the 4.75 mm where a bin's bridge joins its units, so a bin of more than one unit rests on the
ridges, 0.25 mm above its slopes: that is what the figures give, and the checks seat each bin where
it rests.

A bin prints standing on its base. The interface (the bin's base and the socket) is the
standard's and is never changed for the printer; a printer whose measured side gap closes by more
than the 0.25 mm a side the standard leaves gets a warning that its bins will bind.

Frame: X and Y across the grid, centred on the footprint; Z up from the bin's bottom.
Millimetres throughout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.gridfinity_baseplate import BaseplateSpec, build_baseplate
from zcad_core.features.gridfinity_inside import (
    STACK_CLEARANCE_MM,
    Inside,
    compartment_points,
    divider_walls,
    label_tabs,
    plan_inside,
)
from zcad_core.features.gridfinity_shapes import (
    GridfinityPart,
    base_unit,
    check_units,
    corner_holes,
    empty_at,
    held,
    near,
    section,
    stepped,
    unit_centres,
)
from zcad_core.features.gridfinity_standard import (
    BASE_HEIGHT_MM,
    BASE_PROFILE_DEPTH_MM,
    BASE_PROFILE_HEIGHT_MM,
    BASE_PROFILE_STEPS_MM,
    BASE_TOP_MM,
    BASE_TOP_RADIUS_MM,
    BASEPLATE_HEIGHT_MM,
    BASEPLATE_PROFILE_STEPS_MM,
    GRID_MM,
    HEIGHT_UNIT_MM,
    LIP_DEPTH_MM,
    LIP_HEIGHT_MM,
    LIP_STEPS_MM,
    MAGNET_HOLE_DEPTH_MM,
    MAGNET_HOLE_MM,
    REBUILT,
    SCREW_HOLE_MM,
    SPECIFICATION,
    profile_insets,
)

GRIDFINITY_RECORD = "gridfinity.json"
RECORD_SCHEMA_VERSION = "1.1.0"
NOT_CLAIMED = (
    "The engine keeps to the cited Gridfinity figures and checks its solids against them; it "
    "says nothing about whether a part fits a baseplate or a bin from another generator, what "
    "a bin or a stack bears, or how well a magnet or a screw holds. A part is unverified until "
    "printed trials have passed."
)
# The engine's own choices, which neither source gives.
DEFAULT_WALL_MM = 1.2
MINIMUM_HEIGHT_UNITS = 2


@dataclass(frozen=True)
class BinSpec:
    """A bin: its units, its height in units, and its options."""

    units_x: int
    units_y: int
    height_units: int
    lip: bool = True
    magnets: bool = False
    wall_mm: float = DEFAULT_WALL_MM
    screws: bool = False
    # Compartments across and front to back.
    divisions: tuple[int, int] = (1, 1)
    label_tabs: bool = False

    @property
    def height_mm(self) -> float:
        return self.height_units * HEIGHT_UNIT_MM

    @property
    def footprint_mm(self) -> tuple[float, float]:
        gap = GRID_MM - BASE_TOP_MM
        return self.units_x * GRID_MM - gap, self.units_y * GRID_MM - gap


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


def _underside_holes(spec: BinSpec, least_floor: float) -> list[cq.Workplane]:
    """Magnet holes, and screw holes up through the base to a floor's thickness under the
    cavity, in every unit's corners."""

    cutters = []

    for x, y in corner_holes(spec.units_x, spec.units_y):
        if spec.magnets:
            magnet = cq.Solid.makeCylinder(
                MAGNET_HOLE_MM / 2,
                MAGNET_HOLE_DEPTH_MM + 0.01,
                pnt=cq.Vector(x, y, -0.01),
            )
            cutters.append(cq.Workplane("XY").add(magnet))

        if spec.screws:
            screw = cq.Solid.makeCylinder(
                SCREW_HOLE_MM / 2,
                BASE_HEIGHT_MM - least_floor + 0.01,
                pnt=cq.Vector(x, y, -0.01),
            )
            cutters.append(cq.Workplane("XY").add(screw))

    return cutters


def _validate(spec: BinSpec, least_wall: float) -> None:
    check_units(spec.units_x, spec.units_y)

    if spec.height_units < MINIMUM_HEIGHT_UNITS:
        raise ValueError(
            f"A bin is at least {MINIMUM_HEIGHT_UNITS} units tall: one unit is all base"
        )

    if spec.wall_mm < least_wall:
        raise ValueError(
            f"A {spec.wall_mm:g} mm wall is under the printer's {least_wall:g} mm minimum"
        )


def build_bin(
    spec: BinSpec,
    profile: dict[str, Any],
    *,
    side_shortfall_mm: float | None = None,
) -> GridfinityPart:
    """A bin to the standard; refused if its units, height, wall or compartments cannot be
    built."""

    minimums = profile.get("minimums_mm", {})
    least_wall = float(minimums.get("wall", 1.2))
    least_floor = float(minimums.get("floor", 1.2))
    _validate(spec, least_wall)
    width, depth = spec.footprint_mm
    top = spec.height_mm + (LIP_HEIGHT_MM if spec.lip else 0.0)
    inside_top = (
        stack_seat_mm(spec) - STACK_CLEARANCE_MM if spec.lip else spec.height_mm
    )
    inside = plan_inside(
        width - 2 * spec.wall_mm,
        depth - 2 * spec.wall_mm,
        spec.divisions,
        inside_top,
        least_wall,
    )
    body = stepped(
        width,
        depth,
        BASE_TOP_RADIUS_MM,
        [(BASE_PROFILE_HEIGHT_MM, 0.0), (top, 0.0)],
    )

    for x, y in unit_centres(spec.units_x, spec.units_y):
        body = body.union(base_unit((x, y, 0.0)))

    body = body.cut(_bin_cavity(spec, width, depth))

    for addition in divider_walls(inside) + (
        label_tabs(inside) if spec.label_tabs else []
    ):
        body = body.union(addition)

    for cutter in _underside_holes(spec, least_floor):
        body = body.cut(cutter)

    return GridfinityPart(
        kind="bin",
        body=body,
        checks=_bin_checks(spec, body, inside),
        settings={
            "units": [spec.units_x, spec.units_y],
            "seat_height_mm": seat_height_mm(spec.units_x, spec.units_y),
            "height_units": spec.height_units,
            "height_mm": spec.height_mm,
            "lip": spec.lip,
            "magnets": spec.magnets,
            "screws": spec.screws,
            "wall_mm": spec.wall_mm,
            "divisions": list(spec.divisions),
            "divider_mm": inside.divider_mm,
            "label_tabs": spec.label_tabs,
        },
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        warnings=_fit_warnings(side_shortfall_mm),
    )


def _bin_checks(spec: BinSpec, body: cq.Workplane, inside: Inside) -> dict[str, bool]:
    plate = build_baseplate(
        BaseplateSpec(spec.units_x, spec.units_y), {}, check=False
    ).body
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "base_to_standard": _base_to_standard(body, spec),
        "seats_in_baseplate": held(
            body, plate, seat_height_mm(spec.units_x, spec.units_y)
        ),
        "compartments_open": empty_at(body, compartment_points(inside)),
    }

    if spec.lip:
        corner = (
            -(spec.units_x - 1) * GRID_MM / 2,
            -(spec.units_y - 1) * GRID_MM / 2,
            0.0,
        )
        checks["stacks"] = held(base_unit(corner), body, stack_seat_mm(spec))

    if spec.magnets or spec.screws:
        checks["underside_holes_open"] = empty_at(
            body,
            [(x, y, 0.5) for x, y in corner_holes(spec.units_x, spec.units_y)],
        )

    return checks


def _fit_warnings(side_shortfall_mm: float | None) -> tuple[str, ...]:
    gap = (GRID_MM - BASE_TOP_MM) / 2

    if side_shortfall_mm is None or side_shortfall_mm <= gap:
        return ()

    return (
        (
            f"The coupon measured this printer closing a side gap by "
            f"{side_shortfall_mm:.2f} mm, more than the {gap:g} mm a side the standard "
            "leaves between a bin and its cell: its bins may bind. The bin is built to the "
            "standard regardless"
        ),
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


def _base_to_standard(body: cq.Workplane, spec: BinSpec) -> bool:
    """The base's bottom is the profile's bottom and its top the standard's 41.5 mm units, each
    measured across the whole bin."""

    pitch_x, pitch_y = (spec.units_x - 1) * GRID_MM, (spec.units_y - 1) * GRID_MM
    bottom = BASE_TOP_MM - 2 * BASE_PROFILE_DEPTH_MM

    return near(section(body, 0.0), (pitch_x + bottom, pitch_y + bottom)) and near(
        section(body, BASE_PROFILE_HEIGHT_MM - 0.01), spec.footprint_mm
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
