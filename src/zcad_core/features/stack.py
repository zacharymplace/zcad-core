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
from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from zcad_core.features.stack_file import (
    DEFAULT_SCOOP_MM,
    DEFAULT_TAB_MM,
    Item,
    StackSpec,
    load_stack_profile,
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
    solid_count,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume

_TOLERANCE_MM3 = 1e-3
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


def _bin(
    item: Item, profile: StackProfile
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
    }

    return model, top, summary


def _baseplate(
    item: Item, profile: StackProfile
) -> tuple[cq.Workplane, float, dict[str, Any]]:
    model, floor = baseplate_solid(profile, item.cells, item.floor_mm, item.rim_mm)
    summary = {
        "kind": "baseplate",
        "cells": list(item.cells),
        "floor_mm": item.floor_mm,
        "rim_mm": item.rim_mm,
        "ridge_top_mm": RIDGE_TOP_MM,
    }

    return model, floor, summary


def _overlap(first: cq.Workplane, second: cq.Workplane) -> float:
    return intersection_volume(workplane_shape(first), workplane_shape(second))


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

    for item in spec.items:
        if item.kind == "bin":
            model, height, summary = _bin(item, profile)
        else:
            model, height, summary = _baseplate(item, profile)

        parts[item.name] = model
        checks[f"{item.name}.one_solid"] = solid_count(model) == 1
        items[item.name] = summary

        if item.kind == "bin":
            checks[f"{item.name}.stacks_on_itself"] = (
                _overlap(model.translate((0, 0, height)), model) <= _TOLERANCE_MM3
            )
            plate, floor = plates.get(item.cells) or baseplate_solid(
                profile, item.cells, item.floor_mm, 1.2
            )
            checks[f"{item.name}.sits_on_baseplate"] = (
                _overlap(model.translate((0, 0, floor)), plate) <= _TOLERANCE_MM3
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
