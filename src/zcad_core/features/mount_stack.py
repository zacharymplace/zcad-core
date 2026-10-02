"""The stack mount: a plate that bolts to an enclosure's pads and stands on the grid.

A stack plate is a flat plate on a stack profile's foot, in whole cells: a cap that
screws to the enclosure's four mount pads instead of sitting loose. The enclosure then
stands on a baseplate, on a bin or a frame of the same cells, or on another stack
plate's lip, like any item built on the profile.

The screws come from below, so each goes up through a foot. A recess in the foot's bottom
sinks the screw's head, and the build refuses a plate where a recess would cut across a
foot's edge: it tries one more cell across or deep, up to two, so the pads fall inside the
feet, and refuses if none does. The plate is centred on the pads.

The recess depth and its margin are the engine's own design choices.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import cadquery as cq

from zcad_core.features.mounts import (
    HEAD_DIAMETER_FACTOR,
    MountPads,
    MountPlate,
    _pad_bounds,
    cut_all,
    standard_screw_length,
)
from zcad_core.features.stack_drawers import cap_solid
from zcad_core.features.stack_profile import StackProfile
from zcad_core.features.stack_solids import cell_centres
from zcad_core.hardware import FastenerSpec

# A screw's head is about its nominal diameter tall; the recess is a little deeper.
RECESS_EXTRA_MM = 0.5
# The recess leaves at least this much foot above it, and this much round it.
FOOT_ABOVE_RECESS_MM = 1.0
RECESS_WALL_MM = 1.0
# The recess is the head's diameter and this much over.
RECESS_OVER_MM = 0.6
# How many cells past the least the search may add, each way.
MAXIMUM_EXTRA_CELLS = 2


def _recess_radius(fastener: FastenerSpec) -> float:
    return (fastener.nominal_diameter_mm * HEAD_DIAMETER_FACTOR + RECESS_OVER_MM) / 2


def recess_depth_mm(fastener: FastenerSpec) -> float:
    """How far up from the foot's bottom a screw's head is sunk."""

    return fastener.nominal_diameter_mm + RECESS_EXTRA_MM


def _inside_a_foot(
    position: tuple[float, float],
    cells: tuple[int, int],
    profile: StackProfile,
    radius: float,
) -> bool:
    """The recess circle lies inside one cell's foot bottom, with the wall round it."""

    room = profile.cell_top_mm / 2 - profile.foot[0][0] - RECESS_WALL_MM - radius

    return any(
        max(abs(position[0] - cx), abs(position[1] - cy)) <= room
        for cx, cy in cell_centres(cells, profile.pitch_mm)
    )


def _cell_options(
    least: tuple[int, int],
) -> list[tuple[int, int]]:
    options = [
        (least[0] + extra_x, least[1] + extra_y)
        for extra_x in range(MAXIMUM_EXTRA_CELLS + 1)
        for extra_y in range(MAXIMUM_EXTRA_CELLS + 1)
    ]

    return sorted(options, key=lambda cells: (cells[0] * cells[1], sum(cells)))


def build_stack_plate(
    pads: MountPads,
    *,
    fastener: FastenerSpec,
    profile: StackProfile,
    plate_mm: float,
    compensation: float,
) -> MountPlate:
    """The plate in the enclosure's frame, its top face on the pads' bottoms."""

    x0, x1, y0, y1 = _pad_bounds(pads)
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    least = (
        math.ceil(((x1 - x0) + profile.gap_mm) / profile.pitch_mm),
        math.ceil(((y1 - y0) + profile.gap_mm) / profile.pitch_mm),
    )
    radius = _recess_radius(fastener)
    recess = recess_depth_mm(fastener)

    if profile.foot_height_mm - recess < FOOT_ABOVE_RECESS_MM:
        raise ValueError(
            f"A {fastener.identifier} head needs a recess {recess:g} mm deep, and the "
            f"profile's foot is {profile.foot_height_mm:g} mm: it would leave "
            f"{profile.foot_height_mm - recess:g} mm, under {FOOT_ABOVE_RECESS_MM:g}"
        )

    for cells in _cell_options(least):
        relative = [(px - centre[0], py - centre[1]) for px, py in pads.positions]

        if all(_inside_a_foot(p, cells, profile, radius) for p in relative):
            return _plate(
                pads, fastener, profile, plate_mm, compensation, cells, centre, recess
            )

    raise ValueError(
        f"No stack plate of {least[0]} to {least[0] + MAXIMUM_EXTRA_CELLS} by "
        f"{least[1]} to {least[1] + MAXIMUM_EXTRA_CELLS} cells puts all four mount "
        f"pads inside a foot with a {fastener.identifier} head's recess: a screw would "
        "land on a foot's edge. Change the wall, the fastener or the profile"
    )


def _plate(
    pads: MountPads,
    fastener: FastenerSpec,
    profile: StackProfile,
    plate_mm: float,
    compensation: float,
    cells: tuple[int, int],
    centre: tuple[float, float],
    recess: float,
) -> MountPlate:
    model, height = cap_solid(profile, cells, plate_mm)
    # The cap's top is the pads' bottoms; its feet hang below.
    model = model.translate((centre[0], centre[1], pads.mating_z_mm - height))
    foot_bottom = pads.mating_z_mm - height
    screw_hole = fastener.clearance_hole_mm + compensation
    radius = _recess_radius(fastener)

    for x, y in pads.positions:
        model = cut_all(
            model,
            cq.Solid.makeCylinder(
                screw_hole / 2,
                height + 2.0,
                pnt=cq.Vector(x, y, foot_bottom - 1.0),
            ),
            cq.Solid.makeCylinder(
                radius, recess + 1.0, pnt=cq.Vector(x, y, foot_bottom - 1.0)
            ),
        )

    reach = (profile.foot_height_mm - recess) + plate_mm + pads.pocket_depth_mm
    width = cells[0] * profile.pitch_mm - profile.gap_mm
    depth = cells[1] * profile.pitch_mm - profile.gap_mm
    stack: dict[str, Any] = {
        "profile": {
            "identifier": profile.identifier,
            "path": str(profile.path),
            "sha256": profile.sha256,
        },
        "cells": list(cells),
        "plate_mm": plate_mm,
        "foot_height_mm": profile.foot_height_mm,
        "holding": "lip",
        "screw_recess_mm": recess,
        "screw_reach_mm": round(reach, 3),
    }

    return MountPlate(
        plate=model,
        thickness_mm=plate_mm,
        recommended_screw_mm=standard_screw_length(reach),
        size_mm=(width, depth),
        attachment=(
            f"stacks on a baseplate, or a bin or frame of {cells[0]} x {cells[1]} cells, "
            f"built to the profile {profile.identifier}"
        ),
        stack=stack,
    )


def require_plate_fits_bed(
    mount: MountPlate | None, volume: Mapping[str, Any] | None
) -> None:
    """Refuse a stack plate larger than the printer's bed, with its cells and the bed's."""

    if mount is None or mount.stack is None or not volume:
        return

    width, depth = mount.size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or turned):
        cells = mount.stack["cells"]

        raise ValueError(
            f"The stack plate is {cells[0]} x {cells[1]} cells, {width:.0f} x "
            f"{depth:.0f} mm; the printer's bed is {volume['x']:.0f} x "
            f"{volume['y']:.0f} mm. A stack plate is whole cells under the "
            "enclosure's footprint: build a narrower enclosure, or shorter units "
            "bolted together"
        )
