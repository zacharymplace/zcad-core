"""Refusals the enclosure builder makes: a stack top that cannot be, and parts that collide."""

from __future__ import annotations

import cadquery as cq

from zcad_core.assemblies import DeviceAssembly
from zcad_core.features.enclosure_geometry import (
    _INTERFERENCE_TOLERANCE_MM3,
    _all_solids,
)
from zcad_core.features.enclosure_model import EnclosureDesign
from zcad_core.geometry.intersection import intersection_volume


def _require_stack_top_possible(design: EnclosureDesign) -> None:
    """Refuse a stack top on a lid that does not stay shut with its own screws or has a fan on
    it: the plate would fix a hinged, sliding or snap lid, and stand on a fan's frame. The lid's
    openings are not a reason: the plate leaves a window over each."""

    reasons: list[str] = []

    if design.lid_attachment != "screws":
        reasons.append(
            f"the lid is '{design.lid_attachment}', and a stack top is held by a screwed "
            "lid's own screws, so the lid must be 'screws'"
        )

    if design.fan is not None and design.fan_position == "lid":
        reasons.append("a fan is mounted on the lid, and its frame stands above it")

    if reasons:
        raise ValueError(
            "A stack top cannot go on this enclosure:\n- " + "\n- ".join(reasons)
        )


def _require_parts_clear(base: cq.Workplane, lid: cq.Workplane) -> None:
    """Refuse a lid whose retainer would run into the base's features."""

    overlap = intersection_volume(_all_solids(base), _all_solids(lid))

    if overlap > _INTERFERENCE_TOLERANCE_MM3:
        raise ValueError(
            f"The enclosure lid intersects the base by {overlap:.3f} mm3; "
            "increase side_clearance_mm or move the display"
        )


def _require_clear_of_assembly(
    assembly: DeviceAssembly, *, base: cq.Workplane, lid: cq.Workplane
) -> None:
    """Refuse an enclosure whose material intersects any assembly part."""

    parts = {"base": _all_solids(base), "lid": _all_solids(lid)}

    for component in assembly.components:
        geometry = _all_solids(component.transformed_geometry())

        for part_name, part in parts.items():
            overlap = intersection_volume(part, geometry)

            if overlap > _INTERFERENCE_TOLERANCE_MM3:
                raise ValueError(
                    f"The enclosure {part_name} intersects '{component.identifier}' "
                    f"by {overlap:.3f} mm3; increase the design's clearances or "
                    "move the part"
                )
