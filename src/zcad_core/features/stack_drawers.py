"""Caps, drawer frames and drawers: stackable items that close or slide.

- A **cap** is a flat lid on the profile's foot. It sits in the lip of a bin or a frame of
  the same cells, as a bin does, and nothing stacks on it.
- A **frame** is a bin with its front wall taken out, a roof, and a pair of ledges for each
  of ``drawers`` slots up the inside of its side walls. It has the foot and the lip, so it
  stands on a baseplate and takes a bin or a cap on top.
- A **drawer** is a tray that slides along a slot's ledges, its front flush with the
  frame's front. It rests on the ledges and is held by nothing: it comes out when pulled.

The ledge, the roof, the drawer's clearances and the finger pull are the engine's own
design choices, not figures from a profile's source.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.stack_profile import StackProfile
from zcad_core.features.stack_solids import (
    MINIMUM_RADIUS_MM,
    bin_solid,
    cell_centres,
    foot_solid,
    prism,
)

# How far a ledge stands in from a side wall, and how thick it is.
LEDGE_MM = 3.0
LEDGE_THICKNESS_MM = 1.6
# The roof over the top slot.
ROOF_MM = 1.6
# Air between a drawer's top and the ledge or roof above it.
TOP_CLEARANCE_MM = 0.6
# The least a drawer may hold, and the least width a drawer may be.
MINIMUM_DRAWER_DEPTH_MM = 3.0
MINIMUM_DRAWER_WIDTH_MM = 15.0
MAXIMUM_DRAWERS = 8
# A drawer's finger pull is a half-round notch in its front wall.
PULL_RADIUS_MM = 6.0
DEFAULT_CLEARANCE_MM = 0.2


@dataclass(frozen=True)
class FramePlan:
    """The sizes a frame and its drawers share."""

    outer_width: float
    outer_depth: float
    inner_width: float
    inner_depth: float
    inner_radius: float
    wall_top: float
    floor_z: float
    roof_z: float
    slots: int
    pitch: float
    drawer_width: float
    drawer_length: float
    drawer_height: float
    drawer_wall: float
    drawer_floor: float
    clearance: float

    @property
    def drawer_interior_depth(self) -> float:
        return self.drawer_height - self.drawer_floor

    @property
    def pull_radius(self) -> float:
        return min(PULL_RADIUS_MM, self.drawer_interior_depth * 0.8)


def plan_frame(
    profile: StackProfile,
    cells: tuple[int, int],
    units: int,
    slots: int,
    wall_mm: float,
    floor_mm: float,
    drawer_wall_mm: float,
    drawer_floor_mm: float,
    clearance_mm: float,
) -> FramePlan:
    """The sizes of a frame and its drawers, refused with the figures if they do not
    leave a drawer room to hold anything."""

    outer_width = cells[0] * profile.pitch_mm - profile.gap_mm
    outer_depth = cells[1] * profile.pitch_mm - profile.gap_mm
    inner_width = outer_width - 2 * wall_mm
    inner_depth = outer_depth - 2 * wall_mm
    wall_top = units * profile.height_unit_mm
    floor_z = profile.foot_height_mm + floor_mm
    roof_z = wall_top - ROOF_MM
    pitch = (roof_z - floor_z) / slots
    drawer_width = inner_width - 2 * clearance_mm
    height = pitch - LEDGE_THICKNESS_MM - TOP_CLEARANCE_MM

    if drawer_width - 2 * LEDGE_MM < MINIMUM_DRAWER_WIDTH_MM:
        raise ValueError(
            f"the frame is {inner_width:.1f} mm wide inside: with ledges {LEDGE_MM:g} mm "
            f"deep each side a drawer would be {drawer_width - 2 * LEDGE_MM:.1f} mm, "
            f"under {MINIMUM_DRAWER_WIDTH_MM:g}"
        )

    if height - drawer_floor_mm < MINIMUM_DRAWER_DEPTH_MM:
        raise ValueError(
            f"{slots} drawers in {units} units leave each {height - drawer_floor_mm:.1f} mm "
            f"deep inside, under {MINIMUM_DRAWER_DEPTH_MM:g} mm: use fewer drawers or a "
            "taller frame"
        )

    return FramePlan(
        outer_width=outer_width,
        outer_depth=outer_depth,
        inner_width=inner_width,
        inner_depth=inner_depth,
        inner_radius=max(profile.corner_radius_mm - wall_mm, MINIMUM_RADIUS_MM),
        wall_top=wall_top,
        floor_z=floor_z,
        roof_z=roof_z,
        slots=slots,
        pitch=pitch,
        drawer_width=drawer_width,
        drawer_length=inner_depth + wall_mm - clearance_mm,
        drawer_height=height,
        drawer_wall=drawer_wall_mm,
        drawer_floor=drawer_floor_mm,
        clearance=clearance_mm,
    )


def cap_solid(
    profile: StackProfile, cells: tuple[int, int], thickness_mm: float
) -> tuple[cq.Workplane, float]:
    """A flat cap on the foot, and its overall height."""

    width = cells[0] * profile.pitch_mm - profile.gap_mm
    depth = cells[1] * profile.pitch_mm - profile.gap_mm
    top = profile.foot_height_mm
    model = prism(width, depth, profile.corner_radius_mm, top, top + thickness_mm)

    for centre in cell_centres(cells, profile.pitch_mm):
        model = model.union(foot_solid(profile, centre))

    return model, top + thickness_mm


def frame_solid(
    profile: StackProfile,
    cells: tuple[int, int],
    units: int,
    wall_mm: float,
    floor_mm: float,
    plan: FramePlan,
) -> tuple[cq.Workplane, float]:
    """A frame, and the height of its walls' tops."""

    model, top = bin_solid(profile, cells, units, wall_mm, floor_mm)
    front = -plan.outer_depth / 2
    opening = (
        cq.Workplane("XY")
        .box(
            plan.inner_width,
            plan.inner_radius + wall_mm + 1.1,
            plan.roof_z - plan.floor_z,
            centered=(True, False, False),
        )
        .translate((0.0, front - 1.0, plan.floor_z))
    )
    model = model.cut(opening)
    roof = (
        cq.Workplane("XY")
        .box(
            plan.inner_width + 0.2,
            plan.inner_depth + 0.2,
            ROOF_MM,
            centered=(True, True, False),
        )
        .translate((0.0, 0.0, plan.roof_z))
    )
    model = model.union(roof)
    outline = prism(
        plan.outer_width,
        plan.outer_depth,
        profile.corner_radius_mm,
        plan.floor_z,
        plan.roof_z,
    )

    for slot in range(plan.slots):
        for side in (-1, 1):
            ledge = (
                cq.Workplane("XY")
                .box(
                    LEDGE_MM + wall_mm,
                    plan.outer_depth,
                    LEDGE_THICKNESS_MM,
                    centered=(True, False, False),
                )
                .translate(
                    (
                        side * (plan.inner_width / 2 - LEDGE_MM / 2 + wall_mm / 2),
                        front,
                        plan.floor_z + slot * plan.pitch,
                    )
                )
            )
            model = model.union(ledge.intersect(outline))

    return model, top


def drawer_solid(plan: FramePlan, pull: bool) -> cq.Workplane:
    """A drawer for slot 0, in the frame's own coordinates: on the ledges, its front
    flush with the frame's front."""

    wall, floor = plan.drawer_wall, plan.drawer_floor
    radius = max(plan.inner_radius - plan.clearance, MINIMUM_RADIUS_MM)
    z0 = plan.floor_z + LEDGE_THICKNESS_MM
    front = -plan.outer_depth / 2
    centre_y = front + plan.drawer_length / 2
    outer = prism(
        plan.drawer_width, plan.drawer_length, radius, z0, z0 + plan.drawer_height
    )
    inner = prism(
        plan.drawer_width - 2 * wall,
        plan.drawer_length - 2 * wall,
        max(radius - wall, MINIMUM_RADIUS_MM),
        z0 + floor,
        z0 + plan.drawer_height + 1.0,
    )
    model = outer.cut(inner).translate((0.0, centre_y, 0.0))

    if pull:
        radius_p = plan.pull_radius
        notch = (
            cq.Workplane("XZ")
            .center(0.0, z0 + plan.drawer_height)
            .circle(radius_p)
            .extrude(-(wall + 2.0))
            .translate((0.0, front - 1.0, 0.0))
        )
        model = model.cut(notch)

    return model
