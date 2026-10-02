"""What a nest and a guide share: a pocket round a part's shadow, and the checks on it.

A nest turns a part into a pocket. It follows the part's **shadow** (its outline seen from
above, undercuts and overhangs included), widened by the printer's sliding clearance, with a wall
round it. A pocket cut to the shadow lets the part lift straight out whatever its shape beneath.

Both products use it: the drill guide cuts the pocket from its underside with a plate above, and the
holding nest cuts it from a floor up. The functions here are the ones both build with, so a change to
the pocket or to the release check changes both.

Frame: the part's own, as in :mod:`zcad_core.features.guide_file`: centred on its bounding box in X and
Y, with its top face at ``z == 0`` and the part below it.
"""

from __future__ import annotations

from collections.abc import Sequence

import cadquery as cq

from zcad_core.geometry.intersection import intersection_volume
from zcad_core.geometry.outline_prism import outline_prism

# How far a body is moved per step in the release check.
RELEASE_STEP_MM = 2.0
TOLERANCE_MM3 = 1e-6

Point = tuple[float, float]


def pocketed(
    points: Sequence[Point],
    *,
    clearance_mm: float,
    wall_mm: float,
    outer_z0: float,
    outer_z1: float,
    pocket_z0: float,
    pocket_z1: float,
) -> cq.Workplane:
    """A body round the outline, grown by the clearance and the wall, with the outline's
    pocket (grown by the clearance only) cut out of it between two heights."""

    outer = outline_prism(points, outer_z0, outer_z1, clearance_mm + wall_mm)
    pocket = outline_prism(points, pocket_z0, pocket_z1, clearance_mm)

    return outer.cut(pocket)


def clear(first: object, second: cq.Shape) -> bool:
    """Whether two shapes share no volume."""

    if not isinstance(first, cq.Shape):
        raise TypeError("Expected a shape")

    return intersection_volume(first, second) <= TOLERANCE_MM3


def lifts_off(body: object, part: cq.Shape, height_mm: float) -> bool:
    """Lift the body up off the part in steps, to clear of the part's whole height, and
    refuse one that meets the part on the way."""

    if not isinstance(body, cq.Shape):
        raise TypeError("Expected a shape")

    lift = RELEASE_STEP_MM

    while lift <= height_mm + RELEASE_STEP_MM:
        moved = body.moved(cq.Location(cq.Vector(0, 0, lift)))

        if intersection_volume(moved, part) > TOLERANCE_MM3:
            return False

        lift += RELEASE_STEP_MM

    return True


def lifts_out(part: cq.Shape, body: object, rise_mm: float) -> bool:
    """Lift the part up out of the body in steps, through ``rise_mm``, and refuse a body
    that catches it on the way."""

    if not isinstance(body, cq.Shape):
        raise TypeError("Expected a shape")

    lift = RELEASE_STEP_MM

    while lift <= rise_mm + RELEASE_STEP_MM:
        moved = part.moved(cq.Location(cq.Vector(0, 0, lift)))

        if intersection_volume(moved, body) > TOLERANCE_MM3:
            return False

        lift += RELEASE_STEP_MM

    return True
