"""Build a drill guide: a nest around a part, and a plate with the bores in it.

The nest is a pocket on the underside that follows the part's shadow, widened
by the printer's sliding clearance; the plate is a slab above it, resting on
the part's top face, with a bore for each hole the user wants: a printed hole,
or a pocket for a steel bushing. The build refuses a guide whose bores do not
fit the plate and the part, or whose chuck cannot stand clear to reach the
depth. Its record names the part by hash and says the guide is unverified.

Frame: the guide's own, as in :mod:`zcad_core.features.guide_file`. The part's
top is ``z == 0``; the nest runs down from it and the plate up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.guide_bores import (
    BorePlan,
    PlannedBore,
    Sections,
    axis_point,
    bit_needed,
    chuck_standoff,
    flange_solids,
    plan_bores,
    play_bounds,
    printer_numbers,
)
from zcad_core.features.guide_file import (
    DEFAULT_PLATE_MM,
    MINIMUM_BEARING_AREA_MM2,
    GuidePart,
    GuideSpec,
    nest_outline,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.profiles.guide_accuracy import GuideAccuracyProfile

GUIDE_RECORD_SCHEMA_VERSION = "4.0.0"
GUIDE_RECORD = "guide.json"
# How far the guide is lifted off the part per step in the release check.
RELEASE_STEP_MM = 2.0
_TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class Guide:
    """The built guide and what it was built from."""

    spec: GuideSpec
    part: GuidePart
    body: cq.Workplane
    plate_thickness_mm: float
    # How far the plate's underside stands above the part's top: 0 when it
    # rests on the part.
    plate_base_mm: float
    bearing_area_mm2: float | None
    clearance_mm: float
    profile_id: str
    tolerance_status: str
    bores: tuple[PlannedBore, ...]
    play: dict[str, tuple[float, float]]
    checks: dict[str, bool]
    # Why a check failed, in words.
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return all(self.checks.values()) and not self.problems

    @property
    def size_mm(self) -> tuple[float, float, float]:
        box = self.body.val().BoundingBox()  # type: ignore[union-attr]

        return box.xlen, box.ylen, box.zlen


def _sections(spec: GuideSpec) -> Sections:
    return Sections(drill=spec.drill, bushing=spec.bushing, bores=spec.bores)


def _cutters(
    item: PlannedBore, sections: Sections, top_z: float, bottom_z: float
) -> cq.Workplane:
    """What a bore removes from the plate: the hole for the drill, through the
    plate, and for a bushing a wider pocket from the top down the bushing's
    length. Each is a cylinder on the bore's axis, started a millimetre above
    the plate and ended half a millimetre below it, in the nest's void."""

    cosine = -item.axis[2]
    start = axis_point(item, top_z + 1.0)
    base = cq.Vector(start[0], start[1], top_z + 1.0)
    direction = cq.Vector(*item.axis)
    through = (top_z + 1.0 - (bottom_z - 0.5)) / cosine
    cutter = cq.Workplane("XY").add(
        cq.Solid.makeCylinder(
            item.hole_diameter_mm / 2, through, pnt=base, dir=direction
        )
    )

    if item.pocket_diameter_mm is not None and sections.bushing is not None:
        depth = 1.0 / cosine + sections.bushing.body_length_mm
        cutter = cutter.union(
            cq.Workplane("XY").add(
                cq.Solid.makeCylinder(
                    item.pocket_diameter_mm / 2, depth, pnt=base, dir=direction
                )
            )
        )

    return cutter


def build_guide(spec: GuideSpec, part: GuidePart, profile: dict[str, Any]) -> Guide:
    """The nest and plate for a part, with its bores; refused if a wall or the
    plate is under the printer's minimum, a bore does not fit, or the part would
    not lift out."""

    fits, least_wall, least_floor = printer_numbers(profile)
    clearance = fits["sliding_clearance_per_side"]

    if spec.nest_wall_mm < least_wall:
        raise ValueError(
            f"nest.wall_mm is {spec.nest_wall_mm:g}, under the printer's "
            f"{least_wall:g} mm minimum wall"
        )

    sections = _sections(spec)
    outline = nest_outline(spec, part, clearance)

    if (
        outline.bearing_area_mm2 is not None
        and outline.bearing_area_mm2 < MINIMUM_BEARING_AREA_MM2
    ):
        raise ValueError(
            f"The part widens under the ledge nest by only "
            f"{outline.bearing_area_mm2:.1f} mm2; the least is "
            f"{MINIMUM_BEARING_AREA_MM2:g} mm2"
        )

    base_z = spec.nest_gap_mm
    plan: BorePlan = plan_bores(
        sections,
        height_mm=part.height_mm,
        shadow=outline.points,
        tolerances=fits,
        minimum_wall_mm=least_wall,
        nest_wall_mm=spec.nest_wall_mm,
        plate_thickness_mm=spec.plate_thickness_mm,
        default_plate_mm=DEFAULT_PLATE_MM,
        plate_base_mm=base_z,
    )

    if plan.errors:
        raise ValueError("The bores cannot be built:\n- " + "\n- ".join(plan.errors))

    thickness = plan.plate_thickness_mm

    if thickness < least_floor:
        raise ValueError(
            f"plate.thickness_mm is {thickness:g}, under the printer's "
            f"{least_floor:g} mm minimum"
        )

    top_z = base_z + thickness
    points = outline.points
    outer = outline_prism(
        points, -spec.nest_depth_mm, top_z, clearance + spec.nest_wall_mm
    )
    pocket = outline_prism(points, -spec.nest_depth_mm - 1.0, base_z, clearance)
    body = outer.cut(pocket)

    for item in plan.bores:
        body = body.cut(_cutters(item, sections, top_z, base_z))

    solid = body.val()
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "part_fits_pocket": _clear(solid, part.shape),
        "part_lifts_out": _lifts_out(solid, part),
        "bores_open": _bores_open(solid, plan.bores, top_z),
    }
    reached, problems = _reach(body, plan.bores, sections, thickness, base_z)
    checks["bit_reaches_depth"] = not problems
    play = {
        item.bore.identifier: play_bounds(item, sections, fits, clearance)
        for item in plan.bores
    }

    return Guide(
        spec=spec,
        part=part,
        body=body,
        plate_thickness_mm=thickness,
        plate_base_mm=base_z,
        bearing_area_mm2=outline.bearing_area_mm2,
        clearance_mm=clearance,
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        bores=reached,
        play=play,
        checks=checks,
        problems=tuple(problems),
        warnings=plan.warnings,
    )


def _reach(
    body: cq.Workplane,
    planned: tuple[PlannedBore, ...],
    sections: Sections,
    thickness: float,
    base_z: float,
) -> tuple[tuple[PlannedBore, ...], list[str]]:
    """Slide the chuck up each bore's axis until it clears the plate and any
    bushing flange, and say how much bit must stand out of it to reach the
    depth; refuse a bit that is too short."""

    drill = sections.drill
    shape = body.val()

    if drill is None or not planned or not isinstance(shape, cq.Shape):
        return planned, []

    assembly = cq.Compound.makeCompound(
        [shape, *flange_solids(planned, sections, base_z + thickness)]
    )
    reached: list[PlannedBore] = []
    problems: list[str] = []

    for item in planned:
        try:
            standoff = chuck_standoff(assembly, item, drill, base_z + thickness)
        except ValueError as error:
            problems.append(str(error))
            reached.append(item)

            continue

        needed = bit_needed(item, standoff, thickness, base_z)
        reached.append(item.with_reach(standoff, needed))

        if drill.stickout_mm is not None and needed > drill.stickout_mm + 1e-9:
            problems.append(
                f"{item.bore.identifier}: the drill must stand {needed:g} mm out of "
                f"its chuck to reach {item.bore.depth_mm:g} mm, and the file says it "
                f"stands out {drill.stickout_mm:g} mm"
            )

    return tuple(reached), problems


def _bores_open(body: object, planned: tuple[PlannedBore, ...], top_z: float) -> bool:
    """Each bore's drill, as a cylinder through the plate, meets no material."""

    if not isinstance(body, cq.Shape):
        raise TypeError("Expected a shape")

    for item in planned:
        cosine = -item.axis[2]
        top = top_z + 1.0
        origin = axis_point(item, top)
        drill = cq.Solid.makeCylinder(
            item.bore.diameter_mm / 2,
            top / cosine,
            pnt=cq.Vector(origin[0], origin[1], top),
            dir=cq.Vector(*item.axis),
        )

        if intersection_volume(body, drill) > _TOLERANCE_MM3:
            return False

    return True


def _clear(first: object, second: cq.Shape) -> bool:
    if not isinstance(first, cq.Shape):
        raise TypeError("Expected a shape")

    return intersection_volume(first, second) <= _TOLERANCE_MM3


def _lifts_out(body: object, part: GuidePart) -> bool:
    """Lift the guide off the part in steps, to clear of its whole height, and
    refuse one that meets the part on the way."""

    if not isinstance(body, cq.Shape):
        raise TypeError("Expected a shape")

    lift = RELEASE_STEP_MM

    while lift <= part.height_mm + RELEASE_STEP_MM:
        moved = body.moved(cq.Location(cq.Vector(0, 0, lift)))

        if intersection_volume(moved, part.shape) > _TOLERANCE_MM3:
            return False

        lift += RELEASE_STEP_MM

    return True


def print_oriented(guide: Guide) -> cq.Workplane:
    """The guide as it goes on the bed: plate down, so the plate's face is the
    flat one against the bed and the nest opens upward."""

    return guide.body.rotate((0, 0, 0), (1, 0, 0), 180)


def require_fits_bed(guide: Guide, profile: dict[str, Any]) -> None:
    """Refuse a guide that will not lie on the printer's bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, height = guide.size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or turned) or height > volume["z"]:
        raise ValueError(
            f"The guide is {width:.0f} x {depth:.0f} x {height:.0f} mm; the "
            f"printer's bed is {volume['x']:.0f} x {volume['y']:.0f} x "
            f"{volume['z']:.0f} mm"
        )


def measured_accuracy(
    guide: Guide, profile: GuideAccuracyProfile, material_profile_id: str
) -> dict[str, Any]:
    """What a guide accuracy profile says about this guide's bores, beside the
    play bound the build computed. Refuses a profile for another printer or
    material, whose offsets say nothing about this one."""

    if profile.printer_profile_id != guide.profile_id:
        raise ValueError(
            f"The accuracy profile is for printer {profile.printer_profile_id}; "
            f"this guide is for {guide.profile_id}"
        )

    if profile.material_profile_id != material_profile_id:
        raise ValueError(
            f"The accuracy profile is for {profile.material_profile_id}; this "
            f"guide is for {material_profile_id}"
        )

    bores = []

    for item in guide.bores:
        figure = profile.position(item.bore.kind)
        bound = guide.play[item.bore.identifier][0]
        bores.append(
            {
                "identifier": item.bore.identifier,
                "kind": item.bore.kind,
                "measured": figure,
                "play_bound_entry_mm": bound,
                # The measured offsets beating the bound say the profile's
                # clearances are tighter than the print: a finding, not an error.
                "measured_exceeds_bound": (
                    None if figure is None else figure["max"] > bound + 1e-9
                ),
            }
        )

    return {
        "profile": profile.reference(),
        "described": profile.describe(),
        "note": (
            "Measured offsets of drilled holes from passing trials on this "
            "printer and material. They are evidence about those prints and how "
            "they were measured, with the sample sizes given, and not a "
            "guarantee for this guide."
        ),
        "figures": profile.payload["figures"],
        "bores": bores,
    }


def guide_record(
    guide: Guide,
    files: dict[str, dict[str, Any]],
    *,
    material_profile_id: str = "",
    accuracy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What a build says about itself: the guide file and the part by hash, the
    numbers and tolerances used, the bores as placed, and that nothing here is
    verified."""

    spec, part = guide.spec, guide.part
    drill, bushing = spec.drill, spec.bushing

    return {
        "schema_version": GUIDE_RECORD_SCHEMA_VERSION,
        "design_type": "guide",
        "identifier": spec.identifier,
        "guide_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "part": {
            "step": str(spec.part_path),
            "sha256": part.sha256,
            "solid_index": spec.solid_index,
            "solids": part.solids,
            "size_mm": [round(v, 3) for v in part.size_mm],
            "height_mm": round(part.height_mm, 3),
            "shadow_area_mm2": round(part.silhouette.area_mm2, 1),
            "shadow_points": len(part.silhouette.points),
            "top_flat_share": round(part.silhouette.top_share, 3),
        },
        "nest": {
            "depth_mm": spec.nest_depth_mm,
            "wall_mm": spec.nest_wall_mm,
            "bearing": spec.bearing,
            "gap_mm": guide.plate_base_mm,
            "bearing_area_mm2": (
                None
                if guide.bearing_area_mm2 is None
                else round(guide.bearing_area_mm2, 1)
            ),
            "clearance_per_side_mm": guide.clearance_mm,
        },
        "plate": {
            "thickness_mm": guide.plate_thickness_mm,
            "sized_by": "file" if spec.plate_thickness_mm is not None else "bores",
        },
        "drill": None
        if drill is None
        else {
            "diameter_mm": drill.diameter_mm,
            "chuck_diameter_mm": drill.chuck_diameter_mm,
            "depth_mm": drill.depth_mm,
            "stickout_mm": drill.stickout_mm,
        },
        # The bushing's figures are the user's own unless the file named a catalogued
        # one, and the record says which.
        "bushing": None
        if bushing is None
        else {
            "inner_diameter_mm": bushing.inner_diameter_mm,
            "outer_diameter_mm": bushing.outer_diameter_mm,
            "length_mm": bushing.length_mm,
            "flange_diameter_mm": bushing.flange_diameter_mm,
            "flange_thickness_mm": bushing.flange_thickness_mm,
            "source": bushing.source,
            "figures_from": (
                "the catalogue; see the source"
                if bushing.source.startswith("catalog ")
                else "the user's file; no maker's datasheet has been read"
            ),
        },
        "bores": [
            {
                **item.to_dict(),
                "worst_case_entry_play_mm": guide.play[item.bore.identifier][0],
                "worst_case_tip_play_mm": guide.play[item.bore.identifier][1],
            }
            for item in guide.bores
        ],
        "play_note": (
            "Play is a bound from the printer profile's provisional clearances "
            "alone. It is not a measured positional accuracy, which only a trial "
            "gives."
        ),
        "printer_profile_id": guide.profile_id,
        "material_profile_id": material_profile_id,
        "measured": accuracy,
        "tolerance_status": guide.tolerance_status,
        "checks": guide.checks,
        # The engine states no accuracy: a trial measures it.
        "verified": False,
        "parts": files,
    }


def write_guide_record(
    guide: Guide,
    files: dict[str, dict[str, Any]],
    directory: Path,
    *,
    material_profile_id: str = "",
    accuracy: dict[str, Any] | None = None,
) -> Path:
    """Write ``guide.json`` beside the exported parts; refuses to overwrite."""

    path = directory / GUIDE_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(
            guide_record(
                guide, files, material_profile_id=material_profile_id, accuracy=accuracy
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return path
