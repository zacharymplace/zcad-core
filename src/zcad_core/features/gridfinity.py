"""Gridfinity bins, built to the figures in :mod:`gridfinity_standard`.

A **bin** is ``x`` by ``y`` units and ``u`` units tall. Every unit has the standard's base: its
profile swept round the unit's 41.5 mm square, joined above by the base's bridge. Walls stand
round the whole footprint to ``7u`` mm from the bin's bottom, and a stacking lip, if asked for,
stands above them with a 45-degree shoulder under its inner tip so it prints. Magnet and screw
holes, if asked for, open on the underside in the four corners of every unit. Dividers and label
tabs are :mod:`gridfinity_inside`'s; baseplates are :mod:`gridfinity_baseplate`'s.

A **half-grid** bin (``--half-grid``) has its bases on a 21 mm pitch, as Gridfinity Rebuilt
builds them: the same profile on a 20.5 mm top, counts in half units, the walls and lip of a full
bin of the same outside, and magnet and screw holes at its four outer corners only. A bin one half
unit across covers half a cell and is held there on one side only, so the build warns of it.

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
    MAXIMUM_UNITS,
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
    BASE_GAP_MM,
    BASE_HEIGHT_MM,
    BASE_PROFILE_DEPTH_MM,
    BASE_PROFILE_HEIGHT_MM,
    BASE_PROFILE_STEPS_MM,
    BASE_TOP_MM,
    BASE_TOP_RADIUS_MM,
    BASEPLATE_HEIGHT_MM,
    BASEPLATE_PROFILE_STEPS_MM,
    GRID_MM,
    HALF_GRID_HOLE_INSET_MM,
    HALF_GRID_MM,
    HEIGHT_UNIT_MM,
    LIP_DEPTH_MM,
    LIP_HEIGHT_MM,
    LIP_STEPS_MM,
    MAGNET_HOLE_DEPTH_MM,
    MAGNET_HOLE_MM,
    REBUILT,
    REBUILT_HALF_GRID,
    SCREW_HOLE_MM,
    SPECIFICATION,
    profile_insets,
)
from zcad_core.features.gridfinity_trial import gridfinity_checks

GRIDFINITY_RECORD = "gridfinity.json"
RECORD_SCHEMA_VERSION = "1.2.0"
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
    # Units on the half grid's 21 mm pitch, counted in half units.
    half_grid: bool = False

    @property
    def height_mm(self) -> float:
        return self.height_units * HEIGHT_UNIT_MM

    @property
    def pitch_mm(self) -> float:
        return HALF_GRID_MM if self.half_grid else GRID_MM

    @property
    def base_top_mm(self) -> float:
        return self.pitch_mm - BASE_GAP_MM

    @property
    def footprint_mm(self) -> tuple[float, float]:
        return (
            self.units_x * self.pitch_mm - BASE_GAP_MM,
            self.units_y * self.pitch_mm - BASE_GAP_MM,
        )

    @property
    def cells(self) -> tuple[int, int]:
        """The baseplate cells the bin covers, set at a cell's corner: a half-grid bin with an
        odd count covers half of its last cell."""

        per_cell = round(GRID_MM / self.pitch_mm)

        return -(-self.units_x // per_cell), -(-self.units_y // per_cell)

    @property
    def located(self) -> bool:
        """Whether some cell under the bin meets its bases on both sides in each direction: not
        so for a half-grid bin one half unit across, which a neighbour must hold."""

        return not self.half_grid or min(self.units_x, self.units_y) > 1


def bin_block(spec: BinSpec) -> cq.Workplane:
    """The bin solid to its top, its lip's height included: the bases under every unit and the
    outer body above them, before anything is cut from it."""

    width, depth = spec.footprint_mm
    top = spec.height_mm + (LIP_HEIGHT_MM if spec.lip else 0.0)
    body = stepped(
        width,
        depth,
        BASE_TOP_RADIUS_MM,
        [(BASE_PROFILE_HEIGHT_MM, 0.0), (top, 0.0)],
    )

    for x, y in unit_centres(spec.units_x, spec.units_y, spec.pitch_mm):
        body = body.union(base_unit((x, y, 0.0), spec.base_top_mm))

    return body


def lip_socket(spec: BinSpec) -> cq.Workplane:
    """The stacking lip's socket alone, above the wall's top, for a bin solid below it."""

    width, depth = spec.footprint_mm
    top = spec.height_mm
    insets = [(top - 0.01, LIP_DEPTH_MM)]
    insets += [
        (top + height, inset) for height, inset in profile_insets(LIP_STEPS_MM)[1:]
    ]
    insets.append((top + LIP_HEIGHT_MM + 1.0, 0.0))

    return stepped(width, depth, BASE_TOP_RADIUS_MM, insets)


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


def hole_points(spec: BinSpec) -> list[tuple[float, float]]:
    """Where magnets and screws go: every unit's four corners on the full grid, the bin's four
    outer corners only on the half grid, 4.8 mm in from the edge of its bases' bottom."""

    if not spec.half_grid:
        return corner_holes(spec.units_x, spec.units_y)

    width, depth = spec.footprint_mm
    x = width / 2 - BASE_PROFILE_DEPTH_MM - HALF_GRID_HOLE_INSET_MM
    y = depth / 2 - BASE_PROFILE_DEPTH_MM - HALF_GRID_HOLE_INSET_MM

    return [(sx * x, sy * y) for sx in (-1, 1) for sy in (-1, 1)]


def underside_holes(spec: BinSpec, least_floor: float) -> list[cq.Workplane]:
    """Magnet holes, and screw holes up through the base to a floor's thickness under the
    cavity, where :func:`hole_points` puts them."""

    cutters = []

    for x, y in hole_points(spec):
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
    # A half unit is half the grid, so a bin may have twice as many.
    check_units(
        spec.units_x, spec.units_y, MAXIMUM_UNITS * (2 if spec.half_grid else 1)
    )

    refuse_overlapping_holes(spec)

    if spec.height_units < MINIMUM_HEIGHT_UNITS:
        raise ValueError(
            f"A bin is at least {MINIMUM_HEIGHT_UNITS} units tall: one unit is all base"
        )

    if spec.wall_mm < least_wall:
        raise ValueError(
            f"A {spec.wall_mm:g} mm wall is under the printer's {least_wall:g} mm minimum"
        )


def refuse_overlapping_holes(spec: BinSpec) -> None:
    """Refuse magnet or screw holes on a half-grid bin one half unit across, where the outer
    corners' holes would overlap."""

    if (
        spec.half_grid
        and (spec.magnets or spec.screws)
        and min(spec.units_x, spec.units_y) == 1
    ):
        raise ValueError(
            "A half-grid bin one half unit across has no room for magnet or screw holes: "
            "its outer corners' holes would overlap"
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
    body = bin_block(spec).cut(_bin_cavity(spec, width, depth))

    for addition in divider_walls(inside) + (
        label_tabs(inside) if spec.label_tabs else []
    ):
        body = body.union(addition)

    for cutter in underside_holes(spec, least_floor):
        body = body.cut(cutter)

    return GridfinityPart(
        kind="bin",
        body=body,
        checks=_bin_checks(spec, body, inside),
        settings={
            "units": [spec.units_x, spec.units_y],
            "half_grid": spec.half_grid,
            "pitch_mm": spec.pitch_mm,
            "seat_height_mm": seat_height_mm(*spec.cells),
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
        warnings=_fit_warnings(side_shortfall_mm) + located_warnings(spec),
    )


def _bin_checks(spec: BinSpec, body: cq.Workplane, inside: Inside) -> dict[str, bool]:
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "base_to_standard": base_to_standard(body, spec),
        "seats_in_baseplate": seats_in_baseplate(spec, body),
        "compartments_open": empty_at(body, compartment_points(inside)),
    }

    if spec.lip:
        checks.update(stacking_checks(spec, body, stack_seat_mm(spec)))

    if spec.magnets or spec.screws:
        checks["underside_holes_open"] = empty_at(
            body, [(x, y, 0.5) for x, y in hole_points(spec)]
        )

    return checks


def seats_in_baseplate(spec: BinSpec, body: cq.Workplane) -> bool:
    """Whether the bin rests on the engine's baseplate of the cells it covers, set at a cell's
    corner: a half-grid bin with an odd count covers half its last cell."""

    cells_x, cells_y = spec.cells
    plate = build_baseplate(BaseplateSpec(cells_x, cells_y), {}, check=False).body
    width, depth = spec.footprint_mm
    shift = (
        (width + BASE_GAP_MM - cells_x * GRID_MM) / 2,
        (depth + BASE_GAP_MM - cells_y * GRID_MM) / 2,
        0.0,
    )

    return held(body.translate(shift), plate, seat_height_mm(cells_x, cells_y))


def stacking_checks(
    spec: BinSpec, body: cq.Workplane, seat_z: float
) -> dict[str, bool]:
    """A base of the bin's own pitch set in its corner at ``seat_z`` (a bin like it stacked
    on it) and, on a half-grid bin wide enough, a full base (a full bin stacked on it)."""

    checks = {
        "stacks": held(
            base_unit(corner_unit(spec, spec.pitch_mm), spec.base_top_mm), body, seat_z
        )
    }

    if spec.half_grid and min(spec.units_x, spec.units_y) > 1:
        checks["takes_a_full_base"] = held(
            base_unit(corner_unit(spec, GRID_MM)), body, seat_z
        )

    return checks


def corner_unit(spec: BinSpec, pitch: float) -> tuple[float, float, float]:
    """The centre of a base ``pitch`` across set in the bin's corner."""

    width, depth = spec.footprint_mm

    return (
        -(width + BASE_GAP_MM - pitch) / 2,
        -(depth + BASE_GAP_MM - pitch) / 2,
        0.0,
    )


def located_warnings(spec: BinSpec) -> tuple[str, ...]:
    if spec.located:
        return ()

    return (
        (
            "This half-grid bin is one half unit across, so it covers half a cell and rests "
            "on the cell's slope on one side only: it can slide half a cell unless a "
            "neighbour holds it"
        ),
    )


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


def base_to_standard(body: cq.Workplane, spec: BinSpec) -> bool:
    """The base's bottom is the profile's bottom and its top the standard's units (41.5 mm, or
    20.5 mm on the half grid), each measured across the whole bin."""

    pitch_x = (spec.units_x - 1) * spec.pitch_mm
    pitch_y = (spec.units_y - 1) * spec.pitch_mm
    bottom = spec.base_top_mm - 2 * BASE_PROFILE_DEPTH_MM

    return near(section(body, 0.0), (pitch_x + bottom, pitch_y + bottom)) and near(
        section(body, BASE_PROFILE_HEIGHT_MM - 0.01), spec.footprint_mm
    )


def _nominal_measurements(part: GridfinityPart) -> dict[str, float]:
    """The sizes a trial measures with calipers, in mm, from the part as built."""

    width, depth, height = part.size_mm
    sizes = {
        "overall_width_mm": round(width, 3),
        "overall_depth_mm": round(depth, 3),
        "overall_height_mm": round(height, 3),
    }

    if part.kind == "bin":
        sizes["wall_mm"] = float(part.settings["wall_mm"])
    else:
        sizes["cell_mm"] = GRID_MM

    return sizes


def gridfinity_record(
    part: GridfinityPart, files: dict[str, dict[str, Any]], design_name: str = ""
) -> dict[str, Any]:
    width, depth, height = part.size_mm

    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "record_kind": f"gridfinity-{part.kind}-build",
        "design_name": design_name,
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
            "sources": [SPECIFICATION, REBUILT]
            + ([REBUILT_HALF_GRID] if part.settings.get("half_grid") else []),
        },
        "size_mm": [round(width, 3), round(depth, 3), round(height, 3)],
        "printer_profile_id": part.profile_id,
        "tolerance_status": part.tolerance_status,
        "parts": files,
        "fit_checks": part.checks,
        "checks": gridfinity_checks(part.kind, part.settings),
        "nominal_measurements_mm": _nominal_measurements(part),
        "warnings": list(part.warnings),
        "verified": False,
        "not_claimed": NOT_CLAIMED,
    }


def write_gridfinity_record(
    part: GridfinityPart,
    files: dict[str, dict[str, Any]],
    output_directory: Path,
    design_name: str = "",
) -> Path:
    path = output_directory / GRIDFINITY_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(
            gridfinity_record(part, files, design_name), indent=2, sort_keys=True
        )
        + "\n",
        "utf-8",
    )

    return path
