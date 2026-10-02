"""The features a holding nest can carry past a floor and a wall: strap slots, a label, and a lip.

- **Strap slots.** Two slots through the floor's flange, one at each end of the nest's longer side,
  each the strap's width and thickness with the printer's sliding clearance round it, so a hook-and-
  loop strap or a clamp's cord holds the nest still. The strap is the user's figure, with a source.
- **A label.** Embossed text on the flange's top, on a side the slots are not on.
- **A retaining lip.** Tabs cut from the wall, each bending outward on two slits, with a hook that overhangs the
  part's top face by ``overhang_mm``. The part presses past the hooks and is kept against being knocked. A
  tab's strain is the end-loaded cantilever's, checked against the provisional limit, and a part with no
  flat top is refused. The engine states no holding force.

Every size here except the user's strap figures is the engine's own design choice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.mounts import FLEXURE_STRAIN_LIMIT, flexure_for
from zcad_core.features.nest_file import NestSpec
from zcad_core.geometry.outline_prism import outline_prism

Point = tuple[float, float]
# A tab is this wide with a slit this wide each side, and keeps this much wall root below it.
TAB_WIDTH_MM = 10.0
SLIT_MM = 0.8
TAB_ROOT_MM = 2.0
# A hook stands this far above the part's top, is this tall, and its inner face is this tall.
HOOK_GAP_MM = 0.3
HOOK_HEIGHT_MM = 1.0
HOOK_FACE_MM = 0.4
# The label sits this far from the flange's edges, and a character is this wide as a share of
# the text's size.
LABEL_MARGIN_MM = 1.0
CHARACTER_WIDTH = 0.7
MAXIMUM_LABEL_CHARACTERS = 24
DEFAULT_TEXT_SIZE_MM = 3.0
DEFAULT_EMBOSS_MM = 0.4


@dataclass(frozen=True)
class StrapSlot:
    """One strap slot: its centre, and its sizes."""

    centre: Point
    length_mm: float
    width_mm: float
    # Whether the long side runs along Y.
    along_y: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "centre_mm": [round(self.centre[0], 3), round(self.centre[1], 3)],
            "length_mm": round(self.length_mm, 3),
            "width_mm": round(self.width_mm, 3),
        }


@dataclass(frozen=True)
class Label:
    """A label's text, size and where it sits."""

    text: str
    centre: Point
    size_mm: float
    emboss_mm: float
    rotated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "centre_mm": [round(self.centre[0], 3), round(self.centre[1], 3)],
            "size_mm": self.size_mm,
            "emboss_mm": self.emboss_mm,
        }


def extents(points: tuple[Point, ...]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    return min(xs), max(xs), min(ys), max(ys)


def flange_reach_mm(spec: NestSpec, clearance: float) -> float:
    """How far from the outline the flange's edge is."""

    return clearance + spec.wall_mm + spec.flange_mm


def plan_strap(
    spec: NestSpec,
    points: tuple[Point, ...],
    clearance: float,
    least_wall: float,
) -> tuple[tuple[StrapSlot, ...], list[str]]:
    """Where the two strap slots go, or why they cannot: each needs a strip of flange as wide
    as the slot with a minimum wall on both sides."""

    strap = spec.strap

    if strap is None:
        return (), []

    length = strap.width_mm + 2 * clearance
    width = strap.thickness_mm + 2 * clearance
    needed = width + 2 * least_wall

    if spec.flange_mm < needed:
        return (), [
            (
                f"a {strap.width_mm:g} x {strap.thickness_mm:g} mm strap needs a slot "
                f"{width:.1f} mm wide and a minimum wall of {least_wall:g} mm each side of it: "
                f"nest.flange_mm must be at least {needed:.1f}, and it is {spec.flange_mm:g}"
            )
        ]

    xmin, xmax, ymin, ymax = extents(points)
    along_y = (xmax - xmin) >= (ymax - ymin)
    middle = spec.wall_mm + clearance + spec.flange_mm / 2
    slots = []

    for sign in (1.0, -1.0):
        centre = (
            (sign * (xmax if sign > 0 else -xmin) + sign * middle, 0.0)
            if along_y
            else (0.0, sign * (ymax if sign > 0 else -ymin) + sign * middle)
        )
        slots.append(StrapSlot(centre, length, width, along_y))

    return tuple(slots), []


def slot_cutter(slot: StrapSlot, z0: float, z1: float) -> cq.Workplane:
    """A slot's box, through the floor."""

    x, y = slot.centre
    width_x = slot.width_mm if slot.along_y else slot.length_mm
    width_y = slot.length_mm if slot.along_y else slot.width_mm

    return (
        cq.Workplane("XY")
        .box(width_x, width_y, z1 - z0, centered=(True, True, False))
        .translate((x, y, z0))
    )


def strap_slots_clear(
    slots: tuple[StrapSlot, ...],
    points: tuple[Point, ...],
    clearance: float,
    wall: float,
    flange: float,
    least_wall: float,
    floor_z0: float,
    floor_z1: float,
) -> bool:
    """Each slot, grown by a minimum wall, lies wholly in the flange: off the nest's wall and inside the
    flange's edge."""

    slab = outline_prism(points, floor_z0, floor_z1, clearance + wall + flange)
    wall_body = outline_prism(points, floor_z0, floor_z1, clearance + wall)

    for slot in slots:
        grown = slot_cutter(
            StrapSlot(
                slot.centre,
                slot.length_mm + 2 * least_wall,
                slot.width_mm + 2 * least_wall,
                slot.along_y,
            ),
            floor_z0 + 0.25,
            floor_z1 - 0.25,
        )
        inside = grown.intersect(slab).val().Volume()  # type: ignore[union-attr]
        total = grown.val().Volume()  # type: ignore[union-attr]
        on_wall = grown.intersect(wall_body).val().Volume()  # type: ignore[union-attr]

        if inside < total - 1e-6 or on_wall > 1e-6:
            return False

    return True


def label_text(spec: NestSpec) -> str | None:
    """The label's text: the file's, or the nest's name when ``label`` is true."""

    return spec.label


def plan_label(
    spec: NestSpec,
    points: tuple[Point, ...],
    clearance: float,
    text_size: float,
    emboss: float,
    slots: tuple[StrapSlot, ...],
) -> tuple[Label | None, list[str]]:
    """Where the label goes, on the flange's strip beside the one the slots are not on, or why it
    cannot: the strip must be as wide as the text and the text as long as the nest's side allows."""

    text = label_text(spec)

    if text is None:
        return None, []

    needed = text_size + 2 * LABEL_MARGIN_MM

    if spec.flange_mm < needed:
        return None, [
            (
                f"a label of {text_size:g} mm text needs a flange at least {needed:g} mm "
                f"wide: nest.flange_mm is {spec.flange_mm:g}"
            )
        ]

    xmin, xmax, ymin, ymax = extents(points)
    slots_along_y = slots[0].along_y if slots else (xmax - xmin) >= (ymax - ymin)
    side = spec.wall_mm + clearance + spec.flange_mm / 2
    # The label goes on the side the slots are not on, along the nest's longer side.
    if slots_along_y:
        centre = (0.0, ymax + side)
        run = xmax - xmin
        rotated = False
    else:
        centre = (xmax + side, 0.0)
        run = ymax - ymin
        rotated = True

    width = CHARACTER_WIDTH * text_size * len(text)

    if width > run:
        return None, [
            (
                f"the label {text!r} is about {width:.0f} mm long at {text_size:g} mm text "
                f"and the nest's side is {run:.0f} mm: use shorter text"
            )
        ]

    return Label(text, centre, text_size, emboss, rotated), []


def label_solid(label: Label, z: float) -> cq.Workplane:
    """The label's text standing on the surface at ``z``."""

    text = (
        cq.Workplane("XY")
        .workplane(offset=z)
        .text(
            label.text,
            label.size_mm,
            label.emboss_mm,
            halign="center",
            valign="center",
        )
    )

    if label.rotated:
        text = text.rotate((0, 0, 0), (0, 0, 1), 90)

    return text.translate((label.centre[0], label.centre[1], 0.0))


@dataclass(frozen=True)
class Tab:
    """A lip tab: the stretch it is on, and the strain it is built to."""

    centre: Point
    outward: Point
    along: Point
    strain: float
    reach_mm: float
    deflection_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "centre_mm": [round(self.centre[0], 3), round(self.centre[1], 3)],
            "width_mm": TAB_WIDTH_MM,
            "reach_mm": round(self.reach_mm, 3),
            "deflection_mm": round(self.deflection_mm, 3),
            "strain_percent": round(100 * self.strain, 2),
            "strain_limit_percent": round(100 * FLEXURE_STRAIN_LIMIT, 2),
        }


def tab_strain(
    height_mm: float, wall_mm: float, overhang_mm: float, clearance: float
) -> tuple[float, float, float]:
    """The strain of a tab and its reach and deflection: the wall from its root to the hook's
    underside, bent out by the overhang and the clearance."""

    reach = height_mm - TAB_ROOT_MM + HOOK_GAP_MM
    deflection = overhang_mm + clearance
    flexure = flexure_for(deflection, reach, wall_mm)

    return flexure.strain, reach, deflection


def lip_errors(
    spec: NestSpec, height_mm: float, top_share: float, clearance: float
) -> list[str]:
    """Why the lip cannot be built, if it cannot: the part needs a flat top to hold, and a tab
    must be long enough not to strain past the limit."""

    if spec.lip_tabs == 0:
        return []

    errors = []

    if top_share < 0.1:
        errors.append(
            f"The part has no flat top for a lip to hold: only {top_share:.0%} of its shadow is "
            "flat at the top, and the least is 10%"
        )

    strain, reach, deflection = tab_strain(
        height_mm, spec.wall_mm, spec.lip_overhang_mm, clearance
    )

    if strain > FLEXURE_STRAIN_LIMIT:
        needed = math.sqrt(3 * spec.wall_mm * deflection / (2 * FLEXURE_STRAIN_LIMIT))
        errors.append(
            f"A lip tab on a part {height_mm:.1f} mm tall would strain {100 * strain:.1f}%, over the "
            f"{100 * FLEXURE_STRAIN_LIMIT:.1f}% limit: its reach is {reach:.1f} mm and needs "
            f"{needed:.1f} mm, or use a smaller overhang or a thinner wall"
        )

    return errors
