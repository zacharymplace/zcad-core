"""Build an insert jig: a nest round a part, and a plate with a bore over each insert.

The nest is a pocket on the underside that follows the part's shadow, widened by the printer's
sliding clearance; the plate stands on the part's top face. Each bore is the catalogued insert's
diameter plus the printer's sliding clearance each side and its hole oversize, so the insert drops
in and is held square as the iron presses it. The iron's tip goes down the bore and its shoulder
rests on the plate: the plate's thickness is the iron's tip length less how far below the face the
insert's top ends, so the plate is the depth stop. The build refuses a jig whose iron does not fit
its bore, whose plate would be under the printer's floor, whose bores do not lie in the part's
shadow or keep a wall between them, or from which the part would not lift. Its record names the
part by hash and says the jig is unverified.

Frame: the part's own, as in :mod:`zcad_core.features.jig_file`: the part's top is ``z == 0``;
the nest runs down from it and the plate up.
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
from zcad_core.features.jig_file import (
    InsertSite,
    JigSpec,
    insert_figures,
    pocket_depth_mm,
)
from zcad_core.features.nest_core import TOLERANCE_MM3, clear, lifts_off, pocketed
from zcad_core.geometry.intersection import intersection_volume

JIG_RECORD_SCHEMA_VERSION = "1.0.0"
JIG_RECORD = "jig.json"
RECORD_KIND = "jig-build"
NOT_CLAIMED = (
    "The engine states no temperature, time or force for installing an insert, and nothing "
    "about whether an insert holds or a part survives the heat. It says where each insert is "
    "and how far the iron can go. A jig is unverified until a printed trial has passed."
)
Point = tuple[float, float]


@dataclass(frozen=True)
class Bore:
    """One bore: where it is and how wide, with the insert it guides."""

    identifier: str
    centre: Point
    diameter_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "centre_mm": [round(self.centre[0], 3), round(self.centre[1], 3)],
            "diameter_mm": round(self.diameter_mm, 3),
        }


@dataclass(frozen=True)
class Jig:
    """The built jig and what it was built from."""

    spec: JigSpec
    part: GuidePart
    body: cq.Workplane
    depth_mm: float
    plate_thickness_mm: float
    clearance_mm: float
    profile_id: str
    tolerance_status: str
    bores: tuple[Bore, ...]
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


def bore_diameter_mm(insert_diameter: float, fits: dict[str, float]) -> float:
    """The CAD diameter of a bore: the insert's, the sliding clearance each side, and the
    printer's hole oversize, since a printer prints holes small."""

    return (
        insert_diameter + 2 * fits["sliding_clearance_per_side"] + fits["hole_oversize"]
    )


def _distance_to_outline(point: Point, outline: tuple[Point, ...]) -> float:
    """How far a point is from the nearest edge of a closed outline."""

    best = math.inf

    for a, b in zip(outline, (*outline[1:], outline[0]), strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = (
            0.0
            if length2 == 0
            else max(
                0.0,
                min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2),
            )
        )
        best = min(best, math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy))

    return best


def _inside_outline(point: Point, outline: tuple[Point, ...]) -> bool:
    inside = False

    for a, b in zip(outline, (*outline[1:], outline[0]), strict=True):
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0] + (point[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])

            if point[0] < x:
                inside = not inside

    return inside


def plan_bores(
    sites: tuple[InsertSite, ...],
    diameter: float,
    outline: tuple[Point, ...],
    least_wall: float,
) -> tuple[tuple[Bore, ...], list[str]]:
    """The bores, or why they cannot be: each lies wholly in the part's shadow, and two keep at
    least a minimum wall between them."""

    bores = tuple(
        Bore(site.identifier, (site.x_mm, site.y_mm), diameter) for site in sites
    )
    errors: list[str] = []

    for bore in bores:
        if not _inside_outline(bore.centre, outline):
            errors.append(
                f"{bore.identifier}: ({bore.centre[0]:g}, {bore.centre[1]:g}) is outside the "
                "part's shadow"
            )
        elif _distance_to_outline(bore.centre, outline) < diameter / 2:
            errors.append(
                f"{bore.identifier}: its {diameter:.1f} mm bore would reach past the edge of "
                "the part's shadow"
            )

    for index, first in enumerate(bores):
        for second in bores[index + 1 :]:
            between = math.dist(first.centre, second.centre) - diameter

            if between < least_wall:
                errors.append(
                    f"{first.identifier} and {second.identifier} leave {max(between, 0):.1f} mm "
                    f"of plate between their bores; the printer's least wall is "
                    f"{least_wall:g} mm"
                )

    return bores, errors


def iron_errors(
    spec: JigSpec, diameter: float, clearance: float, least_wall: float
) -> list[str]:
    """Why the iron cannot work in the bore: its tip must go down it with a clearance, and its
    shoulder must stand on the plate with a wall's width of land."""

    iron = spec.iron
    errors = []

    if iron.tip_diameter_mm > diameter - clearance:
        errors.append(
            f"The iron's {iron.tip_diameter_mm:g} mm tip will not go down a {diameter:.1f} mm "
            f"bore with {clearance:g} mm to spare: use a tip under {diameter - clearance:.1f} mm"
        )

    if iron.shoulder_diameter_mm < diameter + 2 * least_wall:
        errors.append(
            f"The iron's {iron.shoulder_diameter_mm:g} mm shoulder would not stand on the "
            f"plate round a {diameter:.1f} mm bore: it must be at least "
            f"{diameter + 2 * least_wall:.1f} mm"
        )

    return errors


def build_jig(spec: JigSpec, part: GuidePart, profile: dict[str, Any]) -> Jig:
    """The nest and plate for a part, with a bore over each insert; refused if a wall or the
    plate is under the printer's minimum, the iron does not fit, or the part would not lift."""

    fits, least_wall, least_floor = printer_numbers(profile)
    clearance = fits["sliding_clearance_per_side"]

    if spec.wall_mm < least_wall:
        raise ValueError(
            f"jig.wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm minimum wall"
        )

    depth = pocket_depth_mm(spec, part)

    if depth > part.height_mm + 1e-6:
        raise ValueError(
            f"jig.depth_mm is {depth:g}, deeper than the part's {part.height_mm:.1f} mm height"
        )

    insert_diameter, _ = insert_figures(spec)
    diameter = bore_diameter_mm(insert_diameter, fits)
    outline = part.silhouette.points
    bores, problems = plan_bores(spec.sites, diameter, outline, least_wall)
    problems += iron_errors(spec, diameter, clearance, least_wall)
    thickness = spec.iron.tip_length_mm - spec.depth_below_face_mm

    if thickness < least_floor:
        problems.append(
            f"The iron's {spec.iron.tip_length_mm:g} mm tip, stopping {spec.depth_below_face_mm:g} "
            f"mm below the face, makes a plate {thickness:g} mm thick, under the printer's "
            f"{least_floor:g} mm minimum"
        )

    if problems:
        raise ValueError("The jig cannot be built:\n- " + "\n- ".join(problems))

    body = pocketed(
        outline,
        clearance_mm=clearance,
        wall_mm=spec.wall_mm,
        outer_z0=-depth,
        outer_z1=thickness,
        pocket_z0=-depth - 1.0,
        pocket_z1=0.0,
    )

    for bore in bores:
        body = body.cut(
            cq.Workplane("XY")
            .circle(bore.diameter_mm / 2)
            .extrude(thickness + 2.0)
            .translate((bore.centre[0], bore.centre[1], -1.0))
        )

    solid = body.val()
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "part_fits_pocket": clear(solid, part.shape),
        "part_lifts_out": lifts_off(solid, part.shape, part.height_mm),
        "bores_open": _bores_open(solid, bores, thickness),
        "iron_reaches_insert": abs(
            (thickness - spec.iron.tip_length_mm) + spec.depth_below_face_mm
        )
        < 1e-9,
    }

    return Jig(
        spec=spec,
        part=part,
        body=body,
        depth_mm=depth,
        plate_thickness_mm=thickness,
        clearance_mm=clearance,
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        bores=bores,
        checks=checks,
        warnings=(),
    )


def _bores_open(body: object, bores: tuple[Bore, ...], thickness: float) -> bool:
    """Each bore, as a cylinder through the plate, meets no material."""

    if not isinstance(body, cq.Shape):
        raise TypeError("Expected a shape")

    for bore in bores:
        cylinder = cq.Solid.makeCylinder(
            bore.diameter_mm / 2,
            thickness,
            pnt=cq.Vector(bore.centre[0], bore.centre[1], 0.0),
            dir=cq.Vector(0, 0, 1),
        )

        if intersection_volume(body, cylinder) > TOLERANCE_MM3:
            return False

    return True


def print_oriented(jig: Jig) -> cq.Workplane:
    """The jig as it goes on the bed: plate down, so the plate's face is the flat one against the
    bed and the nest opens upward."""

    return jig.body.rotate((0, 0, 0), (1, 0, 0), 180)


def require_fits_bed(jig: Jig, profile: dict[str, Any]) -> None:
    """Refuse a jig that will not lie on the printer's bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, height = jig.size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or turned) or height > volume["z"]:
        raise ValueError(
            f"The jig is {width:.0f} x {depth:.0f} x {height:.0f} mm; the printer's bed is "
            f"{volume['x']:.0f} x {volume['y']:.0f} x {volume['z']:.0f} mm"
        )


def jig_record(jig: Jig, files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a build says of itself: the part by hash, the settings, the iron's figures and their
    source, what was placed, and that it is unverified."""

    spec, part = jig.spec, jig.part
    width, depth, height = jig.size_mm
    diameter, length = insert_figures(spec)

    return {
        "schema_version": JIG_RECORD_SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "design_name": spec.identifier.lower().replace("_", "-"),
        "jig_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "part": {
            "path": str(spec.part_path),
            "sha256": part.sha256,
            "solid_index": spec.solid_index,
            "size_mm": [round(part.size_mm[0], 3), round(part.size_mm[1], 3)],
            "height_mm": round(part.height_mm, 3),
        },
        "settings": {
            "depth_mm": round(jig.depth_mm, 3),
            "wall_mm": spec.wall_mm,
            "depth_below_face_mm": spec.depth_below_face_mm,
            "plate_thickness_mm": round(jig.plate_thickness_mm, 3),
            "clearance_per_side_mm": jig.clearance_mm,
        },
        "insert": {
            "size": spec.insert_size,
            "diameter_mm": diameter,
            "length_mm": length,
        },
        "iron": {
            "tip_diameter_mm": spec.iron.tip_diameter_mm,
            "shoulder_diameter_mm": spec.iron.shoulder_diameter_mm,
            "tip_length_mm": spec.iron.tip_length_mm,
            "source": spec.iron.source,
        },
        "bores": [bore.to_dict() for bore in jig.bores],
        "size_mm": [round(width, 3), round(depth, 3), round(height, 3)],
        "printer_profile_id": jig.profile_id,
        "tolerance_status": jig.tolerance_status,
        "parts": files,
        "fit_checks": jig.checks,
        "verified": False,
        "not_claimed": NOT_CLAIMED,
    }


def write_jig_record(
    jig: Jig, files: dict[str, dict[str, Any]], output_directory: Path
) -> Path:
    """Write ``jig.json``; refuses to replace one."""

    path = output_directory / JIG_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(jig_record(jig, files), indent=2, sort_keys=True) + "\n", "utf-8"
    )

    return path
