"""Units that join: the standard joint face, the cable pass-through, and the check
that two units bolt together.

A row too wide for the bed is built as units, each a box of one or more bays. Each
unit's left wall carries two heat-set insert bosses and its right wall two clearance
holes, so the next unit's left wall meets this one's right wall and a screw crosses
both. The first version put the bolts at fixed *fractions* of the unit's depth, which
mates only units of the same depth.

The **standard joint face** puts them at fixed distances from the unit's front
outer face and its underside, in the enclosure's own frame, so a unit of any depth
carries them in the same place and any unit's left wall meets any other's right,
over the depth they share. An optional **pass-through**, one rectangular opening in a
join wall at a fixed place above the bolts, lets a cable run from one unit to the
next. A unit's height is its own: the lids are separate, so units of different
height need no match.

The standard face is opt-in (``GroupDesign.joint_face = "standard"``), so a build that
does not ask for it is unchanged. :func:`check_join` builds nothing: it takes two
built units, puts the second against the first's right wall, and reports whether a
screw passes through each hole into each boss, the walls meet without a gap or an
overlap, and a pass-through, where both have one, lines up. It works on a unit of
either face, since it reads the geometry; whether a unit is on the standard face is
reported beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from zcad_core.features.enclosure_group_envelope import make_box, single_shape
from zcad_core.features.enclosure_group_model import (
    OPENING_RIM_MM,
    GroupDesign,
    GroupEnclosure,
)
from zcad_core.geometry.intersection import intersection_volume

# The standard face: the bolts' distances from the unit's front outer face, and from
# its underside; the pass-through's centre from the front outer face, and its lower
# edge from the underside (above the bolts' bosses).
STANDARD_JOINT_Y_MM = (20.0, 38.0)
STANDARD_JOINT_Z_MM = 10.0
PASS_THROUGH_Y_MM = 29.0
PASS_THROUGH_BOTTOM_MM = 16.0
# The old face: the bolts at these fractions of the inner depth, this far above the
# floor.
FRACTION_JOINT_Y = (0.65, 0.83)
FRACTION_JOINT_ABOVE_FLOOR_MM = 8.0
# A sliding lid's entry wall comes down to the groove's floor, so a pass-through in
# it stops this much under the wall's top.
_SLIDE_WALL_DROP_MM = 5.0
_TOLERANCE_MM = 0.05
_TOLERANCE_MM3 = 1e-3


def joint_positions(
    design: GroupDesign,
    *,
    wall: float,
    inner_depth: float,
    outer_depth: float,
    radius: float,
    corner_x: float,
    screwed: bool,
) -> tuple[tuple[float, float], ...]:
    """Where the join bolts go, as ``(y, z)`` from the front outer face and the
    underside, refusing a unit the standard face does not fit."""

    if design.joint_face == "fractions":
        return tuple(
            (
                wall + inner_depth * fraction,
                design.floor_mm + FRACTION_JOINT_ABOVE_FLOOR_MM,
            )
            for fraction in FRACTION_JOINT_Y
        )

    low, high = STANDARD_JOINT_Y_MM

    if STANDARD_JOINT_Z_MM - radius < design.floor_mm:
        raise ValueError(
            f"The standard joint face puts the bolts {STANDARD_JOINT_Z_MM:g} mm up "
            f"and their bosses are {radius:g} mm in radius, which reaches the "
            f"{design.floor_mm:g} mm floor: use a thinner floor or a smaller fastener"
        )

    need = high + radius + wall

    if outer_depth < need:
        raise ValueError(
            f"The unit is {outer_depth:.1f} mm deep and the standard joint face "
            f"needs {need:.1f} mm for its bolts: use fewer bays, a deeper board, or "
            "joint_face='fractions'"
        )

    if screwed:
        # The lid's corner bosses stand clear of the bolts' bosses.
        corner_y = wall + corner_x
        clear = 2 * radius + 1.0

        if low - corner_y < clear or (outer_depth - corner_y) - high < clear:
            raise ValueError(
                f"The unit is {outer_depth:.1f} mm deep and the standard joint "
                f"face's bolts would meet the lid's corner bosses, which need "
                f"{clear:.1f} mm between centres: make the unit deeper, or use a "
                "hinged or sliding lid"
            )

    return tuple((y, STANDARD_JOINT_Z_MM) for y in STANDARD_JOINT_Y_MM)


def cut_pass_through(
    base: cq.Workplane,
    design: GroupDesign,
    *,
    outer: tuple[float, float, float],
    cavity_top: float,
    radius: float,
    corner_x: float,
    screwed: bool,
) -> cq.Workplane:
    """The pass-through in the join wall or walls, refused if it would reach the
    lid's seat, the bolts' bosses, or the lid's corner bosses."""

    if design.pass_through_mm is None:
        return base

    width, height = design.pass_through_mm
    wall = design.wall_mm
    y0, y1 = PASS_THROUGH_Y_MM - width / 2, PASS_THROUGH_Y_MM + width / 2
    z0, z1 = PASS_THROUGH_BOTTOM_MM, PASS_THROUGH_BOTTOM_MM + height
    limit = cavity_top - OPENING_RIM_MM
    drop = _SLIDE_WALL_DROP_MM if design.lid_attachment == "slide" else 0.0

    if z1 > limit - drop:
        raise ValueError(
            f"The pass-through reaches {z1:g} mm and the wall may be cut to "
            f"{limit - drop:g} mm under the lid: make it shorter or raise "
            "headroom_mm"
        )

    if z0 < STANDARD_JOINT_Z_MM + radius + 1.0:
        raise ValueError(
            "The pass-through starts too low: it would meet the join bolts' bosses"
        )

    corner_y = wall + corner_x
    margin = radius + 1.0 if screwed else 0.0

    if y0 < corner_y + margin or y1 > outer[1] - corner_y - margin:
        raise ValueError(
            f"A {width:g} mm wide pass-through at {PASS_THROUGH_Y_MM:g} mm would "
            f"meet the lid's corner bosses in a unit {outer[1]:.1f} mm deep: make "
            "it narrower, or the unit deeper"
        )

    sides = []

    if design.pass_through_sides in ("both", "left"):
        sides.append((-1.0, wall + 0.01))

    if design.pass_through_sides in ("both", "right"):
        sides.append((outer[0] - wall - 0.01, outer[0] + 1.0))

    for x0, x1 in sides:
        base = base.cut(make_box((x0, x1), (y0, y1), (z0, z1)))

    return base


@dataclass(frozen=True)
class JoinReport:
    """Whether two units bolt together, and each check that says so."""

    checks: dict[str, bool]
    details: dict[str, Any]
    notes: tuple[str, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def _screw(unit: GroupEnclosure, y: float, z: float, x0: float, x1: float) -> cq.Shape:
    return cq.Solid.makeCylinder(
        unit.fastener.nominal_diameter_mm / 2,
        x1 - x0,
        pnt=cq.Vector(x0, y, z),
        dir=cq.Vector(1, 0, 0),
    )


def _same_places(
    first: tuple[tuple[float, float], ...], second: tuple[tuple[float, float], ...]
) -> bool:
    if len(first) != len(second):
        return False

    return all(
        abs(a[0] - b[0]) <= _TOLERANCE_MM and abs(a[1] - b[1]) <= _TOLERANCE_MM
        for a, b in zip(sorted(first), sorted(second), strict=True)
    )


def _bolts(left: GroupEnclosure, right: GroupEnclosure) -> tuple[bool, bool]:
    """Whether a screw goes through each of the left unit's right-wall holes and
    into a pocket in a boss of the right unit's left wall."""

    if not left.join_positions or not right.join_positions:
        return False, False

    shift = left.outer_size_mm[0]
    wall = left.design.wall_mm
    insert_depth = right.fastener.heat_set_insert_depth_mm or 0.0
    base_left = single_shape(left.base)
    base_right = single_shape(right.base).translate(cq.Vector(shift, 0, 0))
    same = _same_places(left.join_positions, right.join_positions)
    through = True
    seated = True

    for y, z in left.join_positions:
        screw = _screw(left, y, z, shift - wall, shift + insert_depth)
        through = through and intersection_volume(base_left, screw) <= _TOLERANCE_MM3
        pocket = cq.Vector(shift + insert_depth / 2, y, z)
        boss = cq.Vector(
            shift + 2.0,
            y,
            z + (right.fastener.heat_set_insert_diameter_mm or 0.0) / 2 + 0.6,
        )
        seated = (
            seated
            and not any(s.isInside(pocket) for s in base_right.Solids())
            and any(s.isInside(boss) for s in base_right.Solids())
        )

    return same and through, same and seated


def _pass_through_open(unit: GroupEnclosure, side: str) -> bool:
    """Whether the unit has an opening in that join wall at the standard place."""

    wall = unit.design.wall_mm
    x = wall / 2 if side == "left" else unit.outer_size_mm[0] - wall / 2
    point = cq.Vector(x, PASS_THROUGH_Y_MM, PASS_THROUGH_BOTTOM_MM + 0.5)

    return not any(s.isInside(point) for s in single_shape(unit.base).Solids())


def check_join(left: GroupEnclosure, right: GroupEnclosure) -> JoinReport:
    """Put ``right`` against ``left``'s right wall and check the joint."""

    shift = left.outer_size_mm[0]
    moved = single_shape(right.base).translate(cq.Vector(shift, 0, 0))
    base_left = single_shape(left.base)
    notes: list[str] = []
    shared = min(left.outer_size_mm[1], right.outer_size_mm[1])
    overlap = intersection_volume(base_left, moved)
    # The walls meet face to face where both stand: no overlap, and a gap of nothing.
    gap = base_left.distance(moved)
    through, seated = _bolts(left, right)
    checks = {
        "same_screw": left.fastener.identifier == right.fastener.identifier,
        "walls_do_not_overlap": overlap <= _TOLERANCE_MM3,
        "walls_meet": gap <= _TOLERANCE_MM,
        "bolts_pass_through_the_holes": through,
        "bolts_reach_the_bosses": seated,
    }
    left_open = _pass_through_open(left, "right")
    right_open = _pass_through_open(right, "left")

    if left_open and right_open:
        checks["pass_through_lines_up"] = (
            left.design.pass_through_mm == right.design.pass_through_mm
        )
    elif left_open or right_open:
        notes.append(
            "Only one unit has a pass-through at this joint: a cable has no "
            "opening to go through on the other side"
        )

    for name, unit in (("left", left), ("right", right)):
        if unit.design.joint_face != "standard":
            notes.append(
                f"The {name} unit is not on the standard joint face: its bolts are "
                "at fractions of its depth, and only units of the same depth mate"
            )

    return JoinReport(
        checks=checks,
        details={
            "shared_depth_mm": round(shared, 1),
            "depths_mm": [
                round(left.outer_size_mm[1], 1),
                round(right.outer_size_mm[1], 1),
            ],
            "left_joint": [list(p) for p in left.join_positions],
            "right_joint": [list(p) for p in right.join_positions],
            "overlap_mm3": round(overlap, 3),
            "gap_mm": round(gap, 3),
        },
        notes=tuple(notes),
    )
