"""Build a holding nest: a tray with a floor and a wall round a part's shadow.

The part stands on the floor in a pocket that follows its shadow, widened by the printer's sliding
clearance, with a wall round the pocket. The floor reaches past the wall by the flange. Finger
notches cut the wall down to the floor so the part lifts out by hand. The build refuses a nest
whose walls or floor are under the printer's minimum, whose notches do not fit the outline, or
from which the part would not lift straight up. Its record names the part by hash and says the nest
is unverified.

Frame: the part's own, as in :mod:`zcad_core.features.nest_file`: the part's top is ``z == 0``, its
bottom ``z == -height``, which is the floor's top; the wall climbs from there.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.guide_file import GuidePart
from zcad_core.features.nest_core import clear, lifts_out, pocketed
from zcad_core.features.nest_file import (
    NOTCH_MARGIN_MM,
    NOTCH_WIDTH_MM,
    NestSpec,
    pocket_depth_mm,
)
from zcad_core.geometry.outline_prism import outline_prism

NEST_RECORD_SCHEMA_VERSION = "1.0.0"
NEST_RECORD = "nest.json"
RECORD_KIND = "nest-build"
NOT_CLAIMED = (
    "The engine states nothing about how well the nest holds a part, only that the part fits "
    "the pocket and lifts straight out. A nest is unverified until a printed trial has passed."
)
Point = tuple[float, float]


@dataclass(frozen=True)
class Notch:
    """A finger notch: where it is cut through the wall, and the stretch of outline it is on."""

    centre: Point
    # The outward direction from the outline, a unit vector.
    outward: Point
    # The direction along the outline, a unit vector.
    along: Point
    stretch_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "centre_mm": [round(self.centre[0], 3), round(self.centre[1], 3)],
            "width_mm": NOTCH_WIDTH_MM,
            "stretch_mm": round(self.stretch_mm, 3),
        }


@dataclass(frozen=True)
class Nest:
    """The built nest and what it was built from."""

    spec: NestSpec
    part: GuidePart
    body: cq.Workplane
    depth_mm: float
    clearance_mm: float
    profile_id: str
    tolerance_status: str
    notches: tuple[Notch, ...]
    checks: dict[str, bool]
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return all(self.checks.values()) and not self.problems

    @property
    def size_mm(self) -> tuple[float, float, float]:
        box = self.body.val().BoundingBox()  # type: ignore[union-attr]

        return box.xlen, box.ylen, box.zlen


def _signed_area(points: tuple[Point, ...]) -> float:
    return (
        sum(
            a[0] * b[1] - b[0] * a[1]
            for a, b in zip(points, (*points[1:], points[0]), strict=True)
        )
        / 2
    )


def notch_sites(
    points: tuple[Point, ...], count: int
) -> tuple[tuple[Notch, ...], list[str]]:
    """Where ``count`` finger notches go: the middle of the longest straight stretches of the
    outline, each long enough for a notch with a margin past its ends. Fewer long stretches than
    notches asked for is refused, naming how many there are."""

    if count == 0:
        return (), []

    sign = 1.0 if _signed_area(points) > 0 else -1.0
    wanted = NOTCH_WIDTH_MM + 2 * NOTCH_MARGIN_MM
    stretches = []

    for a, b in zip(points, (*points[1:], points[0]), strict=True):
        length = math.hypot(b[0] - a[0], b[1] - a[1])

        if length >= wanted:
            along = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            outward = (sign * along[1], -sign * along[0])
            centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            stretches.append(Notch(centre, outward, along, length))

    stretches.sort(key=lambda notch: -notch.stretch_mm)

    if len(stretches) < count:
        message = (
            f"{count} finger notches need {count} straight stretches of outline at least "
            f"{wanted:g} mm long; the part's shadow has {len(stretches)}"
        )

        return tuple(stretches), [message]

    return tuple(stretches[:count]), []


def _notch_cutter(
    notch: Notch, clearance: float, wall: float, z0: float, z1: float
) -> cq.Workplane:
    """The box that cuts a notch through the wall, from the floor's top to above the wall:
    across the pocket's edge and the wall, centred on the middle of the stretch."""

    inner, outer = clearance - 1.0, clearance + wall + 0.5
    thickness = outer - inner
    offset = (inner + outer) / 2
    angle = math.degrees(math.atan2(notch.along[1], notch.along[0]))
    box = (
        cq.Workplane("XY")
        .box(NOTCH_WIDTH_MM, thickness, z1 - z0, centered=(True, True, False))
        .rotate((0, 0, 0), (0, 0, 1), angle)
    )

    shift = (
        notch.centre[0] + notch.outward[0] * offset,
        notch.centre[1] + notch.outward[1] * offset,
        z0,
    )

    return box.translate(shift)


def build_nest(spec: NestSpec, part: GuidePart, profile: dict[str, Any]) -> Nest:
    """The tray for a part; refused if a wall, the floor or a notch does not fit, or the part
    would not lift out."""

    fits, least_wall, least_floor = printer_numbers(profile)
    clearance = fits["sliding_clearance_per_side"]

    if spec.wall_mm < least_wall:
        raise ValueError(
            f"nest.wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm minimum wall"
        )

    if spec.floor_mm < least_floor:
        raise ValueError(
            f"nest.floor_mm is {spec.floor_mm:g}, under the printer's {least_floor:g} mm minimum "
            "floor"
        )

    depth = pocket_depth_mm(spec, part)

    if depth > part.height_mm + 1e-6:
        raise ValueError(
            f"nest.depth_mm is {depth:g}, deeper than the part's {part.height_mm:.1f} mm height"
        )

    points = part.silhouette.points
    floor_top = -part.height_mm
    floor_bottom = floor_top - spec.floor_mm
    wall_top = floor_top + depth
    notches, problems = notch_sites(points, spec.finger_notches)

    if problems:
        raise ValueError("The notches cannot be placed:\n- " + "\n- ".join(problems))

    body = pocketed(
        points,
        clearance_mm=clearance,
        wall_mm=spec.wall_mm,
        outer_z0=floor_bottom,
        outer_z1=wall_top,
        pocket_z0=floor_top,
        pocket_z1=wall_top + 1.0,
    )

    if spec.flange_mm > 0:
        body = body.union(
            outline_prism(
                points,
                floor_bottom,
                floor_top,
                clearance + spec.wall_mm + spec.flange_mm,
            )
        )

    for notch in notches:
        body = body.cut(
            _notch_cutter(notch, clearance, spec.wall_mm, floor_top, wall_top + 1.0)
        )

    solid = body.val()
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "part_fits_pocket": clear(solid, part.shape),
        "part_lifts_out": lifts_out(part.shape, solid, depth),
        "notches_open": _notches_open(
            solid, notches, clearance, spec.wall_mm, floor_top, wall_top
        ),
    }

    return Nest(
        spec=spec,
        part=part,
        body=body,
        depth_mm=depth,
        clearance_mm=clearance,
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        notches=notches,
        checks=checks,
        warnings=(),
    )


def _notches_open(
    body: object,
    notches: tuple[Notch, ...],
    clearance: float,
    wall: float,
    floor_top: float,
    wall_top: float,
) -> bool:
    """Every notch is open: no material in the wall at the middle of each, just above the floor
    and at the wall's top."""

    if not isinstance(body, cq.Shape):
        raise TypeError("Expected a shape")

    solids = body.Solids()

    for notch in notches:
        x = notch.centre[0] + notch.outward[0] * (clearance + wall / 2)
        y = notch.centre[1] + notch.outward[1] * (clearance + wall / 2)

        for z in (wall_top - 0.2, floor_top + 0.2):
            if any(solid.isInside(cq.Vector(x, y, z)) for solid in solids):
                return False

    return True


def print_oriented(nest: Nest) -> cq.Workplane:
    """The nest as it goes on the bed: its floor flat down, the pocket opening up."""

    low = nest.body.val().BoundingBox().zmin  # type: ignore[union-attr]

    return nest.body.translate((0.0, 0.0, -low))


def require_fits_bed(nest: Nest, profile: dict[str, Any]) -> None:
    """Refuse a nest that will not lie on the printer's bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, height = nest.size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or turned) or height > volume["z"]:
        raise ValueError(
            f"The nest is {width:.0f} x {depth:.0f} x {height:.0f} mm; the printer's bed is "
            f"{volume['x']:.0f} x {volume['y']:.0f} x {volume['z']:.0f} mm"
        )


def nest_record(nest: Nest, files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a build says of itself: the part by hash, the settings, what was placed, and that it
    is unverified."""

    spec, part = nest.spec, nest.part
    width, depth, height = nest.size_mm

    return {
        "schema_version": NEST_RECORD_SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "design_name": spec.identifier.lower().replace("_", "-"),
        "nest_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "part": {
            "path": str(spec.part_path),
            "sha256": part.sha256,
            "solid_index": spec.solid_index,
            "size_mm": [round(part.size_mm[0], 3), round(part.size_mm[1], 3)],
            "height_mm": round(part.height_mm, 3),
        },
        "settings": {
            "depth_mm": round(nest.depth_mm, 3),
            "wall_mm": spec.wall_mm,
            "floor_mm": spec.floor_mm,
            "flange_mm": spec.flange_mm,
            "finger_notches": spec.finger_notches,
            "clearance_per_side_mm": nest.clearance_mm,
        },
        "notches": [notch.to_dict() for notch in nest.notches],
        "size_mm": [round(width, 3), round(depth, 3), round(height, 3)],
        "printer_profile_id": nest.profile_id,
        "tolerance_status": nest.tolerance_status,
        "parts": files,
        "fit_checks": nest.checks,
        "verified": False,
        "not_claimed": NOT_CLAIMED,
    }


def write_nest_record(
    nest: Nest, files: dict[str, dict[str, Any]], output_directory: Path
) -> Path:
    """Write ``nest.json``; refuses to replace one."""

    path = output_directory / NEST_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(nest_record(nest, files), indent=2, sort_keys=True) + "\n", "utf-8"
    )

    return path
