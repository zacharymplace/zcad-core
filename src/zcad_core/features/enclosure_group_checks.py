"""What the group enclosure builder refuses, and the checks it makes of what it built."""

from __future__ import annotations

import cadquery as cq

from zcad_core.features.enclosure_group_envelope import single_shape
from zcad_core.features.enclosure_group_model import GroupDesign
from zcad_core.geometry.intersection import intersection_volume

_INTERFERENCE_TOLERANCE_MM3 = 1e-6


_SCREW_LENGTHS_MM = (4, 5, 6, 8, 10, 12, 16, 20)


def _require_stack_top_possible(design: GroupDesign, *, fans: int) -> None:
    """Refuse a stack top on a lid that does not stay shut with its own screws or has a fan on
    it: the plate would fix a hinged or sliding lid, and stand on a fan's frame. The lid's slots
    and outlets are not a reason: the plate leaves a window over each."""

    reasons: list[str] = []

    if design.lid_attachment != "screws":
        reasons.append(
            f"the lid is '{design.lid_attachment}', and a stack top is held by a screwed "
            "lid's own screws, so the lid must be 'screws'"
        )

    if fans:
        reasons.append("a fan is mounted on the lid, and its frame stands above it")

    if reasons:
        raise ValueError(
            "A stack top cannot go on this row:\n- " + "\n- ".join(reasons)
        )


def _part_collisions(
    base: cq.Workplane,
    lid: cq.Workplane,
    parts: dict[str, dict[str, cq.Shape]],
) -> tuple[str, ...]:
    """Each Pi part that runs into the base or the lid. A bay's parts are
    tried together first, and one by one only when they meet something."""

    collisions: list[str] = []

    for name, solid in (("base", single_shape(base)), ("lid", single_shape(lid))):
        for bay, shapes in parts.items():
            if not shapes:
                continue

            together = cq.Compound.makeCompound(list(shapes.values()))

            if intersection_volume(solid, together) <= _INTERFERENCE_TOLERANCE_MM3:
                continue

            collisions.extend(
                f"{bay} {part} meets the {name}"
                for part, shape in shapes.items()
                if intersection_volume(solid, shape) > _INTERFERENCE_TOLERANCE_MM3
            )

    return tuple(collisions)


def _checks(
    base: cq.Workplane, lid: cq.Workplane, hardware: dict[str, cq.Shape]
) -> dict[str, bool]:
    base_shape, lid_shape = single_shape(base), single_shape(lid)

    def clear(first: cq.Shape, second: cq.Shape) -> bool:
        return intersection_volume(first, second) <= _INTERFERENCE_TOLERANCE_MM3

    return {
        "base_and_lid_clear": clear(base_shape, lid_shape),
        "hardware_clear_of_base": all(
            clear(base_shape, shape) for shape in hardware.values()
        ),
        "hardware_clear_of_lid": all(
            clear(lid_shape, shape) for shape in hardware.values()
        ),
        "one_solid_per_part": len(base.solids().vals()) == 1
        and len(lid.solids().vals()) == 1,
    }


def _longest_screw(usable_mm: float) -> int:
    fitting = [length for length in _SCREW_LENGTHS_MM if length <= usable_mm]

    if not fitting:
        raise ValueError("No standard screw is short enough")

    return fitting[-1]
