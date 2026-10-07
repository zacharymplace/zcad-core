"""Gridfinity baseplates: plain, with magnets or screws under the cells, and in pieces.

A plain baseplate is ``x`` by ``y`` cells, each a 42 mm socket cut to the baseplate's own profile
over a straight clearance, open through the plate. Asked for magnets or screws, the plate stands
on a solid floor under its cells, as Gridfinity Rebuilt's are: 1 mm, with a magnet pocket 6.5 mm
across and 2.4 mm deep opening up under each of a bin's magnets, and under it, for screws, a 3 mm
hole through the floor with a 45-degree countersink, so a screw fixes the plate down with its head
below the magnet. The sockets start on the floor's top, where a bin then rests.

A plate larger than the printer's bed is cut into pieces of whole cells, each as near the same
size as the cells allow, that butt together: the plate is built whole and cut at the cells' edges,
so the pieces are exactly the plate. Only the plate's outer corners are rounded.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.gridfinity_shapes import (
    GridfinityPart,
    base_unit,
    bed_of,
    box,
    check_units,
    corner_holes,
    empty_at,
    held,
    near,
    size_of,
    stepped,
    unit_centres,
)
from zcad_core.features.gridfinity_standard import (
    BASEPLATE_CELL_RADIUS_MM,
    BASEPLATE_CLEARANCE_MM,
    BASEPLATE_COUNTERSINK_MM,
    BASEPLATE_FLOOR_MM,
    BASEPLATE_HEIGHT_MM,
    BASEPLATE_PROFILE_DEPTH_MM,
    BASEPLATE_PROFILE_STEPS_MM,
    GRID_MM,
    MAGNET_HOLE_DEPTH_MM,
    MAGNET_HOLE_MM,
    SCREW_HOLE_MM,
    profile_insets,
)


@dataclass(frozen=True)
class BaseplateSpec:
    """A baseplate: its cells, and what is under them."""

    units_x: int
    units_y: int
    magnets: bool = False
    screws: bool = False

    @property
    def floor_mm(self) -> float:
        """The solid floor under the cells: none for a plain plate."""

        if not (self.magnets or self.screws):
            return 0.0

        return (
            BASEPLATE_FLOOR_MM
            + (MAGNET_HOLE_DEPTH_MM if self.magnets else 0.0)
            + (BASEPLATE_COUNTERSINK_MM if self.screws else 0.0)
        )

    @property
    def height_mm(self) -> float:
        return self.floor_mm + BASEPLATE_HEIGHT_MM


def _socket(at: tuple[float, float], floor: float) -> cq.Workplane:
    """One cell's socket: the baseplate's profile over its straight clearance, from the floor's
    top, or through the plate when it has none."""

    depth = BASEPLATE_PROFILE_DEPTH_MM
    start = floor if floor > 0 else -1.0
    insets = [(start, depth), (floor + BASEPLATE_CLEARANCE_MM, depth)]
    insets += [
        (floor + BASEPLATE_CLEARANCE_MM + height, inset)
        for height, inset in profile_insets(BASEPLATE_PROFILE_STEPS_MM)[1:]
    ]
    insets.append((floor + BASEPLATE_HEIGHT_MM + 1.0, 0.0))

    return stepped(
        GRID_MM, GRID_MM, BASEPLATE_CELL_RADIUS_MM, insets, at=(at[0], at[1], 0.0)
    )


def _floor_holes(spec: BaseplateSpec, oversize: float) -> list[cq.Workplane]:
    """The magnet pockets opening up from the floor's top, and the screw holes through the floor
    with their countersinks under the pockets."""

    floor = spec.floor_mm
    cutters = []

    for x, y in corner_holes(spec.units_x, spec.units_y):
        if spec.magnets:
            pocket = cq.Solid.makeCylinder(
                MAGNET_HOLE_MM / 2,
                MAGNET_HOLE_DEPTH_MM + 0.01,
                pnt=cq.Vector(x, y, floor - MAGNET_HOLE_DEPTH_MM),
            )
            cutters.append(cq.Workplane("XY").add(pocket))

        if spec.screws:
            hole = (SCREW_HOLE_MM + oversize) / 2
            sink_top = floor - (MAGNET_HOLE_DEPTH_MM if spec.magnets else 0.0)
            through = cq.Solid.makeCylinder(
                hole, floor + 2.0, pnt=cq.Vector(x, y, -1.0)
            )
            # A funnel widening upward, so it prints with nothing over it.
            sink = cq.Solid.makeCone(
                hole,
                hole + BASEPLATE_COUNTERSINK_MM,
                BASEPLATE_COUNTERSINK_MM + 0.01,
                pnt=cq.Vector(x, y, sink_top - BASEPLATE_COUNTERSINK_MM),
            )
            cutters += [cq.Workplane("XY").add(through), cq.Workplane("XY").add(sink)]

    return cutters


def pieces_across(units: int, bed_mm: float) -> list[int]:
    """How many cells each piece takes along one axis: as few pieces as the bed allows, as
    even as the cells allow."""

    most = max(1, math.floor(bed_mm / GRID_MM))
    count = math.ceil(units / most)
    small, extra = divmod(units, count)

    return [small + 1] * extra + [small] * (count - extra)


def _cut_into_pieces(
    plate: cq.Workplane, spec: BaseplateSpec, bed: tuple[float, float, float]
) -> tuple[cq.Workplane, ...]:
    """The plate cut at its cells' edges into pieces that each fit the bed."""

    across = pieces_across(spec.units_x, bed[0])
    along = pieces_across(spec.units_y, bed[1])

    if len(across) == 1 and len(along) == 1:
        return ()

    def edges(counts: list[int], units: int) -> list[float]:
        found, total = [-units * GRID_MM / 2 - 1.0], 0

        for count in counts[:-1]:
            total += count
            found.append((total - units / 2) * GRID_MM)

        found.append(units * GRID_MM / 2 + 1.0)

        return found

    xs, ys = edges(across, spec.units_x), edges(along, spec.units_y)

    return tuple(
        plate.intersect(box(x0, x1, y0, y1, -1.0, spec.height_mm + 1.0))
        for y0, y1 in itertools.pairwise(ys)
        for x0, x1 in itertools.pairwise(xs)
    )


def build_baseplate(
    spec: BaseplateSpec, profile: dict[str, Any], *, check: bool = True
) -> GridfinityPart:
    """A baseplate of the spec's cells, in pieces if it outgrows the bed."""

    check_units(spec.units_x, spec.units_y)
    floor = spec.floor_mm
    plate = stepped(
        spec.units_x * GRID_MM,
        spec.units_y * GRID_MM,
        BASEPLATE_CELL_RADIUS_MM,
        [(0.0, 0.0), (spec.height_mm, 0.0)],
    )

    for x, y in unit_centres(spec.units_x, spec.units_y):
        plate = plate.cut(_socket((x, y), floor))

    oversize = float(profile.get("tolerances_mm", {}).get("hole_oversize", 0.0))

    for cutter in _floor_holes(spec, oversize):
        plate = plate.cut(cutter)

    bed = bed_of(profile)
    pieces = _cut_into_pieces(plate, spec, bed) if bed is not None else ()
    checks: dict[str, bool] = {}

    if check:
        corner = (
            -(spec.units_x - 1) * GRID_MM / 2,
            -(spec.units_y - 1) * GRID_MM / 2,
            0.0,
        )
        checks = {
            "one_solid": len(plate.solids().vals()) == 1,
            "cells_to_standard": near(
                size_of(plate),
                (spec.units_x * GRID_MM, spec.units_y * GRID_MM, spec.height_mm),
            ),
            "holds_a_bin": held(base_unit(corner), plate, floor),
        }

        if spec.magnets or spec.screws:
            checks["floor_holes_open"] = empty_at(
                plate,
                [
                    (x, y, floor - 0.5)
                    for x, y in corner_holes(spec.units_x, spec.units_y)
                ],
            )

        if pieces:
            checks["pieces_are_the_plate"] = _pieces_are_the_plate(plate, pieces)

    return GridfinityPart(
        kind="baseplate",
        body=plate,
        checks=checks,
        settings={
            "units": [spec.units_x, spec.units_y],
            "height_mm": spec.height_mm,
            "floor_mm": floor,
            "magnets": spec.magnets,
            "screws": spec.screws,
            "pieces": [[round(v, 3) for v in size_of(piece)[:2]] for piece in pieces],
        },
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        pieces=pieces,
    )


def _pieces_are_the_plate(
    plate: cq.Workplane, pieces: tuple[cq.Workplane, ...]
) -> bool:
    """Every piece is one solid, and together they hold the plate's whole volume."""

    whole = plate.val().Volume()  # type: ignore[union-attr]
    parts = [piece.val().Volume() for piece in pieces]  # type: ignore[union-attr]

    return all(len(piece.solids().vals()) == 1 for piece in pieces) and (
        abs(sum(parts) - whole) <= 1e-3 * whole
    )
