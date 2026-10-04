"""What a group enclosure's build reports and refuses: its screws, the bed it must fit, its
parts, its stack top and its warnings.
"""

from __future__ import annotations

from typing import Any

import cadquery as cq

from zcad_core.features.enclosure_group import GroupEnclosure
from zcad_core.features.mount_stack import require_plate_fits_bed, require_top_fits_bed
from zcad_core.features.mounts import MountPlate
from zcad_core.geometry.cadquery_support import workplane_shape


def _screw_style(mount: MountPlate) -> str:
    return "in a head recess" if mount.stack is not None else "countersunk"


def _require_fits_bed(group: GroupEnclosure, profile: dict[str, Any]) -> None:
    """Say how to split a row that will not lie flat on the bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, _ = group.outer_size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    fits_turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or fits_turned):
        raise ValueError(
            f"The {len(group.bays)}-bay row is {width:.0f} x {depth:.0f} mm; the "
            f"printer's bed is {volume['x']:.0f} x {volume['y']:.0f} mm. Build "
            "shorter units and bolt them together: each unit's left wall takes "
            "the join screws from the next unit's right wall."
        )

    _require_ears_fit_bed(group, volume)
    require_plate_fits_bed(group.mount, volume)
    require_top_fits_bed(group.stack_top, volume)


def _require_ears_fit_bed(group: GroupEnclosure, volume: dict[str, Any]) -> None:
    """Refuse rack ears longer than the bed: they are one piece each."""

    if group.mount is None or group.mount.pieces is None:
        return

    bed = sorted((volume["x"], volume["y"]))

    for name, piece in group.mount.pieces.items():
        bounds = workplane_shape(piece).BoundingBox()
        small, large = sorted((bounds.xlen, bounds.ylen, bounds.zlen))[1:]

        if large > bed[1] or small > bed[0]:
            raise ValueError(
                f"The {name} part is {large:.0f} x {small:.0f} mm; the "
                f"printer's bed is {bed[1]:.0f} x {bed[0]:.0f} mm. An ear "
                "reaches from the enclosure to the rack's edge, so a narrower "
                "enclosure needs longer ears; build a wider one or use another "
                "mount."
            )


def _parts(group: GroupEnclosure) -> dict[str, cq.Workplane]:
    parts = {"base": group.base, "lid": group.lid}

    if group.mount is not None:
        parts.update(group.mount.parts)

    if group.stack_top is not None:
        parts["stack_top"] = group.stack_top.plate

    return parts


def _stack_top_payload(group: GroupEnclosure) -> dict[str, object] | None:
    top = group.stack_top

    if top is None:
        return None

    return {
        "cells": list(top.cells),
        "size_mm": [round(top.size_mm[0], 3), round(top.size_mm[1], 3)],
        "thickness_mm": round(top.thickness_mm, 3),
        "floor_mm": round(top.floor_mm, 3),
        "screws": f"{group.fastener.identifier} x {top.recommended_screw_mm} mm, "
        f"{len(group.lid_boss_positions)} through the plate and the lid in place of the "
        "lid's own, in a head recess",
        "screw_reach_mm": round(top.screw_reach_mm, 3),
        "stack": top.stack,
    }


def _group_warnings(group: GroupEnclosure) -> list[str]:
    """What a fan's figures were not checked against."""

    return [
        f"{fan.model}: its figures were not read from the maker's own page; check "
        f"them{fan.unverified}"
        for fan in group.fans
        if not fan.datasheet_read
    ]
