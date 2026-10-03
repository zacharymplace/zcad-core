"""A drawer that clicks shut, and can stop: a bump on a tongue in each side wall, a dimple in the frame's.

A drawer slides along the ledges of a frame and is held by nothing. A **detent** gives it a
closed position: near the back of each side wall of the drawer a **tongue** is cut free of the
wall, with a **bump** on its outer face, and the frame's side wall has a **dimple** where the
bump sits when the drawer is shut. Pushed shut, the drawer clicks into the dimple; pulled, it
clicks out. It does not stop the drawer leaving the frame: a pulled drawer comes out.

A **stop** keeps the drawer in the frame when it is pulled out. The bump's front face is
vertical, and the frame has a **window** through each side wall where the bump sits when the
drawer is pulled out the stop's travel; the window's front edge is a vertical wall, so the bump
catches on it and the drawer stops. Squeezing both bumps in through the windows, with a pin or a
fingernail, lets the drawer out. Pushed in, the bump's rear face is still a 45 degree ramp, so
the drawer goes back past the window and into its dimple, which has a ramped front wall so the
vertical face still clicks out of it.

The tongue is a strip of the drawer's side wall along its length, cut free by a slit under it and
a slit at its free end, fixed at the back, with its top the rim of the drawer. It bends outward
and inward in the wall's thickness, as the slide lid's detent does. Its strain is the cantilever's,
checked against the provisional limit, with the bump pushed in by the engagement.

The bump and the dimple are laid out from the frame's own sizes, from the back of the drawer and
down from its rim, so a frame and the drawers that go in it agree on where the dimple is whatever
the drawer's own wall and floor. The engine states no holding force: it clicks, and a pull lets
go. Every size here is the engine's own design choice, provisional until a trial.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.mounts import (
    FLEXURE_STRAIN_LIMIT,
    flexure_for,
    flexure_payload,
)
from zcad_core.features.stack_drawers import LEDGE_THICKNESS_MM, FramePlan
from zcad_core.features.stack_latch import (
    DEFAULT_ENGAGEMENT_MM,
    DEFAULT_LEAST_WALL_MM,
    ENGAGEMENT_RANGE_MM,
    HOOK_FLAT_MM,
    MINIMUM_ENGAGEMENT_MM,
    SLIT_MM,
)

__all__ = [
    "DEFAULT_ENGAGEMENT_MM",
    "ENGAGEMENT_RANGE_MM",
    "DetentPlan",
    "add_bumps",
    "bump_solid",
    "cut_dimples",
    "cut_tongues",
    "cut_windows",
    "detent_points",
    "plan_detent",
    "stop_points",
]

# A bump is this long along the wall's height, and its tongue reaches this far down from the
# rim: a half millimetre of tongue above and below the bump.
BUMP_Z_MM = 3.0
TONGUE_Z_MM = 4.5
# The bump's centre is this far from the back of the drawer, and the tongue's root keeps this
# much clear of the drawer's back wall.
BUMP_FROM_BACK_MM = 14.0
BACK_MARGIN_MM = 2.0
# The bump's centre sits this far below the drawer's rim.
BUMP_BELOW_RIM_MM = 2.0
# A stop's window is no nearer the frame's front edge than this, and is as long as the bump's
# base and this much more, so a pin reaches the bump. Its height is the bump's and this much
# more each way.
STOP_FRONT_MARGIN_MM = 3.0
WINDOW_EXTRA_LENGTH_MM = 4.0
WINDOW_EXTRA_HEIGHT_MM = 0.6
# The share of a drawer's length a stop lets it out: the least that is a stop, the most that
# leaves the drawer held.
STOP_TRAVEL_SHARE = (0.2, 2 / 3)
_EPSILON = 1e-6


@dataclass(frozen=True)
class DetentPlan:
    """The sizes of a drawer's detent, in the frame's own coordinates."""

    engagement_mm: float
    protrusion_mm: float
    clearance_mm: float
    base_mm: float
    tongue_thickness_mm: float
    reach_mm: float
    length_mm: float
    strain: float
    # Where the bump is, and the faces it meets, all in the frame's coordinates.
    drawer_half_mm: float
    frame_half_mm: float
    y_bump_mm: float
    z_bump_mm: float
    y_free_mm: float
    y_root_mm: float
    z_slit_mm: float
    z_rim_mm: float
    drawer_wall_mm: float
    slots: int
    pitch_mm: float
    # A stop: where the window's front wall is, how far the drawer comes out to it, and the
    # window's size.
    stop: bool = False
    frame_wall_mm: float = 0.0
    drawer_length_mm: float = 0.0
    y_window_mm: float = 0.0
    stop_travel_mm: float = 0.0
    window_length_mm: float = 0.0
    window_height_mm: float = 0.0

    @property
    def dimple_depth_mm(self) -> float:
        """How deep a dimple is cut into the frame's wall, past its face."""

        return self.engagement_mm + self.clearance_mm

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "engagement_mm": self.engagement_mm,
            "protrusion_mm": round(self.protrusion_mm, 3),
            "dimple_depth_mm": round(self.dimple_depth_mm, 3),
            "bump_base_mm": round(self.base_mm, 3),
            "bump_height_mm": BUMP_Z_MM,
            "tongue_thickness_mm": self.tongue_thickness_mm,
            "tongue_length_mm": round(self.length_mm, 3),
            "tongue_reach_mm": round(self.reach_mm, 3),
            "strain_percent": round(100 * self.strain, 2),
            "strain_limit_percent": round(100 * FLEXURE_STRAIN_LIMIT, 2),
            "flexure": flexure_payload(
                flexure_for(self.engagement_mm, self.reach_mm, self.tongue_thickness_mm)
            ),
        }

        if self.stop:
            payload["stop"] = {
                "travel_mm": round(self.stop_travel_mm, 3),
                "travel_share": round(self.stop_travel_mm / self.drawer_length_mm, 3),
                "window_length_mm": round(self.window_length_mm, 3),
                "window_height_mm": round(self.window_height_mm, 3),
                "released_by": "squeezing both bumps in through the windows",
            }

        return payload


def plan_detent(
    plan: FramePlan,
    frame_wall_mm: float,
    engagement_mm: float,
    least_wall_mm: float,
    clearance_mm: float,
    stop: bool = False,
) -> tuple[DetentPlan | None, list[str]]:
    """The detent's sizes, or why the frame and the drawer cannot carry it. ``plan`` is the
    frame's plan with the drawer's own wall and floor, ``clearance_mm`` the printer's sliding
    clearance, which the dimple has past the bump's tip."""

    least_wall = least_wall_mm if least_wall_mm > 0 else DEFAULT_LEAST_WALL_MM
    errors: list[str] = []

    if engagement_mm < MINIMUM_ENGAGEMENT_MM - _EPSILON:
        errors.append(
            f"a detent's engagement is {engagement_mm:g} mm, under the least the engine "
            f"builds, {MINIMUM_ENGAGEMENT_MM:g} mm"
        )

    dimple = engagement_mm + clearance_mm
    left = frame_wall_mm - dimple

    if left < least_wall - _EPSILON:
        errors.append(
            f"a dimple {dimple:.2f} mm deep would leave {left:.2f} mm of the frame's "
            f"{frame_wall_mm:g} mm wall, under the printer's {least_wall:g} mm minimum: the "
            f"frame's wall_mm must be at least {least_wall + dimple:.2f} mm"
        )

    needed = TONGUE_Z_MM + SLIT_MM

    if plan.drawer_interior_depth < needed - _EPSILON:
        errors.append(
            f"a drawer's tongue needs {needed:g} mm of side wall above its floor, and this "
            f"drawer is {plan.drawer_interior_depth:.1f} mm deep inside"
        )

    protrusion = clearance_mm + engagement_mm
    thickness = plan.drawer_wall
    reach = math.sqrt(3 * thickness * engagement_mm / (2 * FLEXURE_STRAIN_LIMIT))
    reach = math.ceil(reach * 2) / 2
    strain = flexure_for(engagement_mm, reach, thickness).strain
    base = 2 * protrusion + HOOK_FLAT_MM
    length = reach + base / 2 + 0.3
    back = -plan.outer_depth / 2 + plan.drawer_length
    y_bump = back - BUMP_FROM_BACK_MM
    y_free = y_bump - base / 2 - 0.3
    y_root = y_free + length

    if back - y_root < thickness + BACK_MARGIN_MM - _EPSILON:
        errors.append(
            f"a tongue of {length:.1f} mm, to bend {engagement_mm:g} mm within the strain "
            f"limit in a {thickness:g} mm wall, would end {back - y_root:.1f} mm from the "
            f"back of the drawer, under the {thickness + BACK_MARGIN_MM:g} mm its back wall "
            "and margin need"
        )

    front = -plan.outer_depth / 2
    y_window = front + STOP_FRONT_MARGIN_MM
    travel = (y_bump - base / 2) - clearance_mm - y_window
    window_height = BUMP_Z_MM + 2 * WINDOW_EXTRA_HEIGHT_MM

    if stop:
        share = travel / plan.drawer_length
        low, high = STOP_TRAVEL_SHARE

        if not low <= share <= high:
            errors.append(
                f"a stop would let the drawer out {travel:.1f} mm, {share:.0%} of its "
                f"length, outside {low:.0%} to {high:.0%}"
            )

        web = plan.pitch - window_height

        if plan.slots > 1 and web < least_wall - _EPSILON:
            errors.append(
                f"windows {window_height:g} mm tall in slots {plan.pitch:.1f} mm apart leave "
                f"{web:.1f} mm of wall between them, under the printer's {least_wall:g} mm "
                "minimum: use fewer drawers or a taller frame"
            )

    if errors:
        return None, errors

    return (
        DetentPlan(
            engagement_mm=engagement_mm,
            protrusion_mm=protrusion,
            clearance_mm=clearance_mm,
            base_mm=base,
            tongue_thickness_mm=thickness,
            reach_mm=reach,
            length_mm=length,
            strain=strain,
            drawer_half_mm=plan.drawer_width / 2,
            frame_half_mm=plan.inner_width / 2,
            y_bump_mm=y_bump,
            z_bump_mm=plan.floor_z
            + LEDGE_THICKNESS_MM
            + plan.drawer_height
            - BUMP_BELOW_RIM_MM,
            y_free_mm=y_free,
            y_root_mm=y_root,
            z_slit_mm=plan.floor_z
            + LEDGE_THICKNESS_MM
            + plan.drawer_height
            - TONGUE_Z_MM
            - SLIT_MM,
            z_rim_mm=plan.floor_z + LEDGE_THICKNESS_MM + plan.drawer_height,
            drawer_wall_mm=thickness,
            slots=plan.slots,
            pitch_mm=plan.pitch,
            stop=stop,
            frame_wall_mm=frame_wall_mm,
            drawer_length_mm=plan.drawer_length,
            y_window_mm=y_window,
            stop_travel_mm=travel if stop else 0.0,
            window_length_mm=base + WINDOW_EXTRA_LENGTH_MM if stop else 0.0,
            window_height_mm=window_height if stop else 0.0,
        ),
        [],
    )


def _outline(
    points: Sequence[tuple[float, float]], side: int, z0: float, height: float
) -> cq.Workplane:
    """A polygon of ``(x, y)`` points on the +X side, mirrored for ``side == -1``, standing
    ``height`` up from ``z0``."""

    placed = [(side * x, y) for x, y in points]

    return (
        cq.Workplane("XY").workplane(offset=z0).polyline(placed).close().extrude(height)
    )


def bump_solid(plan: DetentPlan, side: int) -> cq.Workplane:
    """A bump on the drawer's outer face on ``side`` (+1 or -1), buried 0.3 mm in the
    tongue so it fuses with it. It has a 45 degree ramp each way along the wall, or, for a
    stop, a vertical face on the front, the side the drawer is pulled toward."""

    face = plan.drawer_half_mm
    p = plan.protrusion_mm
    half = plan.base_mm / 2
    y = plan.y_bump_mm
    front = (
        [(face - 0.3, y - half), (face + p, y - half)]
        if plan.stop
        else [
            (face - 0.3, y - half),
            (face, y - half),
            (face + p, y - half + p),
        ]
    )
    section = [
        *front,
        (face + p, y + half - p),
        (face, y + half),
        (face - 0.3, y + half),
    ]

    return _outline(section, side, plan.z_bump_mm - BUMP_Z_MM / 2, BUMP_Z_MM)


def _dimple_solid(plan: DetentPlan, side: int, slot: int) -> cq.Workplane:
    """A dimple in the frame's side wall: the bump's section grown by the clearance, cut
    from the wall's face outward only."""

    face = plan.drawer_half_mm
    s = plan.clearance_mm
    p = plan.protrusion_mm
    half = plan.base_mm / 2
    y = plan.y_bump_mm
    spread = s * math.sqrt(2)
    start = plan.frame_half_mm - 0.01
    reach = face + p + s
    rear = [
        (reach, y + half - p - s + spread),
        (start, y + half - (start - face) + spread),
    ]

    if plan.stop:
        # The bump's front is vertical, so the dimple's front wall is a ramp that starts the
        # clearance ahead of the face and climbs at 45 degrees to the wall's face: the bump's
        # corner rides up it and out.
        front_face = y - half
        tip = front_face - s
        front = [(start, tip - (reach - start)), (reach, tip)]
    else:
        front = [
            (start, y - half + (start - face) - spread),
            (reach, y - half + p + s - spread),
        ]

    section = [*front, *rear]

    return _outline(
        section,
        side,
        plan.z_bump_mm - BUMP_Z_MM / 2 - s + slot * plan.pitch_mm,
        BUMP_Z_MM + 2 * s,
    )


def _slits(plan: DetentPlan, side: int) -> cq.Workplane:
    """The two slits that free a tongue: along its underside and across its free end."""

    wall = plan.drawer_wall_mm
    x0 = plan.drawer_half_mm - wall - 0.5
    x1 = plan.drawer_half_mm + 0.5
    under = _outline(
        [
            (x0, plan.y_free_mm - SLIT_MM),
            (x1, plan.y_free_mm - SLIT_MM),
            (x1, plan.y_root_mm),
            (x0, plan.y_root_mm),
        ],
        side,
        plan.z_slit_mm,
        SLIT_MM,
    )
    end = _outline(
        [
            (x0, plan.y_free_mm - SLIT_MM),
            (x1, plan.y_free_mm - SLIT_MM),
            (x1, plan.y_free_mm),
            (x0, plan.y_free_mm),
        ],
        side,
        plan.z_slit_mm,
        plan.z_rim_mm + 1.0 - plan.z_slit_mm,
    )

    return under.union(end)


def cut_tongues(drawer: cq.Workplane, plan: DetentPlan) -> cq.Workplane:
    """Free a tongue in each side wall of a drawer in slot 0."""

    for side in (1, -1):
        drawer = drawer.cut(_slits(plan, side))

    return drawer


def add_bumps(drawer: cq.Workplane, plan: DetentPlan) -> cq.Workplane:
    """A bump on each tongue."""

    for side in (1, -1):
        drawer = drawer.union(bump_solid(plan, side))

    return drawer


def cut_dimples(frame: cq.Workplane, plan: DetentPlan) -> cq.Workplane:
    """A dimple in each side wall of the frame at every slot."""

    for slot in range(plan.slots):
        for side in (1, -1):
            frame = frame.cut(_dimple_solid(plan, side, slot))

    return frame


def cut_windows(frame: cq.Workplane, plan: DetentPlan) -> cq.Workplane:
    """A window through each side wall of the frame at every slot, where the bump sits when
    the drawer is pulled out the stop's travel. Its front edge is a vertical wall."""

    near = plan.frame_half_mm - 0.01
    far = plan.frame_half_mm + plan.frame_wall_mm + 0.5
    front = plan.y_window_mm
    back = front + plan.window_length_mm

    for slot in range(plan.slots):
        for side in (1, -1):
            frame = frame.cut(
                _outline(
                    [(near, front), (far, front), (far, back), (near, back)],
                    side,
                    plan.z_bump_mm - plan.window_height_mm / 2 + slot * plan.pitch_mm,
                    plan.window_height_mm,
                )
            )

    return frame


def stop_points(
    plan: DetentPlan, side: int, slot: int = 0
) -> dict[str, tuple[float, float, float]]:
    """Points to test the frame at: in a window (void) and in the wall just ahead of its
    front edge (solid)."""

    wall_mid = side * (plan.frame_half_mm + plan.frame_wall_mm / 2)
    z = plan.z_bump_mm + slot * plan.pitch_mm

    return {
        "window": (wall_mid, plan.y_window_mm + plan.window_length_mm / 2, z),
        "front_wall": (wall_mid, plan.y_window_mm - 0.5, z),
    }


def detent_points(
    plan: DetentPlan, side: int, slot: int = 0
) -> dict[str, tuple[float, float, float]]:
    """Points to test the solids at: in a tongue's wall (solid), in the slit under it and at
    its end (void), in a dimple's mouth (void) and in the frame's wall behind it (solid)."""

    wall_mid = side * (plan.drawer_half_mm - plan.drawer_wall_mm / 2)
    z = plan.z_bump_mm + slot * plan.pitch_mm
    frame = plan.frame_half_mm

    return {
        "tongue": (wall_mid, plan.y_bump_mm, plan.z_bump_mm),
        "under_slit": (wall_mid, plan.y_bump_mm, plan.z_slit_mm + SLIT_MM / 2),
        "end_slit": (wall_mid, plan.y_free_mm - SLIT_MM / 2, plan.z_bump_mm),
        "dimple_mouth": (
            side * (frame + plan.engagement_mm / 2),
            plan.y_bump_mm,
            z,
        ),
        "dimple_backing": (
            side * (frame + plan.dimple_depth_mm + 0.3),
            plan.y_bump_mm,
            z,
        ),
    }
