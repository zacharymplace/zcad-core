"""Build a wearable housing: a cradle for a sealed device, or a case for a board.

A **cradle** (:mod:`zcad_core.features.housing_cradle`) is one printed tray the device
snaps into. A **case** is the single-board enclosure, with a snap lid so there is
nothing to screw, thinner walls, and the outer vertical corners rounded; its base,
lid, openings and standoffs or cradle are the enclosure builder's own.

The build refuses a housing that cannot work and checks the parts it makes. Nothing
here says how the housing is worn: this release builds one you hold. And nothing here
makes a claim about skin, water, comfort, or a device's function; see
``docs/roadmaps/wearable-housings.md``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.housing_cradle import (
    CradlePlan,
    build_cradle,
    device_envelope,
    half_across,
    plan_cradle,
)
from zcad_core.features.housing_file import HousingSpec, load_housing_input
from zcad_core.features.housing_wear import add_wear, body_of
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware.electronics.board_file import BoardFileSpec
from zcad_core.hardware.wearables import WearableCapture

_TOLERANCE_MM3 = 1e-6
# A snap lid's openings need the connector access the enclosure gives a plug.
_CONNECTOR_ACCESS_MM = 2.0
NOT_CLAIMED = (
    "The engine states no claim about skin contact or biocompatibility, water or "
    "sweat, comfort, or the device's function."
)


@dataclass(frozen=True)
class Housing:
    """The built parts, what was checked, and what the build refused or noted."""

    spec: HousingSpec
    parts: dict[str, cq.Workplane]
    checks: dict[str, bool]
    summary: dict[str, Any]
    profile_id: str
    notes: tuple[str, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


WEAR_NOT_CLAIMED = (
    "The engine states no figure for how well any way of wearing holds a body, and no "
    "print has shown that one prints cleanly: a trial measures that."
)


def _notes(spec: HousingSpec) -> tuple[str, ...]:
    return (NOT_CLAIMED, WEAR_NOT_CLAIMED) if spec.wear else (NOT_CLAIMED,)


def _wear(
    model: cq.Workplane,
    spec: HousingSpec,
    profile: Mapping[str, Any],
    corner_radius_mm: float,
) -> tuple[cq.Workplane, list[dict[str, Any]]]:
    """The body with each way of wearing added."""

    if not spec.wear:
        return model, []

    fits, _, _ = printer_numbers(profile)

    return add_wear(
        model,
        body_of(model, corner_radius_mm),
        spec.wear,
        hole_oversize_mm=fits["hole_oversize"],
        plate_mm=spec.floor_mm,
    )


def _single(model: cq.Workplane) -> bool:
    return len(model.solids().vals()) == 1


def _build_cradle(
    spec: HousingSpec, capture: WearableCapture, profile: Mapping[str, Any]
) -> Housing:
    plan = plan_cradle(
        capture,
        edges=spec.retention_edges,
        wall_mm=spec.wall_mm,
        floor_mm=spec.floor_mm,
        clearance_mm=spec.clearance_mm,
    )

    if plan.errors:
        raise ValueError("The housing cannot be built:\n- " + "\n- ".join(plan.errors))

    tray = build_cradle(
        capture,
        plan,
        wall_mm=spec.wall_mm,
        floor_mm=spec.floor_mm,
        clearance_mm=spec.clearance_mm,
    )
    tray, worn = _wear(
        tray,
        spec,
        profile,
        (capture.outline_radius_mm or 0.0) + spec.clearance_mm + spec.wall_mm,
    )
    shape = workplane_shape(tray)
    checks = {
        "one_solid": _single(tray),
        "device_fits_pocket": intersection_volume(
            shape, workplane_shape(device_envelope(capture))
        )
        <= _TOLERANCE_MM3,
        "edge_features_open": _features_open(tray, capture, spec),
    }

    return Housing(
        spec=spec,
        parts={"housing": tray},
        checks=checks,
        summary={**_cradle_summary(capture, plan, spec), "wear": worn},
        profile_id=str(profile.get("profile_id", "")),
        notes=_notes(spec),
    )


def _features_open(
    tray: cq.Workplane, capture: WearableCapture, spec: HousingSpec
) -> bool:
    """Each edge feature has a notch through the wall at its middle."""

    shape = workplane_shape(tray)

    for feature in capture.edge_features:
        angle = {"north": 0.0, "west": 90.0, "south": 180.0, "east": 270.0}[
            feature.edge
        ]
        sign = -1.0 if feature.edge in ("south", "east") else 1.0
        # Local (north) coordinates, then turned to the edge.
        x = sign * feature.center_offset_mm
        y = half_across(capture, feature.edge) + spec.clearance_mm + spec.wall_mm / 2
        rad = math.radians(angle)
        point = cq.Vector(
            x * math.cos(rad) - y * math.sin(rad),
            x * math.sin(rad) + y * math.cos(rad),
            capture.thickness_mm / 2,
        )

        if any(solid.isInside(point) for solid in shape.Solids()):
            return False

    return True


def _cradle_summary(
    capture: WearableCapture, plan: CradlePlan, spec: HousingSpec
) -> dict[str, Any]:
    return {
        "style": "cradle",
        "houses": capture.name,
        "device_sha256": capture.sha256,
        "device_mm": [capture.length_mm, capture.width_mm, capture.thickness_mm],
        "outer_size_mm": [round(v, 3) for v in plan.outer_size_mm],
        "tabs": [{"edge": tab.edge, "offset_mm": tab.offset_mm} for tab in plan.tabs],
        "tab": {
            "length_mm": plan.flexure.length_mm,
            "thickness_mm": plan.flexure.thickness_mm,
            "deflection_mm": plan.flexure.deflection_mm,
            "strain_percent": round(100 * plan.flexure.strain, 2),
            "strain_limit_percent": round(100 * plan.flexure.strain_limit, 2),
        },
        "edge_features_open": [f.identifier for f in capture.edge_features],
        "face_features_left_open": [f.identifier for f in capture.face_features],
        "wall_mm": spec.wall_mm,
        "floor_mm": spec.floor_mm,
        "clearance_mm": spec.clearance_mm,
    }


def corner_radius_limit_mm(wall_mm: float, least_wall_mm: float) -> float:
    """The largest radius that rounds an outer corner of a square cavity and leaves
    the diagonal of the wall at least the printer's minimum: the wall is
    ``wall * sqrt(2)`` along the diagonal, and a radius ``r`` takes ``r * (sqrt(2) -
    1)`` of it."""

    return max((wall_mm * math.sqrt(2) - least_wall_mm) / (math.sqrt(2) - 1), 0.0)


def _rounded(
    model: cq.Workplane, footprint: cq.BoundBox, radius: float
) -> cq.Workplane:
    """``model`` with its outer vertical corners rounded: cut to a rounded box over
    the footprint."""

    if radius <= 0:
        return model

    box = workplane_shape(model).BoundingBox()
    envelope = (
        cq.Workplane("XY")
        .box(footprint.xlen, footprint.ylen, box.zlen + 2.0)
        .edges("|Z")
        .fillet(radius)
        .translate(
            (
                (footprint.xmin + footprint.xmax) / 2,
                (footprint.ymin + footprint.ymax) / 2,
                box.zmin + box.zlen / 2,
            )
        )
    )

    return model.intersect(envelope)


def _build_case(
    spec: HousingSpec, board: BoardFileSpec, profile: Mapping[str, Any]
) -> Housing:
    _, least_wall, _ = printer_numbers(profile)
    limit = corner_radius_limit_mm(spec.wall_mm, least_wall)

    if spec.corner_radius_mm > limit + 1e-9:
        raise ValueError(
            f"A corner radius of {spec.corner_radius_mm:g} mm on a {spec.wall_mm:g} mm "
            f"wall leaves less than the printer's {least_wall:g} mm minimum along the "
            f"corner's diagonal: the most is {limit:.2f} mm, or use a thicker wall"
        )

    assembly = build_board_assembly(
        board=board,
        board_placement=Placement(),
        connector_access_clearance_mm=_CONNECTOR_ACCESS_MM,
    )
    enclosure = build_enclosure(
        assembly,
        board=board,
        design=EnclosureDesign(
            wall_mm=spec.wall_mm,
            floor_mm=spec.floor_mm,
            lid_mm=spec.lid_mm,
            lid_attachment="snap",
        ),
    )
    footprint = workplane_shape(enclosure.base).BoundingBox()
    base = _rounded(enclosure.base, footprint, spec.corner_radius_mm)
    base, worn = _wear(base, spec, profile, spec.corner_radius_mm)
    lid = _rounded(enclosure.lid, footprint, spec.corner_radius_mm)
    size = workplane_shape(base).BoundingBox()

    return Housing(
        spec=spec,
        parts={"base": base, "lid": lid},
        checks={"base_one_solid": _single(base), "lid_one_solid": _single(lid)},
        summary={
            "style": "case",
            "houses": board.identifier,
            "board_sha256": spec.input_sha256,
            "outer_size_mm": [
                round(size.xlen, 3),
                round(size.ylen, 3),
                round(size.zlen, 3),
            ],
            "lid": "snap",
            "wall_mm": spec.wall_mm,
            "floor_mm": spec.floor_mm,
            "lid_mm": spec.lid_mm,
            "corner_radius_mm": spec.corner_radius_mm,
            "corner_radius_limit_mm": round(limit, 2),
            "wear": worn,
        },
        profile_id=str(profile.get("profile_id", "")),
        notes=_notes(spec),
    )


def build_housing(spec: HousingSpec, profile: Mapping[str, Any]) -> Housing:
    """The housing a file describes, refused if it cannot work."""

    housed = load_housing_input(spec)

    if isinstance(housed, WearableCapture):
        return _build_cradle(spec, housed, profile)

    return _build_case(spec, housed, profile)


def print_oriented(housing: Housing) -> dict[str, cq.Workplane]:
    """Each part as it goes on the bed: a tray or a base on its floor, a lid on its
    outer face."""

    parts = {}

    for name, model in housing.parts.items():
        if name == "lid":
            model = model.rotate((0, 0, 0), (1, 0, 0), 180)

        low = workplane_shape(model).BoundingBox().zmin
        parts[name] = model.translate((0, 0, -low))

    return parts


def require_fits_bed(housing: Housing, profile: Mapping[str, Any]) -> None:
    """Refuse a part that will not lie on the printer's bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    for name, model in print_oriented(housing).items():
        box = workplane_shape(model).BoundingBox()
        fits = box.xlen <= volume["x"] and box.ylen <= volume["y"]
        turned = box.xlen <= volume["y"] and box.ylen <= volume["x"]

        if not (fits or turned) or box.zlen > volume["z"]:
            raise ValueError(
                f"The {name} is {box.xlen:.0f} x {box.ylen:.0f} x {box.zlen:.0f} mm; "
                f"the printer's bed is {volume['x']:.0f} x {volume['y']:.0f} x "
                f"{volume['z']:.0f} mm"
            )
