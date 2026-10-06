"""Ways of wearing a housing: a strap, a band, a belt clip, an adhesive plate, a
lanyard.

Each is a feature added to the housing's body, built from figures **the user gives
with a source**: a strap's width and its spring bar's diameter, a band's width and
thickness, a belt's thickness, a patch's outline, a cord's diameter. The engine has no
figure for any of them, and a file that leaves an ``EXAMPLE`` source in is refused. It
checks that each fits the housing, and that two do not take the same place. It states
nothing about how well any holds a body, and no print has shown yet that any prints
cleanly.

The body's frame is the housing part's own: ``x`` along the device's length, ``y``
across it, the skin side at the lowest ``z`` and the face away from the body above.

- **strap**: two lugs at the two ends, each a pair of prongs flanking the strap, with a
  hole across them for a spring bar.
- **band**: two ears at the two ends on the skin plane, each with a slot the band
  threads through.
- **clip**: a spring arm under the housing, fixed at one end of the back and
  free at the other, with a nub that grips a belt slid between it and the back. The arm
  bends up and down along its length, so it has length to spare, and its strain is the
  end-loaded cantilever's, checked against the provisional limit as the snap tabs' are.
- **adhesive**: a flat flange of the patch's outline at the skin plane, all one piece
  with the housing.
- **lanyard**: a flat tab on the +Y side with a hole for a cord.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.housing_skin import round_free_skin_edge
from zcad_core.features.mounts import (
    flexure_for,
    flexure_strain_limit,
    strain_limit_source,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.hardware.electronics import board_outline

WEAR_KINDS = ("strap", "band", "clip", "adhesive", "lanyard")
# What each takes, the figure's name and its allowed range in millimetres.
FIGURES: dict[str, dict[str, tuple[float, float]]] = {
    "strap": {"strap_width_mm": (8.0, 40.0), "bar_diameter_mm": (1.0, 4.0)},
    "band": {"band_width_mm": (8.0, 60.0), "band_thickness_mm": (0.5, 6.0)},
    "clip": {"belt_thickness_mm": (1.0, 12.0)},
    "adhesive": {},
    "lanyard": {"cord_diameter_mm": (0.5, 8.0)},
}
PATCH_RANGE_MM = (20.0, 200.0)
# Two ways of wearing that take the same place.
CONFLICTS = (
    ("strap", "band", "both stand on the two ends"),
    ("adhesive", "clip", "both are on the skin side"),
    ("adhesive", "band", "both are on the skin plane"),
)
LUG_THICKNESS_MM = 2.0
RING_MM = 1.5
BAR_OFFSET_MM = 3.0
EMBED_MM = 0.5
WEB_MM = 1.0
EAR_MARGIN_MM = 1.5
EAR_THICKNESS_MM = 2.0
TAB_THICKNESS_MM = 2.0
CLIP_WIDTH_MM = 12.0
CLIP_ARM_MM = 18.0
CLIP_POST_MM = 3.0
CLIP_THICKNESS_MM = 1.2
CLIP_NUB_MM = 1.0
CLIP_GRIP_MM = 0.4
BELT_CLEARANCE_MM = 0.4
PATCH_MARGIN_MM = 2.0
MINIMUM_STRAIGHT_MM = 2.0
_TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class Wear:
    """One way of wearing, with the user's figures and where they came from."""

    kind: str
    figures: Mapping[str, Any]
    source: str


@dataclass(frozen=True)
class Body:
    """The housing's body as a wearing option sees it: its box, and the radius of its
    outer vertical corners."""

    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float
    corner_radius_mm: float
    # How much to round the free edge of a flat feature on the skin plane.
    skin_radius_mm: float = 0.0

    @property
    def region(self) -> tuple[float, float, float, float]:
        return self.xmin, self.xmax, self.ymin, self.ymax

    @property
    def length(self) -> float:
        return self.xmax - self.xmin

    @property
    def width(self) -> float:
        return self.ymax - self.ymin

    @property
    def height(self) -> float:
        return self.zmax - self.zmin

    @property
    def mid_z(self) -> float:
        return (self.zmin + self.zmax) / 2

    @property
    def straight_y(self) -> float:
        """Half the length of an end face's straight run, across it."""

        return self.width / 2 - self.corner_radius_mm

    @property
    def straight_x(self) -> float:
        return self.length / 2 - self.corner_radius_mm


def body_of(
    model: cq.Workplane, corner_radius_mm: float, skin_radius_mm: float = 0.0
) -> Body:
    """The body of a built housing part."""

    box = workplane_shape(model).BoundingBox()

    return Body(
        box.xmin,
        box.xmax,
        box.ymin,
        box.ymax,
        box.zmin,
        box.zmax,
        corner_radius_mm,
        skin_radius_mm,
    )


def conflicts(kinds: list[str]) -> list[str]:
    """Each pair of ways of wearing that take the same place."""

    return [
        f"{a} and {b} cannot be worn together: {why}"
        for a, b, why in CONFLICTS
        if a in kinds and b in kinds
    ]


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            x[1] - x[0], y[1] - y[0], z[1] - z[0], pnt=cq.Vector(x[0], y[0], z[0])
        )
    )


def _hole_along_y(
    x: float, z: float, diameter: float, y0: float, y1: float
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeCylinder(
            diameter / 2, y1 - y0, pnt=cq.Vector(x, y0, z), dir=cq.Vector(0, 1, 0)
        )
    )


def _hole_along_z(
    x: float, y: float, z0: float, z1: float, diameter: float
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeCylinder(
            diameter / 2, z1 - z0, pnt=cq.Vector(x, y, z0), dir=cq.Vector(0, 0, 1)
        )
    )


def _strap(
    body: Body, figures: Mapping[str, Any], hole_oversize: float
) -> tuple[cq.Workplane, cq.Workplane, dict[str, Any], list[str]]:
    width = float(figures["strap_width_mm"])
    bar = float(figures["bar_diameter_mm"])
    hole = bar + hole_oversize + 0.1
    errors: list[str] = []
    half = width / 2 + LUG_THICKNESS_MM
    prong_height = hole + 2 * RING_MM

    if 2 * half > body.width + 1e-9:
        errors.append(
            f"A {width:g} mm strap needs lugs {2 * half:.1f} mm across, and the "
            f"housing is {body.width:.1f} mm wide: the widest strap is "
            f"{body.width - 2 * LUG_THICKNESS_MM:.1f} mm"
        )

    if prong_height > body.height + 1e-9:
        errors.append(
            f"The lugs for a {bar:g} mm bar are {prong_height:.1f} mm tall and the "
            f"housing is {body.height:.1f} mm: it is too thin for them"
        )

    if body.straight_y < MINIMUM_STRAIGHT_MM:
        errors.append(
            "The housing's ends are too rounded to hold a strap's lugs: lower its "
            "corner radius"
        )

    add, cut = cq.Workplane("XY"), cq.Workplane("XY")

    if not errors:
        reach = BAR_OFFSET_MM + prong_height / 2
        z = (body.mid_z - prong_height / 2, body.mid_z + prong_height / 2)

        for sign, end in ((1.0, body.xmax), (-1.0, body.xmin)):
            near, far = end - sign * EMBED_MM, end + sign * reach
            x = (min(near, far), max(near, far))
            lug = _box(x, (-half, half), z)
            channel_near = end + sign * WEB_MM
            channel_far = end + sign * (reach + 1.0)
            channel = _box(
                (min(channel_near, channel_far), max(channel_near, channel_far)),
                (-width / 2, width / 2),
                (z[0] - 0.1, z[1] + 0.1),
            )
            add = add.union(lug.cut(channel))
            cut = cut.union(
                _hole_along_y(
                    end + sign * BAR_OFFSET_MM, body.mid_z, hole, -half - 1, half + 1
                )
            )

    summary = {
        "kind": "strap",
        "where": "at the two ends at mid-height, beyond the end faces",
        "proud_mm": 0.0,
        "strap_width_mm": width,
        "bar_diameter_mm": bar,
        "bar_hole_mm": round(hole, 3),
        "lug_across_mm": round(2 * half, 3),
        "lug_height_mm": round(prong_height, 3),
    }

    return add, cut, summary, errors


def _band(
    body: Body, figures: Mapping[str, Any]
) -> tuple[cq.Workplane, cq.Workplane, dict[str, Any], list[str]]:
    width = float(figures["band_width_mm"])
    thickness = float(figures["band_thickness_mm"])
    slot_x, slot_y = thickness + 1.0, width + 1.0
    ear_y = width + 2 * EAR_MARGIN_MM
    errors: list[str] = []

    if ear_y > body.width + 1e-9:
        errors.append(
            f"A {width:g} mm band needs ears {ear_y:.1f} mm wide, and the housing is "
            f"{body.width:.1f} mm wide: the widest band is "
            f"{body.width - 2 * EAR_MARGIN_MM:.1f} mm"
        )

    if body.straight_y < MINIMUM_STRAIGHT_MM:
        errors.append(
            "The housing's ends are too rounded to hold a band's ears: lower its "
            "corner radius"
        )

    add, cut = cq.Workplane("XY"), cq.Workplane("XY")
    reach = EAR_MARGIN_MM + slot_x + RING_MM

    if not errors:
        z = (body.zmin, body.zmin + EAR_THICKNESS_MM)

        for sign, end in ((1.0, body.xmax), (-1.0, body.xmin)):
            near, far = end - sign * EMBED_MM, end + sign * reach
            ear = _box((min(near, far), max(near, far)), (-ear_y / 2, ear_y / 2), z)
            add = add.union(round_free_skin_edge(ear, body.skin_radius_mm, body.region))
            s0 = end + sign * EAR_MARGIN_MM
            s1 = s0 + sign * slot_x
            cut = cut.union(
                _box(
                    (min(s0, s1), max(s0, s1)),
                    (-slot_y / 2, slot_y / 2),
                    (z[0] - 0.1, z[1] + 0.1),
                )
            )

    summary = {
        "kind": "band",
        "band_width_mm": width,
        "band_thickness_mm": thickness,
        "slot_mm": [round(slot_x, 3), round(slot_y, 3)],
        "ear_width_mm": round(ear_y, 3),
        "where": "on the skin plane, flush with it",
        "proud_mm": 0.0,
    }

    return add, cut, summary, errors


def _clip(
    body: Body, figures: Mapping[str, Any]
) -> tuple[cq.Workplane, cq.Workplane, dict[str, Any], list[str]]:
    belt = float(figures["belt_thickness_mm"])
    gap = belt + BELT_CLEARANCE_MM
    arm = min(CLIP_ARM_MM, body.length - CLIP_POST_MM - 2 * body.corner_radius_mm)
    deflection = CLIP_NUB_MM - BELT_CLEARANCE_MM
    errors: list[str] = []
    flexure = flexure_for(deflection, max(arm, 0.1), CLIP_THICKNESS_MM)

    if arm <= 0 or flexure.strain > flexure_strain_limit():
        needed = math.ceil(
            math.sqrt(3 * CLIP_THICKNESS_MM * deflection / (2 * flexure_strain_limit()))
        )
        errors.append(
            f"The housing is {body.length:.1f} mm long, so the belt clip's spring arm "
            f"is {max(arm, 0.0):.1f} mm and would strain "
            f"{100 * flexure.strain:.1f} per cent, over the "
            f"{100 * flexure_strain_limit():g} per cent limit: it needs an arm "
            f"{needed} mm long"
        )

    width = min(CLIP_WIDTH_MM, body.width - 2 * body.corner_radius_mm)

    if width < CLIP_WIDTH_MM / 2:
        errors.append(
            "The housing's back is too narrow and too rounded for a belt clip"
        )

    add, cut = cq.Workplane("XY"), cq.Workplane("XY")

    if not errors:
        post_x = (body.xmax - CLIP_POST_MM, body.xmax)
        arm_x = (post_x[0] - arm, post_x[0] + 0.01)
        top = body.zmin - gap
        y = (-width / 2, width / 2)
        add = (
            _box(post_x, y, (top - CLIP_THICKNESS_MM, body.zmin + EMBED_MM))
            .union(_box(arm_x, y, (top - CLIP_THICKNESS_MM, top)))
            .union(_box((arm_x[0], arm_x[0] + 3.0), y, (top, top + CLIP_NUB_MM)))
        )

    summary = {
        "kind": "clip",
        "where": "on the back, where the belt goes, standing proud of it",
        "proud_mm": round(gap + CLIP_THICKNESS_MM, 3),
        "belt_thickness_mm": belt,
        "belt_gap_mm": round(gap, 3),
        "arm_length_mm": round(arm, 3),
        "arm_thickness_mm": CLIP_THICKNESS_MM,
        "deflection_mm": round(deflection, 3),
        "strain_percent": round(100 * flexure.strain, 2),
        "strain_limit_percent": round(100 * flexure_strain_limit(), 2),
        "strain_limit_source": strain_limit_source(),
    }

    return add, cut, summary, errors


def _adhesive(
    body: Body, figures: Mapping[str, Any], thickness_mm: float
) -> tuple[cq.Workplane, cq.Workplane, dict[str, Any], list[str]]:
    patch = figures["patch_mm"]
    width, depth = float(patch[0]), float(patch[1])
    errors: list[str] = []
    need_x, need_y = body.length + 2 * PATCH_MARGIN_MM, body.width + 2 * PATCH_MARGIN_MM

    if body.skin_radius_mm > thickness_mm - 0.1:
        errors.append(
            f"The flange is {thickness_mm:g} mm thick and cannot have its edge rounded "
            f"to {body.skin_radius_mm:g} mm: use a thicker floor or a smaller "
            "skin_edge_radius_mm"
        )

    if width < need_x or depth < need_y:
        errors.append(
            f"A {width:g} x {depth:g} mm patch does not hold the {body.length:.1f} x "
            f"{body.width:.1f} mm housing with {PATCH_MARGIN_MM:g} mm to spare: it "
            f"needs {need_x:.1f} x {need_y:.1f} mm"
        )

    radius = float(figures.get("corner_radius_mm", min(width, depth) / 4))
    add = cq.Workplane("XY")

    if not errors:
        points = board_outline.rounded_rectangle_points(
            width, depth, min(radius, min(width, depth) / 2 - 0.01)
        )
        centre = ((body.xmin + body.xmax) / 2, (body.ymin + body.ymax) / 2)
        flange = outline_prism(points, 0.0, thickness_mm).translate(
            (centre[0], centre[1], body.zmin)
        )
        add = round_free_skin_edge(flange, body.skin_radius_mm, body.region)

    summary = {
        "kind": "adhesive",
        "where": "on the skin plane, flush with it",
        "proud_mm": 0.0,
        "patch_mm": [width, depth],
        "plate_thickness_mm": thickness_mm,
        "corner_radius_mm": round(radius, 3),
    }

    return add, cq.Workplane("XY"), summary, errors


def _lanyard(
    body: Body, figures: Mapping[str, Any]
) -> tuple[cq.Workplane, cq.Workplane, dict[str, Any], list[str]]:
    cord = float(figures["cord_diameter_mm"])
    hole = cord + 1.0
    across = hole + 2 * RING_MM
    errors: list[str] = []

    if across > 2 * body.straight_x + 1e-9:
        errors.append(
            f"The lanyard tab for a {cord:g} mm cord is {across:.1f} mm wide and the "
            f"housing's straight side is {2 * body.straight_x:.1f} mm"
        )

    add, cut = cq.Workplane("XY"), cq.Workplane("XY")

    if not errors:
        reach = RING_MM + hole + RING_MM
        tab = _box(
            (-across / 2, across / 2),
            (body.ymax - EMBED_MM, body.ymax + reach),
            (body.zmin, body.zmin + TAB_THICKNESS_MM),
        )
        add = round_free_skin_edge(tab, body.skin_radius_mm, body.region)
        cut = _hole_along_z(
            0.0,
            body.ymax + RING_MM + hole / 2,
            body.zmin - 0.1,
            body.zmin + TAB_THICKNESS_MM + 0.1,
            hole,
        )

    summary = {
        "kind": "lanyard",
        "where": "on the +Y side, on the skin plane, flush with it",
        "proud_mm": 0.0,
        "cord_diameter_mm": cord,
        "hole_mm": round(hole, 3),
        "tab_width_mm": round(across, 3),
    }

    return add, cut, summary, errors


def add_wear(
    model: cq.Workplane,
    body: Body,
    wears: tuple[Wear, ...],
    *,
    hole_oversize_mm: float,
    plate_mm: float,
) -> tuple[cq.Workplane, list[dict[str, Any]]]:
    """``model`` with each way of wearing added, and a summary of each; refused, with
    every problem listed, if any does not fit."""

    errors: list[str] = []
    summaries: list[dict[str, Any]] = []
    added = cq.Workplane("XY")
    cuts = cq.Workplane("XY")

    for wear in wears:
        if wear.kind == "strap":
            add, cut, summary, found = _strap(body, wear.figures, hole_oversize_mm)
        elif wear.kind == "band":
            add, cut, summary, found = _band(body, wear.figures)
        elif wear.kind == "clip":
            add, cut, summary, found = _clip(body, wear.figures)
        elif wear.kind == "adhesive":
            add, cut, summary, found = _adhesive(body, wear.figures, plate_mm)
        else:
            add, cut, summary, found = _lanyard(body, wear.figures)

        errors.extend(found)
        summary["source"] = wear.source
        summaries.append(summary)

        if not found and add.vals():
            added = added.union(add) if added.vals() else add

        if not found and cut.vals():
            cuts = cuts.union(cut) if cuts.vals() else cut

    if errors:
        raise ValueError(
            "The housing cannot be worn that way:\n- " + "\n- ".join(errors)
        )

    if added.vals():
        model = model.union(added)

    if cuts.vals():
        model = model.cut(cuts)

    return model, summaries
