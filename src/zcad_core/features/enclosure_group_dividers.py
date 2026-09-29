"""Dividers between the bays of a Pi 5 group enclosure.

A divider is a wall across the enclosure, front to back, just clear of the
40-pin header edge of the bay to its right. It can run the full height to the lid or stop low, and it
can carry vents, a cable pass-through notch, and slots for zip ties.

This module works in plain numbers: it knows nothing of bays, only where a
divider stands and what it is asked to carry. The frame is the enclosure's:
+X along the row, +Y front to back, +Z up.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

# Wall left between a feature and the divider's top, and to its front and back.
RIM_MM = 1.0
_VENT_SLOT_WIDTH_MM = 2.4
_VENT_PITCH_MM = 6.0
_VENT_ZONE_MM = 7.0
_VENT_TOP_MARGIN_MM = 3.0
_VENT_END_MARGIN_MM = 12.0
_VENT_KEEPOUT_MM = 3.0
_TIE_SLOT_LENGTH_MM = 4.2
_TIE_SLOT_HEIGHT_MM = 2.0
_TIE_ROW_BOTTOMS_MM = (3.0, 9.0)
_TIE_PAIR_SPAN_MM = 10.0
_TIE_DEPTH_FRACTION = 0.75
_EMBED_MM = 0.5


@dataclass(frozen=True)
class Divider:
    """A divider on the boundary to the left of a bay.

    ``height_mm`` is how far it rises above the floor; left unset it runs to
    the lid and holds the lid up. A low divider is open at the top, for
    separating cables. ``vents`` cuts vertical slots near the top of a
    full-height divider, so air passes between bays but line of sight does
    not. ``notch`` cuts a pass-through at the right bay's header, for a ribbon
    or jumper wires. ``tie_slots`` cuts two rows of slot pairs for zip ties,
    to strap what sits beside it to the divider.
    """

    height_mm: float | None = None
    vents: bool = False
    notch: bool = False
    tie_slots: bool = False

    @property
    def full_height(self) -> bool:
        return self.height_mm is None


@dataclass(frozen=True)
class DividerPlacement:
    """Where one divider stands, in the enclosure frame.

    ``front_y_mm`` and ``back_y_mm`` are the inner faces of the front and
    back walls; the divider is embedded half a millimetre into each so the
    parts fuse. ``notch_center_y_mm`` and ``notch_bottom_z_mm`` place the
    pass-through, and ``notch_width_mm`` and ``notch_height_mm`` size it.
    """

    x_start_mm: float
    thickness_mm: float
    front_y_mm: float
    back_y_mm: float
    floor_top_z_mm: float
    inner_height_mm: float
    notch_center_y_mm: float
    notch_bottom_z_mm: float
    notch_width_mm: float
    notch_height_mm: float

    @property
    def x_end_mm(self) -> float:
        return self.x_start_mm + self.thickness_mm


# A cut through the divider: (y_min, y_max, z_min, z_max), in the frame.
Cut = tuple[float, float, float, float]


def check_divider(divider: Divider, label: str) -> None:
    """Refuse a divider that asks for something it cannot carry."""

    if divider.height_mm is not None and divider.height_mm <= 0:
        raise ValueError(f"{label}: a divider's height_mm must be greater than zero")

    if divider.vents and not divider.full_height:
        raise ValueError(
            f"{label}: a low divider is open at the top; vents are for a "
            "full-height divider"
        )


def divider_top_z(divider: Divider, placement: DividerPlacement) -> float:
    """The divider's top face: the lid seat, or its own height above the floor."""

    height = (
        placement.inner_height_mm if divider.height_mm is None else divider.height_mm
    )

    return placement.floor_top_z_mm + height


def require_divider_fits(
    divider: Divider, placement: DividerPlacement, label: str
) -> None:
    """Refuse a divider taller than the box, or one whose notch or tie slots
    would not leave a millimetre of wall above them."""

    if divider.height_mm is not None and divider.height_mm >= placement.inner_height_mm:
        raise ValueError(
            f"{label}: a {divider.height_mm:g} mm divider is as tall as the "
            f"{placement.inner_height_mm:g} mm box; leave height_mm unset for "
            "a full-height one"
        )

    top = divider_top_z(divider, placement)

    if divider.notch and (
        placement.notch_bottom_z_mm + placement.notch_height_mm > top - RIM_MM
    ):
        raise ValueError(
            f"{label}: the divider's notch reaches "
            f"{placement.notch_bottom_z_mm + placement.notch_height_mm:g} mm and "
            f"the divider tops out at {top:g} mm; raise the divider or lower the "
            "notch"
        )

    if divider.tie_slots:
        needed = (
            placement.floor_top_z_mm
            + _TIE_ROW_BOTTOMS_MM[-1]
            + _TIE_SLOT_HEIGHT_MM
            + RIM_MM
        )

        if top < needed:
            raise ValueError(
                f"{label}: tie slots need a divider {needed - placement.floor_top_z_mm:g}"
                " mm tall or more"
            )

    if divider.vents:
        vent_bottom = top - _VENT_TOP_MARGIN_MM - _VENT_ZONE_MM

        if vent_bottom < placement.floor_top_z_mm + RIM_MM:
            raise ValueError(f"{label}: the box is too short inside for vents")


def notch_cut(placement: DividerPlacement) -> Cut:
    """The pass-through, clipped to leave a millimetre of wall front and back."""

    half = placement.notch_width_mm / 2
    front = max(placement.notch_center_y_mm - half, placement.front_y_mm + RIM_MM)
    back = min(placement.notch_center_y_mm + half, placement.back_y_mm - RIM_MM)

    return (
        front,
        back,
        placement.notch_bottom_z_mm,
        placement.notch_bottom_z_mm + placement.notch_height_mm,
    )


def tie_cuts(placement: DividerPlacement) -> list[Cut]:
    """Two rows of slot pairs, either side of a point a way back along the
    divider, for a zip tie to pass through and around what it holds."""

    center = placement.front_y_mm + _TIE_DEPTH_FRACTION * (
        placement.back_y_mm - placement.front_y_mm
    )
    cuts: list[Cut] = []

    for bottom in _TIE_ROW_BOTTOMS_MM:
        for side in (-1, 1):
            y = center + side * _TIE_PAIR_SPAN_MM
            z = placement.floor_top_z_mm + bottom
            cuts.append(
                (
                    y - _TIE_SLOT_LENGTH_MM / 2,
                    y + _TIE_SLOT_LENGTH_MM / 2,
                    z,
                    z + _TIE_SLOT_HEIGHT_MM,
                )
            )

    return cuts


def vent_cuts(
    divider: Divider, placement: DividerPlacement, others: list[Cut]
) -> list[Cut]:
    """Vertical slots across the divider's top, leaving out any that would
    come within a few millimetres of the notch or a tie slot."""

    top = divider_top_z(divider, placement)
    bottom = top - _VENT_TOP_MARGIN_MM - _VENT_ZONE_MM
    y = placement.front_y_mm + _VENT_END_MARGIN_MM
    limit = placement.back_y_mm - _VENT_END_MARGIN_MM
    cuts: list[Cut] = []

    while y <= limit:
        slot = (
            y - _VENT_SLOT_WIDTH_MM / 2,
            y + _VENT_SLOT_WIDTH_MM / 2,
            bottom,
            bottom + _VENT_ZONE_MM,
        )

        if not any(_near(slot, other, _VENT_KEEPOUT_MM) for other in others):
            cuts.append(slot)

        y += _VENT_PITCH_MM

    return cuts


def _near(first: Cut, second: Cut, margin: float) -> bool:
    return (
        first[0] < second[1] + margin
        and second[0] < first[1] + margin
        and first[2] < second[3] + margin
        and second[2] < first[3] + margin
    )


def divider_cuts(divider: Divider, placement: DividerPlacement) -> list[Cut]:
    """Every cut a divider carries."""

    cuts: list[Cut] = []

    if divider.notch:
        cuts.append(notch_cut(placement))

    if divider.tie_slots:
        cuts.extend(tie_cuts(placement))

    if divider.vents:
        cuts.extend(vent_cuts(divider, placement, list(cuts)))

    return cuts


def build_divider(divider: Divider, placement: DividerPlacement) -> cq.Workplane:
    """The divider as a solid: a wall from the floor to its top, embedded a
    little into the floor and the front and back walls, less its cuts."""

    top = divider_top_z(divider, placement)
    floor = placement.floor_top_z_mm
    y_start = placement.front_y_mm - _EMBED_MM
    y_end = placement.back_y_mm + _EMBED_MM
    wall = cq.Workplane("XY").add(
        cq.Solid.makeBox(
            placement.thickness_mm,
            y_end - y_start,
            top - (floor - _EMBED_MM),
            pnt=cq.Vector(placement.x_start_mm, y_start, floor - _EMBED_MM),
        )
    )

    for y_min, y_max, z_min, z_max in divider_cuts(divider, placement):
        wall = wall.cut(
            cq.Workplane("XY").add(
                cq.Solid.makeBox(
                    placement.thickness_mm + 2 * _EMBED_MM,
                    y_max - y_min,
                    z_max - z_min,
                    pnt=cq.Vector(placement.x_start_mm - _EMBED_MM, y_min, z_min),
                )
            )
        )

    return wall
