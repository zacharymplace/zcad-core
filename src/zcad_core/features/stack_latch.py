"""A printed snap latch between a foot and a lip: a hook on the foot, a keeper in the lip.

The foot of the upper item stands in the lip of the one below. A **hook** on the foot's side
catches in a **keeper**, a recess cut into the lip's inside face (or into a baseplate's pocket
wall), so the stack resists being pulled apart. The hook sits on a **tongue**: a strip of the
foot's outer skin, freed by a relief pocket cut up into the solid foot from its bottom and by a
slit at its free end and along its top, fixed at one end. It bends outward in plane, as the slide
lid's detent does, so it can be as long as the foot's side allows; a tongue bending through the
foot's height could not be long enough for the strain limit.

Sizes the profile gives: the foot's and lip's vertical faces (from its sections) and the gap
across the wall between them. Sizes the engine chooses: the hook's width, the slit, the flat on a
hook's tip, the relief behind the tongue, and a 45 degree ramp on each side of the hook, so the
unit goes on with a push and comes off with a pull. Each is provisional until a trial. The engine
states no holding force: a latch here is a detent that lets go to a pull.

Frames of reference: an item is centred on the origin and rests on ``z == 0``. A tongue is
built in the frame of its cell, with ``u`` along the side, ``v`` out from the cell's centre and
``z`` up, and then turned to its side and moved to its cell.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import cadquery as cq

from zcad_core.features.mounts import (
    FLEXURE_STRAIN_LIMIT,
    flexure_for,
    flexure_payload,
)
from zcad_core.features.stack_profile import StackProfile

SIDES = ("front", "back", "left", "right")
DEFAULT_SIDES = ("front", "back")
DEFAULT_ENGAGEMENT_MM = 0.4
ENGAGEMENT_RANGE_MM = (0.1, 1.5)
# The least engagement the engine builds: under it the printed fit swamps the hook.
MINIMUM_ENGAGEMENT_MM = 0.3
# A hook is this wide along the foot's side, and a slit is this wide: the engine's choices.
HOOK_WIDTH_MM = 6.0
SLIT_MM = 0.8
# The flat on a hook's tip, a nozzle's width, and the least vertical run to put a hook in.
HOOK_FLAT_MM = 0.4
MINIMUM_RUN_MM = 1.5
# How much farther than its deflection a tongue has room to move behind its skin.
RELIEF_MARGIN_MM = 0.4
# Straight foot left clear at each end of a tongue.
END_MARGIN_MM = 1.0
DEFAULT_LEAST_WALL_MM = 1.2
_ANGLES = {"back": 0.0, "front": 180.0, "left": 90.0, "right": -90.0}
# From a side toward the middle of the item, as (x, y).
_INWARD = {
    "back": (0.0, -1.0),
    "front": (0.0, 1.0),
    "left": (1.0, 0.0),
    "right": (-1.0, 0.0),
}
_EPSILON = 1e-6


@dataclass(frozen=True)
class LatchWindow:
    """Where a foot's vertical face and a lip's vertical face overlap in height."""

    z_low: float
    z_high: float
    foot_inset: float
    lip_inset: float

    @property
    def run_mm(self) -> float:
        return self.z_high - self.z_low

    @property
    def gap_mm(self) -> float:
        """The gap across the wall between the foot's face and the lip's face."""

        return self.foot_inset - self.lip_inset


@dataclass(frozen=True)
class LatchPlan:
    """The sizes of one latch, from a profile, an engagement and a printer."""

    window: LatchWindow
    engagement_mm: float
    # How far the hook stands out of the foot's face, and how deep a keeper is cut past the
    # face it is cut in.
    protrusion_mm: float
    keeper_clearance_mm: float
    tongue_thickness_mm: float
    deflection_mm: float
    reach_mm: float
    length_mm: float
    strain: float
    relief_mm: float
    foot_height_mm: float
    cell_top_mm: float
    corner_radius_mm: float
    lip_face_inset_mm: float
    foot_face_inset_mm: float
    nest_clearance_mm: float

    @property
    def keeper_depth_mm(self) -> float:
        """How deep a keeper is cut into the lip, past the lip's face."""

        return self.engagement_mm + self.keeper_clearance_mm

    @property
    def footprint_mm(self) -> float:
        """The length a tongue takes along a foot's side, with its end slit."""

        return self.length_mm + SLIT_MM

    def to_dict(self) -> dict[str, Any]:
        return {
            "engagement_mm": self.engagement_mm,
            "protrusion_mm": round(self.protrusion_mm, 3),
            "keeper_depth_mm": round(self.keeper_depth_mm, 3),
            "hook_width_mm": HOOK_WIDTH_MM,
            "hook_height_mm": round(self.window.run_mm, 3),
            "hook_flat_mm": round(self.window.run_mm - 2 * self.protrusion_mm, 3),
            "tongue_thickness_mm": self.tongue_thickness_mm,
            "tongue_length_mm": round(self.length_mm, 3),
            "tongue_reach_mm": round(self.reach_mm, 3),
            "tongue_deflection_mm": round(self.deflection_mm, 3),
            "relief_mm": round(self.relief_mm, 3),
            "slit_mm": SLIT_MM,
            "strain_percent": round(100 * self.strain, 2),
            "strain_limit_percent": round(100 * FLEXURE_STRAIN_LIMIT, 2),
            "flexure": flexure_payload(
                flexure_for(self.deflection_mm, self.reach_mm, self.tongue_thickness_mm)
            ),
        }


def vertical_runs(
    section: Sequence[tuple[float, float]],
) -> list[tuple[float, float, float]]:
    """The stretches of a section that are vertical: ``(z0, z1, inset)``."""

    return [
        (z_a, z_b, inset_a)
        for (inset_a, z_a), (inset_b, z_b) in pairwise(section)
        if abs(inset_a - inset_b) < _EPSILON and z_b > z_a
    ]


def latch_window(profile: StackProfile) -> LatchWindow | None:
    """The longest overlap in height between a vertical run of the foot and one of the lip,
    or ``None`` if none is long enough to put a hook in."""

    best: LatchWindow | None = None

    for foot_z0, foot_z1, foot_inset in vertical_runs(profile.foot):
        for lip_z0, lip_z1, lip_inset in vertical_runs(profile.lip):
            low, high = max(foot_z0, lip_z0), min(foot_z1, lip_z1)

            if high - low >= MINIMUM_RUN_MM - _EPSILON and (
                best is None or high - low > best.run_mm
            ):
                best = LatchWindow(low, high, foot_inset, lip_inset)

    return best


def engagement_for(item_value: float | None, profile: StackProfile) -> float:
    """The engagement an item uses: its own, else the profile's, else the engine's."""

    if item_value is not None:
        return item_value

    if profile.latch_engagement_mm is not None:
        return profile.latch_engagement_mm

    return DEFAULT_ENGAGEMENT_MM


def plan_latch(
    profile: StackProfile,
    engagement_mm: float,
    least_wall_mm: float,
    clearance_mm: float,
) -> tuple[LatchPlan | None, list[str]]:
    """The latch's sizes, or why the profile and the printer cannot carry it. ``clearance_mm``
    is the printer's sliding clearance, which the keeper has past the hook's tip."""

    least_wall = least_wall_mm if least_wall_mm > 0 else DEFAULT_LEAST_WALL_MM
    window = latch_window(profile)

    if window is None:
        return None, [
            (
                f"a latch needs a vertical run of {MINIMUM_RUN_MM:g} mm where the foot's "
                "face and the lip's face overlap in height, and the profile's sections "
                "have none"
            )
        ]

    errors: list[str] = []

    if engagement_mm < MINIMUM_ENGAGEMENT_MM - _EPSILON:
        errors.append(
            f"a latch's engagement is {engagement_mm:g} mm, under the least the engine "
            f"builds, {MINIMUM_ENGAGEMENT_MM:g} mm"
        )

    protrusion = window.gap_mm + engagement_mm
    flat = window.run_mm - 2 * protrusion

    if flat < HOOK_FLAT_MM - _EPSILON:
        most = (window.run_mm - HOOK_FLAT_MM) / 2 - window.gap_mm
        errors.append(
            f"a hook that stands {protrusion:.2f} mm out of the foot has 45 degree ramps "
            f"that take {2 * protrusion:.2f} mm of the {window.run_mm:.2f} mm vertical run, "
            f"leaving a flat of {flat:.2f} mm under {HOOK_FLAT_MM:g} mm: the most engagement "
            f"this profile's run allows is {most:.2f} mm"
        )

    backing = window.lip_inset - (engagement_mm + clearance_mm)

    if backing < least_wall - _EPSILON:
        most = window.lip_inset - least_wall - clearance_mm
        errors.append(
            f"a keeper {engagement_mm + clearance_mm:.2f} mm deep would leave "
            f"{backing:.2f} mm of the {window.lip_inset:g} mm lip behind it, under the "
            f"printer's {least_wall:g} mm minimum wall: the most engagement is {most:.2f} mm"
        )

    # The tongue bends far enough to pass the lip below, by the engagement, and far enough
    # to pass a baseplate's pocket wall, which stands only the nest clearance from the foot
    # where the lip stands the full gap from it: the hook must clear whichever is nearer.
    deflection = max(engagement_mm, protrusion - profile.min_nest_clearance_mm)
    reach = math.sqrt(3 * least_wall * deflection / (2 * FLEXURE_STRAIN_LIMIT))
    reach = math.ceil(reach * 2) / 2
    strain = flexure_for(deflection, reach, least_wall).strain
    length = reach + HOOK_WIDTH_MM / 2
    straight = profile.cell_top_mm - 2 * profile.corner_radius_mm
    room = straight - 2 * END_MARGIN_MM

    if length + SLIT_MM > room:
        errors.append(
            f"a tongue {length:.1f} mm long, with its slit, needs {length + SLIT_MM:.1f} mm "
            f"of straight foot to bend {deflection:g} mm within the strain limit, and a "
            f"cell's side has {room:.1f} mm"
        )

    if errors:
        return None, errors

    return (
        LatchPlan(
            window=window,
            engagement_mm=engagement_mm,
            protrusion_mm=protrusion,
            keeper_clearance_mm=clearance_mm,
            tongue_thickness_mm=least_wall,
            deflection_mm=deflection,
            reach_mm=reach,
            length_mm=length,
            strain=strain,
            relief_mm=deflection + RELIEF_MARGIN_MM,
            foot_height_mm=profile.foot_height_mm,
            cell_top_mm=profile.cell_top_mm,
            corner_radius_mm=profile.corner_radius_mm,
            lip_face_inset_mm=window.lip_inset,
            foot_face_inset_mm=window.foot_inset,
            nest_clearance_mm=profile.min_nest_clearance_mm,
        ),
        [],
    )


def cells_on_side(
    side: str, centres: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    """The cells whose outer face is on ``side`` of the item."""

    xs = [x for x, _ in centres]
    ys = [y for _, y in centres]
    edge = {
        "back": ("y", max(ys)),
        "front": ("y", min(ys)),
        "left": ("x", min(xs)),
        "right": ("x", max(xs)),
    }[side]

    return [
        (x, y) for x, y in centres if abs((y if edge[0] == "y" else x) - edge[1]) < 1e-6
    ]


def _box(
    u0: float, u1: float, v0: float, v1: float, z0: float, z1: float
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(u1 - u0, v1 - v0, z1 - z0, centered=(False, False, False))
        .translate((u0, v0, z0))
    )


def _extruded(
    points: Sequence[tuple[float, float]], width: float, u_centre: float
) -> cq.Workplane:
    """A polygon of ``(v, z)`` points extruded ``width`` along ``u`` about ``u_centre``."""

    return (
        cq.Workplane("YZ")
        .polyline(list(points))
        .close()
        .extrude(width / 2, both=True)
        .translate((u_centre, 0.0, 0.0))
    )


def _u_start(plan: LatchPlan) -> float:
    """Where a tongue's footprint begins along the side, so that it is centred on the cell."""

    return -plan.footprint_mm / 2


def hook_centre_u(plan: LatchPlan) -> float:
    """Where the hook's middle is along the side: at the tongue's free end."""

    return _u_start(plan) + SLIT_MM + HOOK_WIDTH_MM / 2


def _foot_face_v(plan: LatchPlan) -> float:
    return plan.cell_top_mm / 2 - plan.foot_face_inset_mm


def _place(
    shape: cq.Workplane, side: str, centre: tuple[float, float], z: float = 0.0
) -> cq.Workplane:
    return shape.rotate((0, 0, 0), (0, 0, 1), _ANGLES[side]).translate(
        (centre[0], centre[1], z)
    )


def tongue_cutters(plan: LatchPlan) -> cq.Workplane:
    """What is cut from a foot to free a tongue, in its cell's frame: the relief pocket behind
    the skin, the slit at the free end and the slit along the top of the skin."""

    face = _foot_face_v(plan)
    inner = face - plan.tongue_thickness_mm
    u0 = _u_start(plan)
    free = u0 + SLIT_MM
    root = free + plan.length_mm
    top = plan.foot_height_mm
    outside = plan.cell_top_mm / 2 + 1.0
    relief = _box(free, root, inner - plan.relief_mm, inner, -1.0, top)
    end_slit = _box(u0, free, inner - plan.relief_mm, outside, -1.0, top)
    top_slit = _box(u0, root, inner, outside, top - SLIT_MM, top)

    return relief.union(end_slit).union(top_slit)


def _hook_solid(plan: LatchPlan) -> cq.Workplane:
    """The hook, in its cell's frame: a trapezoid on the foot's face, buried 0.3 mm in the
    skin so it fuses with it."""

    face = _foot_face_v(plan)
    low, high = plan.window.z_low, plan.window.z_high
    p = plan.protrusion_mm
    section = [
        (face - 0.3, low),
        (face, low),
        (face + p, low + p),
        (face + p, high - p),
        (face, high),
        (face - 0.3, high),
    ]

    return _extruded(section, HOOK_WIDTH_MM, hook_centre_u(plan))


def keeper_cutter(plan: LatchPlan, face_v: float) -> cq.Workplane:
    """A keeper, in its cell's frame: the hook's section grown by the printer's sliding
    clearance, cut from the surface at ``face_v`` outward only, so it opens onto that face."""

    foot_face = _foot_face_v(plan)
    low, high = plan.window.z_low, plan.window.z_high
    p = plan.protrusion_mm
    s = plan.keeper_clearance_mm
    spread = s * math.sqrt(2)
    start = face_v - 0.01
    reach = foot_face + p + s
    section = [
        (start, low + (start - foot_face) - spread),
        (reach, low + p + s - spread),
        (reach, high - p - s + spread),
        (start, high - (start - foot_face) + spread),
    ]

    return _extruded(section, HOOK_WIDTH_MM + 2 * s, hook_centre_u(plan))


def add_latch_feet(
    model: cq.Workplane,
    plan: LatchPlan,
    centres: Sequence[tuple[float, float]],
    sides: Sequence[str],
) -> cq.Workplane:
    """Free a tongue on each named side of each cell on it, and give it a hook."""

    cutters = tongue_cutters(plan)
    hook = _hook_solid(plan)

    for side in sides:
        for centre in cells_on_side(side, centres):
            model = model.cut(_place(cutters, side, centre))

    for side in sides:
        for centre in cells_on_side(side, centres):
            model = model.union(_place(hook, side, centre))

    return model


def cut_lip_keepers(
    model: cq.Workplane,
    plan: LatchPlan,
    centres: Sequence[tuple[float, float]],
    sides: Sequence[str],
    wall_top: float,
) -> cq.Workplane:
    """Cut a keeper into the lip's inside face at each tongue's place, ``wall_top`` up."""

    face_v = plan.cell_top_mm / 2 - plan.lip_face_inset_mm
    cutter = keeper_cutter(plan, face_v)

    for side in sides:
        for centre in cells_on_side(side, centres):
            model = model.cut(_place(cutter, side, centre, wall_top))

    return model


def cut_plate_keepers(
    model: cq.Workplane,
    plan: LatchPlan,
    centres: Sequence[tuple[float, float]],
    sides: Sequence[str],
    floor_mm: float,
) -> cq.Workplane:
    """Cut a keeper into each pocket wall of a baseplate, on the named side of every cell.
    A foot's bottom stands at ``floor_mm``, and the pocket's wall is the foot's face and the
    nest clearance."""

    face_v = plan.cell_top_mm / 2 - plan.foot_face_inset_mm + plan.nest_clearance_mm
    cutter = keeper_cutter(plan, face_v)

    for side in sides:
        for centre in centres:
            model = model.cut(_place(cutter, side, centre, floor_mm))

    return model


def hook_solids(
    plan: LatchPlan, centres: Sequence[tuple[float, float]], side: str
) -> cq.Workplane | None:
    """The hooks on one side of an item, in the item's frame."""

    hook = _hook_solid(plan)
    placed = [_place(hook, side, centre) for centre in cells_on_side(side, centres)]

    if not placed:
        return None

    joined = placed[0]

    for other in placed[1:]:
        joined = joined.union(other)

    return joined


def inward(side: str) -> tuple[float, float]:
    """The direction a side's tongue deflects: toward the middle of the item."""

    return _INWARD[side]


def _to_frame(
    local: dict[str, tuple[float, float, float]],
    centre: tuple[float, float],
    side: str,
    z0: float,
) -> dict[str, tuple[float, float, float]]:
    angle = math.radians(_ANGLES[side])
    cos, sin = math.cos(angle), math.sin(angle)

    return {
        name: (
            centre[0] + u * cos - v * sin,
            centre[1] + u * sin + v * cos,
            z0 + z,
        )
        for name, (u, v, z) in local.items()
    }


def foot_points(
    plan: LatchPlan, centre: tuple[float, float], side: str
) -> dict[str, tuple[float, float, float]]:
    """Points to test an item's solid at, in its frame: in a tongue's skin, and in the relief
    behind it. The skin is solid and the relief is void."""

    face = _foot_face_v(plan)
    inner = face - plan.tongue_thickness_mm
    u = hook_centre_u(plan)
    local = {
        "skin": (u, face - plan.tongue_thickness_mm / 2, 0.5),
        "relief": (u, inner - plan.relief_mm / 2, 0.5),
    }

    return _to_frame(local, centre, side, 0.0)


def keeper_points(
    plan: LatchPlan, centre: tuple[float, float], side: str, z0: float
) -> dict[str, tuple[float, float, float]]:
    """Points to test the item below at, with its lip's base at ``z0``: in a keeper's mouth,
    which is void, and in the lip behind it, which is solid."""

    u = hook_centre_u(plan)
    z = (plan.window.z_low + plan.window.z_high) / 2
    face = plan.cell_top_mm / 2 - plan.lip_face_inset_mm
    behind = (face + plan.keeper_depth_mm + plan.cell_top_mm / 2) / 2
    local = {
        "keeper_mouth": (u, face + plan.engagement_mm / 2, z),
        "keeper_backing": (u, behind, z),
    }

    return _to_frame(local, centre, side, z0)


def clash_errors(
    plan: LatchPlan,
    sides: Sequence[str],
    holding_points: Sequence[tuple[float, float]],
    pocket_radius_mm: float,
    least_wall_mm: float,
) -> list[str]:
    """A tongue's relief and slits must keep a minimum wall from a magnet or bolt pocket at a
    holding point."""

    if not holding_points or pocket_radius_mm <= 0:
        return []

    face = _foot_face_v(plan)
    u0, u1 = _u_start(plan), _u_start(plan) + plan.footprint_mm
    v0, v1 = face - plan.tongue_thickness_mm - plan.relief_mm, plan.cell_top_mm / 2
    errors = []

    for side in sides:
        angle = math.radians(_ANGLES[side])
        cos, sin = math.cos(angle), math.sin(angle)

        for x, y in holding_points:
            # The point in the side's frame: u along the side, v out from the centre.
            u = x * cos + y * sin
            v = -x * sin + y * cos
            gap = math.hypot(max(u0 - u, 0.0, u - u1), max(v0 - v, 0.0, v - v1))

            if gap < pocket_radius_mm + max(least_wall_mm, DEFAULT_LEAST_WALL_MM):
                errors.append(
                    f"the {side} tongue comes within {max(gap - pocket_radius_mm, 0):.1f} mm "
                    f"of the pocket at ({x:g}, {y:g}), under the printer's minimum wall"
                )

    return errors
