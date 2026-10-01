"""Build a drill guide's nest and plate around a part.

The nest is a pocket on the underside that follows the part's shadow, widened
by the printer's sliding clearance; the plate is a slab above it, resting on
the part's top face. This release builds that shell, with its release check and
a build record that names the part by hash and says the guide is unverified.
The bores that make it a drill guide come in the next.

Frame: the guide's own, as in :mod:`zcad_core.features.guide_file`. The part's
top is ``z == 0``; the nest runs down from it and the plate up.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.guide_file import GuidePart, GuideSpec
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.geometry.outline_prism import outline_prism

GUIDE_RECORD_SCHEMA_VERSION = "1.0.0"
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
    clearance_mm: float
    profile_id: str
    tolerance_status: str
    checks: dict[str, bool]

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def size_mm(self) -> tuple[float, float, float]:
        box = self.body.val().BoundingBox()  # type: ignore[union-attr]

        return box.xlen, box.ylen, box.zlen


def _tolerance(profile: dict[str, Any], name: str) -> float:
    value = profile.get("tolerances_mm", {}).get(name)

    if value is None:
        raise ValueError(f"The printer profile has no tolerances_mm.{name}")

    return float(value)


def build_guide(spec: GuideSpec, part: GuidePart, profile: dict[str, Any]) -> Guide:
    """The nest and plate for a part, refused if a wall or the plate is under
    the printer's minimum or the part would not lift out."""

    clearance = _tolerance(profile, "sliding_clearance_per_side")
    minimums = profile.get("minimums_mm", {})
    least_wall = float(minimums.get("wall", 1.2))
    least_floor = float(minimums.get("floor", 1.2))

    if spec.nest_wall_mm < least_wall:
        raise ValueError(
            f"nest.wall_mm is {spec.nest_wall_mm:g}, under the printer's "
            f"{least_wall:g} mm minimum wall"
        )

    if spec.plate_thickness_mm < least_floor:
        raise ValueError(
            f"plate.thickness_mm is {spec.plate_thickness_mm:g}, under the "
            f"printer's {least_floor:g} mm minimum"
        )

    points = part.silhouette.points
    outer = outline_prism(
        points,
        -spec.nest_depth_mm,
        spec.plate_thickness_mm,
        clearance + spec.nest_wall_mm,
    )
    pocket = outline_prism(points, -spec.nest_depth_mm - 1.0, 0.0, clearance)
    body = outer.cut(pocket)
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "part_fits_pocket": _clear(body.val(), part.shape),
        "part_lifts_out": _lifts_out(body.val(), part),
    }

    return Guide(
        spec=spec,
        part=part,
        body=body,
        clearance_mm=clearance,
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        checks=checks,
    )


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
        if (
            intersection_volume(
                body.moved(cq.Location(cq.Vector(0, 0, lift))), part.shape
            )
            > _TOLERANCE_MM3
        ):
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


def guide_record(guide: Guide, files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a build says about itself: the guide file and the part by hash, the
    numbers and tolerances used, and that nothing here is verified."""

    spec, part = guide.spec, guide.part

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
            "clearance_per_side_mm": guide.clearance_mm,
        },
        "plate": {"thickness_mm": spec.plate_thickness_mm},
        "printer_profile_id": guide.profile_id,
        "tolerance_status": guide.tolerance_status,
        "bores": [],
        "checks": guide.checks,
        # The engine states no accuracy: a trial measures it.
        "verified": False,
        "parts": files,
    }


def write_guide_record(
    guide: Guide, files: dict[str, dict[str, Any]], directory: Path
) -> Path:
    """Write ``guide.json`` beside the exported parts; refuses to overwrite."""

    path = directory / GUIDE_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(guide_record(guide, files), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return path
