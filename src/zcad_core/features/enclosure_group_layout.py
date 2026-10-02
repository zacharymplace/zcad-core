"""Where each bay of a Pi 5 group enclosure sits along the row, and how tall.

Turns the bays a caller asks for into :class:`BayLayout` records, refusing a
bay whose heights, openings, or divider cannot work."""

from __future__ import annotations

from itertools import pairwise

from zcad_core.features.enclosure_group_dividers import check_divider
from zcad_core.features.enclosure_group_model import (
    BAY_KINDS,
    OPENING_RIM_MM,
    OPENING_WALLS,
    Bay,
    BayLayout,
    BayLike,
    BayOpening,
    GroupDesign,
)
from zcad_core.features.enclosure_group_modules import (
    ALIGNMENTS,
    HEADROOM_MARGIN_MM,
    ROTATIONS,
    BayModule,
)
from zcad_core.hardware import RaspberryPi5Spec

# The card must clear the floor: its depth under the board plus this much.
_MINIMUM_SD_FLOOR_GAP_MM = 0.4
BOSS_WALL_OVERLAP_MM = 0.5
_OPEN_BAY_STRIP_MM = 14.0


def resolve_bay(bay: BayLike) -> Bay:
    """A bay from its kind or itself, refusing an unknown kind."""

    resolved = Bay(kind=bay) if isinstance(bay, str) else bay

    if resolved.kind not in BAY_KINDS:
        raise ValueError(f"unknown bay kind '{resolved.kind}'; use one of {BAY_KINDS}")

    _check_board_settings(resolved)

    return resolved


def _check_cradle_divider(bay: Bay, module: BayModule | None, index: int) -> None:
    """A cradle's clips stand outside the board's side edges, where a divider
    stands, so a cradle bay takes none."""

    if module is not None and module.support == "cradle" and bay.divider is not None:
        raise ValueError(
            f"bay {index} (board): a cradle bay's side clips would meet its "
            "divider: move the divider to the bay beside it, or give the board "
            "standoffs"
        )


def _check_board_settings(bay: Bay) -> None:
    """A board bay needs a board; no other bay takes one or its settings."""

    if bay.kind == "board":
        if bay.board is None:
            raise ValueError("a board bay needs a board file: board:file=PATH")

        if bay.rotate is not None and bay.rotate not in ROTATIONS:
            raise ValueError(f"rotate must be one of {ROTATIONS}, not {bay.rotate!r}")

        if bay.align not in ALIGNMENTS:
            raise ValueError(f"align must be one of {ALIGNMENTS}, not {bay.align!r}")

        return

    if bay.board is not None or bay.rotate is not None or bay.screw is not None:
        raise ValueError(
            f"a {bay.kind} bay takes no board, rotate or screw: only a board bay does"
        )


def layout_bays(
    bays: tuple[Bay, ...],
    design: GroupDesign,
    modules: tuple[BayModule | None, ...],
    inner_depth: float,
) -> tuple[tuple[BayLayout, ...], float]:
    """Each bay's gap, slot, and heights, and the cavity's inner width.

    ``modules`` holds each bay's board, or ``None`` for an open shelf, and
    ``inner_depth`` is how deep the row is, which sets where each board sits front
    to back."""

    layouts: list[BayLayout] = []
    # The first bay's header faces the left wall across the end margin.
    cursor = design.end_margin_mm

    for index, (bay, module) in enumerate(zip(bays, modules, strict=True)):
        divider_start = 0.0
        _check_cradle_divider(bay, module, index)

        if bay.divider is not None:
            if index == 0:
                raise ValueError(
                    "bay 0: a divider stands to a bay's left, so the first bay "
                    "takes none"
                )

            # It closes the previous bay's gap and stands clear of this
            # bay's header.
            check_divider(bay.divider, f"bay {index} ({bay.kind})")
            divider_start = cursor
            cursor = divider_start + design.divider_mm + design.divider_clearance_mm

        left = 0.0

        if module is None:
            gap, slot = _OPEN_BAY_STRIP_MM, design.open_bay_width_mm
        else:
            # A Pi's USB-C and micro-HDMI face right; a board's connectors facing
            # a side take the same service space, and the board's left one is
            # before its slot.
            gap = (
                design.service_gap_mm
                if module.is_pi or module.faces_right
                else design.board_gap_mm
            )
            left = design.service_gap_mm if module.faces_left else 0.0
            slot = module.width_mm + 2 * design.slot_pad_mm
            cursor += left

        standoff, headroom = _heights(bay, index, design, module)
        board_bottom = design.floor_mm + standoff
        board_top = board_bottom + (0.0 if module is None else module.thickness_mm)
        layouts.append(
            BayLayout(
                index=index,
                kind=bay.kind,
                slot_start_mm=cursor,
                slot_end_mm=cursor + slot,
                gap_start_mm=cursor + slot,
                gap_end_mm=cursor + slot + gap,
                standoff_height_mm=standoff,
                headroom_mm=headroom,
                board_bottom_z_mm=board_bottom,
                board_top_z_mm=board_top,
                openings=check_openings(bay, index, slot),
                divider=bay.divider,
                divider_start_mm=divider_start,
                center_y_mm=_center_y(bay, module, design, inner_depth),
                left_space_mm=left,
            )
        )
        cursor += slot + gap

    # The last bay's service gap runs to the right wall.
    return tuple(layouts), cursor


def _center_y(
    bay: Bay, module: BayModule | None, design: GroupDesign, inner_depth: float
) -> float:
    """Where a bay's board is centred front to back: against the back wall unless
    the bay says front or centre, which for the deepest board is the same place."""

    wall = design.wall_mm
    front = wall + design.front_clearance_mm
    back = wall + inner_depth - design.back_clearance_mm

    if module is None:
        return (front + back) / 2

    if bay.align == "front":
        return front + module.depth_mm / 2

    if bay.align == "center":
        return (front + back) / 2

    return back - module.depth_mm / 2


def check_openings(bay: Bay, index: int, slot_width: float) -> tuple[BayOpening, ...]:
    """A bay's openings, refusing any that cannot be cut where asked."""

    label = f"bay {index} ({bay.kind})"

    if bay.openings and bay.kind != "open":
        raise ValueError(
            f"{label}: only an open bay takes openings; a Pi bay's are set by its ports"
        )

    for opening in bay.openings:
        if opening.wall not in OPENING_WALLS:
            raise ValueError(f"{label}: opening wall must be one of {OPENING_WALLS}")

        if opening.width_mm <= 0 or opening.height_mm <= 0:
            raise ValueError(f"{label}: an opening needs a width and height above zero")

        if opening.bottom_mm < 0:
            raise ValueError(f"{label}: an opening cannot start below the floor")

        if abs(opening.offset_mm) + opening.width_mm / 2 > (
            slot_width / 2 - OPENING_RIM_MM
        ):
            raise ValueError(
                f"{label}: a {opening.width_mm:g} mm opening at offset "
                f"{opening.offset_mm:g} mm does not fit the {slot_width:g} mm shelf "
                f"with {OPENING_RIM_MM:g} mm of wall to each side"
            )

    for i, first in enumerate(bay.openings):
        for second in bay.openings[i + 1 :]:
            if first.wall == second.wall and _overlap(first, second):
                raise ValueError(
                    f"{label}: two openings in the {first.wall} wall overlap"
                )

    return bay.openings


def _overlap(first: BayOpening, second: BayOpening) -> bool:
    def spans(opening: BayOpening) -> tuple[float, float, float, float]:
        return (
            opening.offset_mm - opening.width_mm / 2,
            opening.offset_mm + opening.width_mm / 2,
            opening.bottom_mm,
            opening.bottom_mm + opening.height_mm,
        )

    a, b = spans(first), spans(second)

    return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]


def _heights(
    bay: Bay, index: int, design: GroupDesign, module: BayModule | None
) -> tuple[float, float]:
    """A bay's standoff height and headroom, from its own or the design's."""

    label = f"bay {index} ({bay.kind})"
    headroom = bay.headroom_mm if bay.headroom_mm is not None else design.headroom_mm

    if headroom <= 0:
        raise ValueError(f"{label}: headroom_mm must be greater than zero")

    if module is None:
        if bay.standoff_height_mm is not None:
            raise ValueError(f"{label}: an open bay has no board to stand off")

        return 0.0, headroom

    if bay.standoff_height_mm is not None:
        standoff = bay.standoff_height_mm
    elif module.default_standoff_mm is not None:
        standoff = module.default_standoff_mm
    else:
        standoff = design.standoff_height_mm

    minimum = module.minimum_standoff_mm

    if standoff < minimum:
        reason = (
            "the microSD card clears the floor"
            if module.is_pi
            else "the parts under the board clear the floor"
        )
        raise ValueError(
            f"{label}: standoff_height_mm must be at least {minimum:.1f} mm so {reason}"
        )

    if not module.is_pi and headroom < module.tallest_mm + HEADROOM_MARGIN_MM:
        raise ValueError(
            f"{label}: headroom_mm is {headroom:g} mm but the board's tallest part "
            f"stands {module.tallest_mm:g} mm above it and needs "
            f"{HEADROOM_MARGIN_MM:g} mm more: raise headroom"
        )

    return standoff, headroom


def boss_column_xs(
    layouts: tuple[BayLayout, ...],
    radius: float,
    corner_x: float,
    wall: float,
    inner_width: float,
) -> tuple[float, ...]:
    """Boss centres along X: the two end corners, and one at the end of each
    gap before the last, clear of the next Pi. Column ``i + 1`` closes bay
    ``i``'s gap."""

    interior = [
        gap_boss_x(layout, following, radius, wall)
        for layout, following in pairwise(layouts)
    ]

    return (wall + corner_x, *interior, wall + inner_width - corner_x)


def gap_boss_x(
    layout: BayLayout, following: BayLayout, radius: float, wall: float
) -> float:
    """The boss at the end of a bay's gap. Against the next bay's divider it
    is sunk into it like a corner boss into its walls, so the two fuse;
    otherwise it stands a millimetre clear of the next Pi."""

    inset = radius - BOSS_WALL_OVERLAP_MM if following.divider else radius + 1.0

    return wall + layout.gap_end_mm - inset


def hole_positions(pi: RaspberryPi5Spec) -> tuple[tuple[float, float], ...]:
    """The Pi's mounting holes about its board centre, portrait; the pattern
    sits toward the microSD end, not centred."""

    return pi.mounting_hole_positions_mm
