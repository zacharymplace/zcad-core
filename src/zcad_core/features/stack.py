"""Stackable items built on a stack profile: bins and baseplates.

``build_stack`` builds each item a stack file lists and checks the one thing a stack is
for by laying real solids against each other:

- a **bin** is one solid, sits in a one-cell-per-cell baseplate pocket with no overlap, and
  stacks on another like it with no overlap; and
- a **baseplate** is one solid.

The engine states no load rating, no stable height and no compatibility with any other
maker's parts: a build says only that a part was built to the profile in the file named by
its hash. See the stackable items design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import cadquery as cq

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.stack_drawers import (
    DEFAULT_CLEARANCE_MM,
    LEDGE_MM,
    LEDGE_THICKNESS_MM,
    ROOF_MM,
    FramePlan,
    cap_solid,
    drawer_solid,
    frame_solid,
    plan_frame,
)
from zcad_core.features.stack_file import (
    DEFAULT_SCOOP_MM,
    DEFAULT_TAB_MM,
    Item,
    StackSpec,
    load_stack_profile,
)
from zcad_core.features.stack_holding import Holding, holding_for, screw_length_mm
from zcad_core.features.stack_latch import (
    LatchPlan,
    add_latch_feet,
    cells_on_side,
    cut_lip_keepers,
    cut_plate_keepers,
    engagement_for,
    foot_points,
    hook_solids,
    inward,
    keeper_points,
    plan_latch,
)
from zcad_core.features.stack_profile import StackProfile
from zcad_core.features.stack_solids import (
    DIVIDER_MM,
    LIP_TIP_MM,
    RIDGE_TOP_MM,
    add_dividers,
    add_label_tab,
    add_scoop,
    baseplate_solid,
    bin_solid,
    cell_centres,
    cut_foot_pockets,
    cut_plate_holding,
    holding_centres,
    solid_count,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume

TOLERANCE_MM3 = 1e-3
NOT_CLAIMED = (
    "The engine states no load rating, no stable height for a stack, and no "
    "compatibility with any other maker's parts: a part is built to the profile in the "
    "file named by its hash, and whether it sits on a bought baseplate is a reading."
)


@dataclass(frozen=True)
class Stack:
    """The built items, what was checked, and what the build refused or noted."""

    spec: StackSpec
    parts: dict[str, cq.Workplane]
    checks: dict[str, bool]
    summary: dict[str, Any]
    profile_id: str
    notes: tuple[str, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def latch_plan_for(
    item: Item, profile: StackProfile, printer: Mapping[str, Any] | None
) -> LatchPlan | None:
    """The item's latch, or ``None`` if it has none; refused if the profile or the printer
    cannot carry it."""

    if not item.latch_sides:
        return None

    least_wall = printer_numbers(printer)[1] if printer is not None else 0.0
    plan, problems = plan_latch(
        profile,
        engagement_for(item.latch_engagement_mm, profile),
        least_wall,
        slide_clearance(printer),
    )

    if plan is None:
        raise ValueError(
            f"{item.name} cannot be built with a latch:\n- " + "\n- ".join(problems)
        )

    return plan


def _latch_summary(item: Item, plan: LatchPlan | None) -> dict[str, Any]:
    """What an item's latch is, as sizes, with no claim of how hard it holds."""

    if plan is None:
        return {}

    return {"latch": {"sides": list(item.latch_sides), **plan.to_dict()}}


def _bin(
    item: Item, profile: StackProfile, plan: LatchPlan | None = None
) -> tuple[cq.Workplane, float, dict[str, Any]]:
    model, top = bin_solid(profile, item.cells, item.units, item.wall_mm, item.floor_mm)
    width = item.cells[0] * profile.pitch_mm - profile.gap_mm - 2 * item.wall_mm
    depth = item.cells[1] * profile.pitch_mm - profile.gap_mm - 2 * item.wall_mm
    floor_z = profile.foot_height_mm + item.floor_mm
    # Dividers and the rest stand inside the walls, up to the walls' tops.
    top_z = top - max(profile.lip[0][0] - item.wall_mm, 0.0)
    model = add_dividers(model, (width, depth), floor_z, top_z, item.dividers)

    if item.label_tab:
        model = add_label_tab(model, (width, depth), top_z, DEFAULT_TAB_MM)

    if item.scoop:
        model = add_scoop(model, (width, depth), floor_z, DEFAULT_SCOOP_MM)

    holding = holding_for(item.holding, item.magnet, item.fastener)

    if holding.holds:
        model = cut_foot_pockets(
            model,
            profile,
            item.cells,
            holding.pocket_diameter_mm,
            holding.pocket_depth_mm,
        )

    if plan is not None:
        centres = cell_centres(item.cells, profile.pitch_mm)
        model = add_latch_feet(model, plan, centres, item.latch_sides)
        model = cut_lip_keepers(model, plan, centres, item.latch_sides, top)

    summary: dict[str, Any] = {
        "kind": "bin",
        "cells": list(item.cells),
        "units": item.units,
        "wall_height_mm": round(top, 3),
        "overall_height_mm": round(workplane_shape(model).BoundingBox().zlen, 3),
        "wall_mm": item.wall_mm,
        "floor_mm": item.floor_mm,
        "dividers": {"x": item.dividers[0], "y": item.dividers[1]},
        "divider_mm": DIVIDER_MM,
        "label_tab": item.label_tab,
        "scoop": item.scoop,
        **_holding_summary(holding, item.floor_mm),
        **_latch_summary(item, plan),
    }

    return model, top, summary


def _baseplate(
    item: Item, profile: StackProfile, plan: LatchPlan | None = None
) -> tuple[cq.Workplane, float, dict[str, Any]]:
    model, floor = baseplate_solid(profile, item.cells, item.floor_mm, item.rim_mm)
    holding = holding_for(item.holding, item.magnet, item.fastener)

    if holding.holds:
        model = cut_plate_holding(
            model,
            profile,
            item.cells,
            holding.kind,
            holding.pocket_diameter_mm
            if holding.kind == "magnet"
            else holding.hole_diameter_mm,
            holding.pocket_depth_mm,
            floor,
        )

    if plan is not None:
        model = cut_plate_keepers(
            model,
            plan,
            cell_centres(item.cells, profile.pitch_mm),
            item.latch_sides,
            floor,
        )

    summary = {
        "kind": "baseplate",
        "cells": list(item.cells),
        "floor_mm": item.floor_mm,
        "rim_mm": item.rim_mm,
        "ridge_top_mm": RIDGE_TOP_MM,
        **_holding_summary(holding, item.floor_mm),
        **_latch_summary(item, plan),
    }

    return model, floor, summary


def _holding_summary(holding: Holding, floor_mm: float) -> dict[str, Any]:
    """What an item holds with and the sizes of it, with no claim of how hard."""

    if not holding.holds:
        return {"holding": "lip"}

    return {
        "holding": holding.kind,
        "holding_part": holding.identifier,
        "pocket_diameter_mm": round(holding.pocket_diameter_mm, 3),
        "pocket_depth_mm": round(holding.pocket_depth_mm, 3),
        "screw_length_at_least_mm": screw_length_mm(holding, floor_mm),
    }


def _pockets_void(
    model: cq.Workplane, item: Item, profile: StackProfile, holding: Holding
) -> bool:
    """Every holding point is open: nothing is left standing where a pocket or a hole
    was cut."""

    foot = item.kind in ("bin", "frame")

    if foot or holding.kind == "bolt":
        z = holding.pocket_depth_mm / 2 if foot else item.floor_mm / 2
    else:
        z = item.floor_mm - holding.pocket_depth_mm / 2

    solids = workplane_shape(model).Solids()

    return not any(
        solid.isInside(cq.Vector(x, y, z))
        for x, y in holding_centres(profile, item.cells)
        for solid in solids
    )


def overlap_mm3(first: cq.Workplane, second: cq.Workplane) -> float:
    return intersection_volume(workplane_shape(first), workplane_shape(second))


def slide_clearance(printer: Mapping[str, Any] | None) -> float:
    """What a sliding fit leaves per side: the printer's, or a default without one."""

    if printer is None:
        return DEFAULT_CLEARANCE_MM

    return printer_numbers(printer)[0]["sliding_clearance_per_side"]


def frame_plan(
    frame: Item, profile: StackProfile, clearance: float, drawer: Item | None = None
) -> FramePlan:
    """The sizes a frame and its drawers share; ``drawer`` sets the drawers' walls."""

    return plan_frame(
        profile,
        frame.cells,
        frame.units,
        frame.drawers,
        frame.wall_mm,
        frame.floor_mm,
        drawer.wall_mm if drawer else frame.wall_mm,
        drawer.floor_mm if drawer else frame.floor_mm,
        clearance,
    )


def _frame(
    item: Item,
    profile: StackProfile,
    clearance: float,
    latch: LatchPlan | None = None,
) -> tuple[cq.Workplane, float, dict[str, Any]]:
    plan = frame_plan(item, profile, clearance)
    model, top = frame_solid(
        profile, item.cells, item.units, item.wall_mm, item.floor_mm, plan
    )
    holding = holding_for(item.holding, item.magnet, item.fastener)

    if holding.holds:
        model = cut_foot_pockets(
            model,
            profile,
            item.cells,
            holding.pocket_diameter_mm,
            holding.pocket_depth_mm,
        )

    if latch is not None:
        centres = cell_centres(item.cells, profile.pitch_mm)
        model = add_latch_feet(model, latch, centres, item.latch_sides)
        model = cut_lip_keepers(model, latch, centres, item.latch_sides, top)

    summary: dict[str, Any] = {
        "kind": "frame",
        "cells": list(item.cells),
        "units": item.units,
        "wall_height_mm": round(top, 3),
        "overall_height_mm": round(workplane_shape(model).BoundingBox().zlen, 3),
        "wall_mm": item.wall_mm,
        "floor_mm": item.floor_mm,
        "drawers": item.drawers,
        "slot_pitch_mm": round(plan.pitch, 3),
        "ledge_mm": LEDGE_MM,
        "ledge_thickness_mm": LEDGE_THICKNESS_MM,
        "roof_mm": ROOF_MM,
        **_holding_summary(holding, item.floor_mm),
        **_latch_summary(item, latch),
    }

    return model, top, summary


def _cap(
    item: Item, profile: StackProfile, plan: LatchPlan | None = None
) -> tuple[cq.Workplane, float, dict[str, Any]]:
    model, height = cap_solid(profile, item.cells, item.floor_mm)

    if plan is not None:
        model = add_latch_feet(
            model, plan, cell_centres(item.cells, profile.pitch_mm), item.latch_sides
        )

    summary: dict[str, Any] = {
        "kind": item.kind,
        "cells": list(item.cells),
        "thickness_mm": item.floor_mm,
        "overall_height_mm": round(height, 3),
        "holding": "lip",
        **_latch_summary(item, plan),
    }

    return model, height, summary


def _drawer(
    item: Item,
    profile: StackProfile,
    clearance: float,
    siblings: Mapping[str, Item],
) -> tuple[cq.Workplane, float, dict[str, Any]]:
    frame = siblings[item.frame]
    plan = frame_plan(frame, profile, clearance, item)
    model = drawer_solid(plan, item.pull)
    summary: dict[str, Any] = {
        "kind": "drawer",
        "frame": item.frame,
        "size_mm": [
            round(plan.drawer_width, 3),
            round(plan.drawer_length, 3),
            round(plan.drawer_height, 3),
        ],
        "interior_depth_mm": round(plan.drawer_interior_depth, 3),
        "wall_mm": item.wall_mm,
        "floor_mm": item.floor_mm,
        "clearance_per_side_mm": clearance,
        "finger_pull": item.pull,
        "slots": plan.slots,
        "held_by": "nothing: it comes out when pulled",
    }
    top = plan.floor_z + LEDGE_THICKNESS_MM + plan.drawer_height

    return model, top, summary


def build_item(
    item: Item,
    profile: StackProfile,
    printer: Mapping[str, Any] | None = None,
    siblings: Mapping[str, Item] | None = None,
) -> tuple[cq.Workplane, float, dict[str, Any]]:
    """One item's solid, the height a thing stacked on it sits at (a bin's walls' tops,
    a baseplate's pocket floor), and what the build says of it."""

    plan = latch_plan_for(item, profile, printer)

    if item.kind == "baseplate":
        return _baseplate(item, profile, plan)

    if item.kind in ("cap", "plate"):
        return _cap(item, profile, plan)

    if item.kind == "frame":
        return _frame(item, profile, slide_clearance(printer), plan)

    if item.kind == "drawer":
        return _drawer(item, profile, slide_clearance(printer), siblings or {})

    return _bin(item, profile, plan)


def _drawer_slides(drawer: cq.Workplane, frame: cq.Workplane, plan: FramePlan) -> bool:
    """The drawer, in every slot and pulled out by none, half and nine tenths of its
    length, does not touch the frame."""

    for slot in range(plan.slots):
        for travel in (0.0, 0.5, 0.9):
            moved = drawer.translate(
                (0.0, -travel * plan.drawer_length, slot * plan.pitch)
            )

            if overlap_mm3(moved, frame) > TOLERANCE_MM3:
                return False

    return True


def latch_checks(
    item: Item,
    profile: StackProfile,
    plan: LatchPlan,
    feet: cq.Workplane,
    lower: cq.Workplane,
    plain: cq.Workplane,
    height: float,
) -> dict[str, bool]:
    """A latch laid out as real solids. ``feet`` is the item with its tongues, ``lower`` the item
    it sits on with its keepers, ``plain`` that item without them, and ``height`` where the
    lower's lip begins. The tongues are freed and the keepers are open; a hook seated in the
    lip overlaps what a plain lip would be, so it does engage; and a hook deflected by its
    tongue's travel passes the plain lip all the way down."""

    centres = cell_centres(item.cells, profile.pitch_mm)
    foot_solids = workplane_shape(feet).Solids()
    lower_solids = workplane_shape(lower).Solids()

    def solid_in(solids: list[Any], point: tuple[float, float, float]) -> bool:
        return any(solid.isInside(cq.Vector(*point)) for solid in solids)

    freed = True
    opened = True

    for side in item.latch_sides:
        for centre in cells_on_side(side, centres):
            skin = foot_points(plan, centre, side)
            keepers = keeper_points(plan, centre, side, height)
            freed = (
                freed
                and solid_in(foot_solids, skin["skin"])
                and not solid_in(foot_solids, skin["relief"])
            )
            opened = (
                opened
                and not solid_in(lower_solids, keepers["keeper_mouth"])
                and solid_in(lower_solids, keepers["keeper_backing"])
            )

    engaged = True
    passes = True
    lip = profile.lip_height_mm

    for side in item.latch_sides:
        hooks = hook_solids(plan, centres, side)

        if hooks is None:
            continue

        seated = hooks.translate((0.0, 0.0, height))
        engaged = engaged and overlap_mm3(seated, plain) > 0.05
        dx, dy = inward(side)
        step = 0.25
        rise = lip

        while rise >= 0.0:
            moved = hooks.translate(
                (
                    dx * (plan.deflection_mm + 0.001),
                    dy * (plan.deflection_mm + 0.001),
                    height + rise,
                )
            )
            passes = passes and overlap_mm3(moved, plain) <= TOLERANCE_MM3
            rise -= step

    return {
        f"{item.name}.latch_tongues_freed": freed,
        f"{item.name}.latch_keepers_open": opened,
        f"{item.name}.latch_hook_engages": engaged,
        f"{item.name}.latch_hook_passes": passes,
    }


def build_stack(spec: StackSpec, printer: Mapping[str, Any]) -> Stack:
    """The items a stack file lists, refused if one cannot be built."""

    profile = load_stack_profile(spec)
    parts: dict[str, cq.Workplane] = {}
    checks: dict[str, bool] = {}
    items: dict[str, Any] = {}
    plates = {
        item.cells: baseplate_solid(profile, item.cells, item.floor_mm, item.rim_mm)
        for item in spec.items
        if item.kind == "baseplate"
    }

    siblings = {item.name: item for item in spec.items}
    clearance = slide_clearance(printer)

    for item in sorted(spec.items, key=lambda i: i.kind == "drawer"):
        model, height, summary = build_item(item, profile, printer, siblings)

        parts[item.name] = model
        checks[f"{item.name}.one_solid"] = solid_count(model) == 1
        items[item.name] = summary
        holding = holding_for(item.holding, item.magnet, item.fastener)

        if holding.holds:
            checks[f"{item.name}.holding_points_open"] = _pockets_void(
                model, item, profile, holding
            )

        if item.kind == "cap":
            lid_bin, bin_top = bin_solid(profile, item.cells, 1, 1.2, 1.2)
            cap_latch = latch_plan_for(item, profile, printer)
            keyed_bin = lid_bin

            if cap_latch is not None:
                keyed_bin = cut_lip_keepers(
                    lid_bin,
                    cap_latch,
                    cell_centres(item.cells, profile.pitch_mm),
                    item.latch_sides,
                    bin_top,
                )
                checks.update(
                    latch_checks(
                        item, profile, cap_latch, model, keyed_bin, lid_bin, bin_top
                    )
                )

            checks[f"{item.name}.sits_on_a_bin"] = (
                overlap_mm3(model.translate((0, 0, bin_top)), keyed_bin)
                <= TOLERANCE_MM3
            )

        if item.kind == "drawer":
            frame_item = siblings[item.frame]
            plan = frame_plan(frame_item, profile, clearance, item)
            checks[f"{item.name}.slides_in_{item.frame}"] = _drawer_slides(
                model, parts[item.frame], plan
            )

        if item.kind in ("bin", "frame"):
            checks[f"{item.name}.stacks_on_itself"] = (
                overlap_mm3(model.translate((0, 0, height)), model) <= TOLERANCE_MM3
            )
            plate, floor = plates.get(item.cells) or baseplate_solid(
                profile, item.cells, item.floor_mm, 1.2
            )
            latch = latch_plan_for(item, profile, printer)

            if latch is not None:
                plate = cut_plate_keepers(
                    plate,
                    latch,
                    cell_centres(item.cells, profile.pitch_mm),
                    item.latch_sides,
                    floor,
                )
                plain, _, _ = build_item(
                    replace(item, latch_sides=()), profile, printer
                )
                checks.update(
                    latch_checks(item, profile, latch, model, model, plain, height)
                )

            checks[f"{item.name}.sits_on_baseplate"] = (
                overlap_mm3(model.translate((0, 0, floor)), plate) <= TOLERANCE_MM3
            )

    return Stack(
        spec=spec,
        parts=parts,
        checks=checks,
        summary={
            "profile": profile.identifier,
            "profile_sha256": profile.sha256,
            "pitch_mm": profile.pitch_mm,
            "height_unit_mm": profile.height_unit_mm,
            "foot_height_mm": profile.foot_height_mm,
            "lip_height_mm": profile.lip_height_mm,
            "lip_tip_mm": LIP_TIP_MM,
            "nest_clearance_mm": profile.min_nest_clearance_mm,
            "items": items,
        },
        profile_id=str(printer.get("profile_id", "")),
        notes=(NOT_CLAIMED,),
    )


def require_fits_bed(stack: Stack, printer: Mapping[str, Any]) -> None:
    """Refuse an item that will not lie on the printer's bed; a baseplate too big for it
    is told how many cells fit."""

    volume = printer.get("build_volume_mm")

    if not volume:
        return

    for name, model in stack.parts.items():
        box = workplane_shape(model).BoundingBox()
        fits = box.xlen <= volume["x"] and box.ylen <= volume["y"]
        turned = box.xlen <= volume["y"] and box.ylen <= volume["x"]

        if not (fits or turned) or box.zlen > volume["z"]:
            across = int(volume["x"] // stack.summary["pitch_mm"])
            raise ValueError(
                f"The {name} is {box.xlen:.0f} x {box.ylen:.0f} x {box.zlen:.0f} mm; "
                f"the printer's bed is {volume['x']:.0f} x {volume['y']:.0f} x "
                f"{volume['z']:.0f} mm, which takes about {across} cells across: "
                "build it as tiles or make it smaller"
            )
