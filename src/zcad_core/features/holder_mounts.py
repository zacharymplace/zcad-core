"""How an object holder is fixed to a wall: the back plate's fixings.

- ``screws``: two countersunk holes for the user's screw. The hole is the shank plus the printer's
  hole oversize, drawn as a teardrop; a 90-degree countersink on the pocket side takes the head
  flush, so the object never sits on a screw head.
- ``keyhole``: the mounts' keyhole, two of them, with a channel in the plate's back face that a
  screw head standing off the wall rides up as the holder drops onto it.
- ``pegboard``: two square pegs off the plate's back face near its top, on the board's pitch, each
  through a hole and turned up behind the board. A peg is the largest square whose diagonal clears
  the hole by the sliding clearance each side.
- ``flat``: a plain back plate at least as large as the user's adhesive pad.

Screws and keyholes stand behind the object, side by side if the pocket is wide enough for two a
fixing's width apart, else one above the other. Every figure of a wall, a screw, a pegboard or a
pad is the user's, with its source; the engine says nothing about what any of them bears.

The holder prints as it hangs, so a peg leaves the plate horizontally and its underside is an
overhang the length of its reach behind the plate. A peg reaching further than
``MAXIMUM_PEG_REACH_MM`` is refused; one within it still prints with that overhang unsupported,
which a trial judges.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import cadquery as cq

from zcad_core.features.holder_file import HolderSpec
from zcad_core.features.holder_shapes import (
    Placed,
    Point,
    box,
    pointed_slot,
    teardrop,
    xz_prism,
)
from zcad_core.features.mounts import (
    FEATURE_WALL_MM,
    KEYHOLE_HEAD_DIAMETER_MM,
    KEYHOLE_HEAD_HEIGHT_MM,
    KEYHOLE_SLOT_WIDTH_MM,
    KEYHOLE_TRAVEL_MM,
)

# A countersink stops this short of the plate's back face.
COUNTERSINK_FLOOR_MM = 1.2
# A peg is never thinner than this, and passes through the board with this much play.
MINIMUM_PEG_MM = 2.5
PEG_PLAY_MM = 0.5
# The longest a peg may reach behind the plate, its underside printed with nothing under it.
MAXIMUM_PEG_REACH_MM = 12.0


@dataclass(frozen=True)
class Fixing:
    """A screw hole, a keyhole or a peg in the back plate: its centre seen from the room."""

    kind: str
    x_mm: float
    z_mm: float
    # A hole's width through the plate; a peg's square side.
    size_mm: float

    @property
    def has_hole(self) -> bool:
        return self.kind != "pegboard_peg"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "centre_mm": [round(self.x_mm, 3), round(self.z_mm, 3)],
            "size_mm": round(self.size_mm, 3),
        }


@dataclass(frozen=True)
class MountPlan:
    """What a mount adds to the holder and cuts from it, and how wide the back plate must be."""

    fixings: tuple[Fixing, ...]
    cutters: tuple[cq.Workplane, ...] = ()
    additions: tuple[cq.Workplane, ...] = ()
    plate_half_width_mm: float = 0.0
    details: Mapping[str, Any] = field(default_factory=dict)


def fixing_sites(
    p: Placed, clearance: float, half_width: float, below: float, above: float
) -> list[Point]:
    """Two fixings behind the object: side by side if the pocket is wide enough for two a
    fixing's width apart, else one above the other; each clear of the plate's edges, the
    floor and the plate's top by a feature wall."""

    reach = p.width_mm / 2 + clearance - FEATURE_WALL_MM - half_width
    low = below + FEATURE_WALL_MM
    high = p.height_mm - above - FEATURE_WALL_MM
    spacing = 4 * half_width

    if 2 * reach >= spacing and high >= low:
        z = max(low, min(high, 0.6 * p.height_mm))
        offset = min(reach, 30.0)

        return [(-offset, z), (offset, z)]

    if high - low >= spacing:
        return [(0.0, low), (0.0, low + max(spacing, (high - low) / 2))]

    raise ValueError(
        f"The back plate has no room for two fixings: each needs {2 * half_width:.1f} mm and "
        f"{spacing:.1f} mm between them, behind an object {p.width_mm:.1f} mm wide and "
        f"{p.height_mm:.1f} mm tall"
    )


def _screws(
    spec: HolderSpec, p: Placed, clearance: float, fits: Mapping[str, float]
) -> MountPlan:
    figures = spec.mount_figures
    oversize = fits["hole_oversize"]
    hole = figures["shank_diameter_mm"] + oversize
    head = figures["head_diameter_mm"] + oversize
    depth = (head - hole) / 2

    if depth > spec.back_mm - COUNTERSINK_FLOOR_MM:
        raise ValueError(
            f"A {figures['head_diameter_mm']:g} mm head needs a back plate at least "
            f"{depth + COUNTERSINK_FLOOR_MM:.1f} mm thick to sink flush; holder.back_mm is "
            f"{spec.back_mm:g}"
        )

    sites = fixing_sites(p, clearance, head / 2, head / 2, head * math.sqrt(2.0) / 2)
    cutters = []

    for x, z in sites:
        cutters.append(xz_prism(teardrop(x, z, hole / 2), -spec.back_mm - 1.0, 0.5))
        cone = cq.Solid.makeCone(
            head / 2 + 0.01,
            hole / 2,
            depth + 0.01,
            pnt=cq.Vector(x, 0.01, z),
            dir=cq.Vector(0, -1, 0),
        )
        cutters.append(cq.Workplane("XY").add(cone))

    return MountPlan(
        fixings=tuple(Fixing("countersunk_screw", x, z, hole) for x, z in sites),
        cutters=tuple(cutters),
    )


def _keyholes(
    spec: HolderSpec, p: Placed, clearance: float, fits: Mapping[str, float]
) -> MountPlan:
    channel = KEYHOLE_HEAD_HEIGHT_MM + 0.5

    if spec.back_mm < channel + FEATURE_WALL_MM:
        raise ValueError(
            f"A keyhole needs a back plate at least {channel + FEATURE_WALL_MM:.1f} mm thick, "
            f"to hide a screw head {KEYHOLE_HEAD_HEIGHT_MM:g} mm proud of the wall; "
            f"holder.back_mm is {spec.back_mm:g}"
        )

    oversize = fits["hole_oversize"]
    head = KEYHOLE_HEAD_DIAMETER_MM + oversize
    slot = KEYHOLE_SLOT_WIDTH_MM + oversize
    top = KEYHOLE_TRAVEL_MM + head * math.sqrt(2.0) / 2
    sites = fixing_sites(p, clearance, head / 2, head / 2, top)
    back = -spec.back_mm
    cutters = []

    for x, z in sites:
        cutters.append(xz_prism(teardrop(x, z, head / 2), back - 1.0, 0.5))
        cutters.append(
            xz_prism(pointed_slot(x, z, z + KEYHOLE_TRAVEL_MM, slot), back - 1.0, 0.5)
        )
        # The screw's head rides up a channel in the plate's back face as it hangs.
        cutters.append(
            xz_prism(
                pointed_slot(x, z - head / 2, z + KEYHOLE_TRAVEL_MM, head),
                back - 1.0,
                back + channel,
            )
        )

    return MountPlan(
        fixings=tuple(Fixing("keyhole", x, z, head) for x, z in sites),
        cutters=tuple(cutters),
    )


def _pegboard(
    spec: HolderSpec,
    p: Placed,
    cup_half_width: float,
    fits: Mapping[str, float],
) -> MountPlan:
    figures = spec.mount_figures
    pitch = figures["pitch_mm"]
    hole = figures["hole_diameter_mm"]
    board = figures["board_thickness_mm"]
    sliding = fits["sliding_clearance_per_side"]
    peg = math.floor((hole - 2 * sliding) / math.sqrt(2.0) * 10) / 10

    if peg < MINIMUM_PEG_MM:
        raise ValueError(
            f"A {hole:g} mm pegboard hole takes a peg {peg:.1f} mm square, under the "
            f"{MINIMUM_PEG_MM:g} mm least"
        )

    reach = board + PEG_PLAY_MM + peg

    if reach > MAXIMUM_PEG_REACH_MM:
        raise ValueError(
            f"A peg through a {board:g} mm board reaches {reach:.1f} mm behind the plate, "
            f"more than the {MAXIMUM_PEG_REACH_MM:g} mm a peg printed upright may overhang"
        )

    # As many pitches apart as the plate allows, and the plate widened for one if it must.
    room = 2 * (cup_half_width - FEATURE_WALL_MM) - peg
    pitches = max(1, math.floor(room / pitch + 1e-9))
    half = max(cup_half_width, pitches * pitch / 2 + peg / 2 + FEATURE_WALL_MM)
    z = p.height_mm - FEATURE_WALL_MM - peg / 2
    back = -spec.back_mm
    additions = []
    fixings = []

    for x in (-pitches * pitch / 2, pitches * pitch / 2):
        # The arm through the board, and the riser that turns up behind it.
        additions.append(
            box(
                x - peg / 2,
                x + peg / 2,
                back - reach,
                back + 0.1,
                z - peg / 2,
                z + peg / 2,
            )
        )
        additions.append(
            box(
                x - peg / 2,
                x + peg / 2,
                back - reach,
                back - reach + peg,
                z - peg / 2,
                z + peg / 2 + peg,
            )
        )
        fixings.append(Fixing("pegboard_peg", x, z, peg))

    return MountPlan(
        fixings=tuple(fixings),
        additions=tuple(additions),
        plate_half_width_mm=half,
        details={
            "pitches_apart": pitches,
            "peg_mm": peg,
            "reach_behind_plate_mm": round(reach, 3),
        },
    )


def _flat(spec: HolderSpec, p: Placed, cup_half_width: float) -> MountPlan:
    figures = spec.mount_figures
    tall = p.height_mm + spec.floor_mm

    if figures["height_mm"] > tall:
        raise ValueError(
            f"The pad is {figures['height_mm']:g} mm tall and the back plate only "
            f"{tall:.1f} mm"
        )

    return MountPlan(
        fixings=(),
        plate_half_width_mm=max(cup_half_width, figures["width_mm"] / 2),
        details={"pad_mm": [figures["width_mm"], figures["height_mm"]]},
    )


def plan_mount(
    spec: HolderSpec,
    p: Placed,
    clearance: float,
    cup_half_width: float,
    fits: Mapping[str, float],
) -> MountPlan:
    """The mount the holder file asks for, refused if the plate cannot carry it."""

    if spec.mount == "screws":
        plan = _screws(spec, p, clearance, fits)
    elif spec.mount == "keyhole":
        plan = _keyholes(spec, p, clearance, fits)
    elif spec.mount == "pegboard":
        return _pegboard(spec, p, cup_half_width, fits)
    else:
        return _flat(spec, p, cup_half_width)

    return MountPlan(
        fixings=plan.fixings,
        cutters=plan.cutters,
        plate_half_width_mm=cup_half_width,
    )


def pegs_on_pitch(fixings: tuple[Fixing, ...], pitch: float) -> bool:
    """Whether the pegs stand a whole number of pitches apart, on one row."""

    pegs = [f for f in fixings if f.kind == "pegboard_peg"]

    if len(pegs) != 2 or abs(pegs[0].z_mm - pegs[1].z_mm) > 1e-9:
        return False

    apart = abs(pegs[1].x_mm - pegs[0].x_mm) / pitch

    return apart >= 1 - 1e-9 and abs(apart - round(apart)) < 1e-9
