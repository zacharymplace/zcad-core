"""Build one printable enclosure around a row of Raspberry Pi 5 bays.

Every Pi sits portrait, its Ethernet and USB edge against the back wall and
its microSD end against the front wall. Its USB-C power and micro-HDMI edge
faces a service gap on its own left, so a cable plugged in there bends
toward the front wall and leaves through an opening at the end of the gap.
Because every bay repeats the same gap-then-slot pattern, any bay can hold a
Pi 5 now or later, and a bay can be an open shelf for an SSD, a switch, or a
power supply.

A Pi bay is built the same whether or not the Pi is fitted, so a
``reserved`` bay takes a Pi later with no reprint. The units also bolt
together: each unit's left wall carries two heat-set insert bosses and its
right wall two clearance holes, so a second, identical unit continues the
row past the printer's bed.

The frame: the outer bottom-left-front corner is the origin, +X runs along
the row, +Y runs front to back, +Z is up. The floor's top face is at
``z == floor_mm``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import cadquery as cq

from zcad_core.features.connector_cutouts import (
    ConnectorCutoutParameters,
    cut_connector_opening,
)
from zcad_core.features.enclosure_group_dividers import (
    Divider,
    DividerPlacement,
    build_divider,
    check_divider,
    require_divider_fits,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.pcb_mounts import PcbStandoffParameters, add_pcb_standoff
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import (
    FastenerSpec,
    RaspberryPi5Spec,
    get_fastener,
    get_raspberry_pi5,
)

BayKind = Literal["pi5", "reserved", "open"]
BAY_KINDS: tuple[BayKind, ...] = ("pi5", "reserved", "open")
OpeningWall = Literal["front", "back"]
OPENING_WALLS: tuple[OpeningWall, ...] = ("front", "back")
# Wall left between an opening and the shelf's ends, and under the lid.
_OPENING_RIM_MM = 1.0
# The card must clear the floor: its depth under the board plus this much.
_MINIMUM_SD_FLOOR_GAP_MM = 0.4

_FLOOR_EMBED_MM = 0.5
_BOSS_WALL_OVERLAP_MM = 0.5
_BOSS_CLEARANCE_MM = 1.0
_INTERFERENCE_TOLERANCE_MM3 = 1e-6
_STANDOFF_DIAMETER_MM = 6.0
_PI_STANDOFF_FASTENER = "M2.5"
_OPEN_BAY_STRIP_MM = 14.0
_CABLE_EXIT_HEIGHT_MM = 12.0
_SD_OPENING_HEIGHT_MM = 4.0
_SD_OPENING_MARGIN_MM = 2.0
_VENT_SLOTS = 5
_VENT_PITCH_MM = 5.0
_VENT_LENGTH_MM = 30.0
_VENT_WIDTH_MM = 2.4
_JOIN_HEIGHT_ABOVE_FLOOR_MM = 8.0
_JOIN_BOSS_REACH_MM = 8.0
_JOIN_Y_FRACTIONS = (0.65, 0.83)
_SCREW_LENGTHS_MM = (4, 5, 6, 8, 10, 12, 16, 20)


@dataclass(frozen=True)
class GroupDesign:
    """Sizes for the row of bays, in millimetres.

    ``standoff_height_mm`` and ``headroom_mm`` are the defaults for every
    bay; a :class:`Bay` overrides either for itself. ``headroom_mm`` is the
    room a bay's parts need above a Pi's PCB top: the default clears the
    tallest standard part (the 15.6 mm USB stack) and an Active Cooler with
    2 mm to spare; raise it for a HAT. For an ``open`` bay it is the height
    of the shelf's usable space. ``service_gap_mm`` is the space left of each
    Pi for its USB-C and micro-HDMI plugs. ``open_bay_width_mm`` is the width
    of an ``open`` bay's shelf.
    """

    wall_mm: float = 2.0
    floor_mm: float = 2.0
    lid_mm: float = 3.0
    fastener: str = "M3"
    boss_radial_wall_mm: float = 1.8
    standoff_height_mm: float = 4.0
    headroom_mm: float = 18.0
    service_gap_mm: float = 25.0
    end_margin_mm: float = 9.0
    front_clearance_mm: float = 4.0
    back_clearance_mm: float = 3.0
    slot_pad_mm: float = 0.25
    open_bay_width_mm: float = 40.0
    plug_margin_mm: float = 1.5
    vents: bool = True
    join_bolts: bool = True
    divider_mm: float = 2.0
    divider_clearance_mm: float = 0.75
    divider_notch_width_mm: float = 20.0
    divider_notch_height_mm: float = 10.0

    def validate(self) -> None:
        for name in (
            "wall_mm",
            "floor_mm",
            "lid_mm",
            "boss_radial_wall_mm",
            "standoff_height_mm",
            "headroom_mm",
            "service_gap_mm",
            "end_margin_mm",
            "open_bay_width_mm",
            "divider_mm",
            "divider_notch_width_mm",
            "divider_notch_height_mm",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.floor_mm <= _FLOOR_EMBED_MM:
            raise ValueError(f"floor_mm must exceed {_FLOOR_EMBED_MM} mm")

        for name in (
            "front_clearance_mm",
            "back_clearance_mm",
            "slot_pad_mm",
            "plug_margin_mm",
            "divider_clearance_mm",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class BayOpening:
    """A rectangular opening through an ``open`` bay's front or back wall.

    ``offset_mm`` runs along X from the middle of the bay's shelf, and
    ``bottom_mm`` is the opening's lower edge above the floor's top face. It
    must sit inside the shelf, leave a millimetre of wall to each side, and
    stop a millimetre short of the lid.
    """

    wall: OpeningWall
    width_mm: float
    height_mm: float
    offset_mm: float = 0.0
    bottom_mm: float = 0.0


@dataclass(frozen=True)
class Bay:
    """One bay, with heights that differ from the design's defaults.

    ``standoff_height_mm`` lifts a Pi off the floor, for a board mounted
    under it; ``headroom_mm`` is the room its parts need above the PCB, for a
    HAT. The lid is flat, so the box is as tall as its tallest bay needs and
    the other bays get spare room above their boards. ``openings`` cut
    through an ``open`` bay's walls, for the cables of whatever sits on its
    shelf; a Pi bay's openings are fixed by its ports. ``divider`` puts a
    wall on the boundary to this bay's left, just past the previous bay's
    header edge, so the first bay takes none.
    """

    kind: BayKind = "pi5"
    standoff_height_mm: float | None = None
    headroom_mm: float | None = None
    openings: tuple[BayOpening, ...] = ()
    divider: Divider | None = None


BayLike = BayKind | Bay


@dataclass(frozen=True)
class BayLayout:
    """Where one bay sits along X, its heights, and its centre when it holds
    a Pi. Heights are ``z`` in the enclosure frame; an ``open`` bay has no
    board, so its board faces sit at the floor."""

    index: int
    kind: BayKind
    gap_start_mm: float
    slot_start_mm: float
    slot_end_mm: float
    standoff_height_mm: float
    headroom_mm: float
    board_bottom_z_mm: float
    board_top_z_mm: float
    openings: tuple[BayOpening, ...] = ()
    divider: Divider | None = None
    # Where the divider's left face is, when there is one.
    divider_start_mm: float = 0.0

    @property
    def needed_top_z_mm(self) -> float:
        """The lowest lid underside this bay's parts fit under."""
        return self.board_top_z_mm + self.headroom_mm

    @property
    def center_x_mm(self) -> float:
        return (self.slot_start_mm + self.slot_end_mm) / 2

    @property
    def holds_pi(self) -> bool:
        return self.kind != "open"


@dataclass(frozen=True)
class GroupEnclosure:
    """The printable base and lid, and the space they were built around."""

    base: cq.Workplane
    lid: cq.Workplane
    design: GroupDesign
    fastener: FastenerSpec
    bays: tuple[BayLayout, ...]
    inner_size_mm: tuple[float, float, float]
    outer_size_mm: tuple[float, float, float]
    pi_center_y_mm: float
    lid_boss_positions: tuple[tuple[float, float], ...]
    join_positions: tuple[tuple[float, float], ...]
    # One envelope per Pi bay, keyed "bay-<n>", used for the fit checks and
    # for showing the parts in a review model.
    hardware: dict[str, cq.Shape]
    checks: dict[str, bool]
    recommended_lid_screw_mm: int
    recommended_join_screw_mm: int | None

    @property
    def cavity_top_z_mm(self) -> float:
        return self.design.floor_mm + self.inner_size_mm[2]

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    def room_above_board_mm(self, bay: BayLayout) -> float:
        """The space between a bay's board faces and the lid: at least the
        bay's headroom, and more where a taller bay set the box's height."""
        return self.cavity_top_z_mm - bay.board_top_z_mm


def build_group_enclosure(
    bays: Sequence[BayLike] = ("pi5", "pi5"),
    *,
    design: GroupDesign | None = None,
    pi: RaspberryPi5Spec | None = None,
) -> GroupEnclosure:
    """Build the base and lid for a row of bays.

    Raises ``ValueError`` for an unknown or empty bay list, a bay whose
    heights cannot work, or when a feature would cut or run into another.
    """

    design = design or GroupDesign()
    design.validate()
    pi = pi or get_raspberry_pi5()

    if not bays:
        raise ValueError("bays must list at least one bay")

    specs = tuple(_bay(bay) for bay in bays)

    fastener = get_fastener(design.fastener)
    insert_diameter = fastener.heat_set_insert_diameter_mm
    insert_depth = fastener.heat_set_insert_depth_mm

    if insert_diameter is None or insert_depth is None:
        raise ValueError(f"Fastener {fastener.identifier} has no heat-set insert")

    radius = insert_diameter / 2 + design.boss_radial_wall_mm
    layouts, inner_width = _layout(specs, design, pi)
    inner_depth = (
        design.front_clearance_mm + pi.board_length_mm + (design.back_clearance_mm)
    )
    cavity_top = max(layout.needed_top_z_mm for layout in layouts)
    inner_height = cavity_top - design.floor_mm
    _require_openings_under_lid(layouts, inner_height)
    wall = design.wall_mm
    pi_center_y = wall + design.front_clearance_mm + pi.board_length_mm / 2
    dividers = _dividers(
        layouts,
        design=design,
        pi=pi,
        inner_height=inner_height,
        inner_depth=inner_depth,
        pi_center_y=pi_center_y,
    )

    outer = (
        inner_width + 2 * wall,
        inner_depth + 2 * wall,
        inner_height + design.floor_mm,
    )
    base = _shell(outer, wall, design.floor_mm)

    corner_x = radius - _BOSS_WALL_OVERLAP_MM
    front_y = wall + corner_x
    back_y = wall + inner_depth - corner_x
    boss_columns = _boss_columns(layouts, radius, corner_x, wall, inner_width)
    boss_positions = tuple((x, y) for x in boss_columns for y in (front_y, back_y))
    base = base.union(
        _corner_fills(boss_positions, outer, wall, design.floor_mm, inner_height)
    )

    for x, y in boss_positions:
        base = add_heat_set_insert_boss(
            base,
            parameters=InsertBossParameters.from_fastener(
                fastener=fastener,
                x=x,
                y=y,
                base_height_mm=_FLOOR_EMBED_MM,
                base_z_mm=design.floor_mm - _FLOOR_EMBED_MM,
                boss_height_mm=inner_height,
                radial_wall_mm=design.boss_radial_wall_mm,
            ),
        )

    for divider, placement in dividers:
        base = base.union(build_divider(divider, placement))

    standoff_fastener = get_fastener(_PI_STANDOFF_FASTENER)
    hardware: dict[str, cq.Shape] = {}

    for layout in layouts:
        if not layout.holds_pi:
            continue

        center_x = wall + layout.center_x_mm

        for hx, hy in _hole_positions(pi):
            base = add_pcb_standoff(
                base,
                parameters=PcbStandoffParameters(
                    x=center_x + hx,
                    y=pi_center_y + hy,
                    base_height_mm=_FLOOR_EMBED_MM,
                    standoff_height_mm=layout.standoff_height_mm,
                    outer_diameter_mm=_STANDOFF_DIAMETER_MM,
                    hole_diameter_mm=standoff_fastener.tap_hole_mm,
                    base_z_mm=design.floor_mm - _FLOOR_EMBED_MM,
                ),
            )

        hardware[f"bay-{layout.index}"] = _pi_envelope(
            pi,
            center_x,
            pi_center_y,
            layout.board_bottom_z_mm,
            layout.board_top_z_mm,
        )

    base = _cut_pi_openings(
        base,
        layouts=layouts,
        design=design,
        pi=pi,
        radius=radius,
        wall=wall,
        pi_center_y=pi_center_y,
    )
    base = _cut_bay_openings(base, layouts, design)

    join_positions: tuple[tuple[float, float], ...] = ()

    if design.join_bolts:
        join_positions = tuple(
            (
                wall + inner_depth * fraction,
                design.floor_mm + _JOIN_HEIGHT_ABOVE_FLOOR_MM,
            )
            for fraction in _JOIN_Y_FRACTIONS
        )
        base = _add_join_features(
            base,
            positions=join_positions,
            fastener=fastener,
            design=design,
            outer_width=outer[0],
            radius=radius,
        )

    lid = _lid(
        outer,
        wall=wall,
        design=design,
        cavity_top=cavity_top,
        fastener=fastener,
        boss_positions=boss_positions,
        layouts=layouts,
        pi=pi,
        pi_center_y=pi_center_y,
    )

    checks = _checks(base, lid, hardware)
    lid_screw = _longest_screw(design.lid_mm + insert_depth)
    join_screw = _longest_screw(2 * wall + insert_depth) if design.join_bolts else None

    return GroupEnclosure(
        base=base,
        lid=lid,
        design=design,
        fastener=fastener,
        bays=layouts,
        inner_size_mm=(inner_width, inner_depth, inner_height),
        outer_size_mm=outer,
        pi_center_y_mm=pi_center_y,
        lid_boss_positions=boss_positions,
        join_positions=join_positions,
        hardware=hardware,
        checks=checks,
        recommended_lid_screw_mm=lid_screw,
        recommended_join_screw_mm=join_screw,
    )


def _bay(bay: BayLike) -> Bay:
    """A bay from its kind or itself, refusing an unknown kind."""

    resolved = Bay(kind=bay) if isinstance(bay, str) else bay

    if resolved.kind not in BAY_KINDS:
        raise ValueError(f"unknown bay kind '{resolved.kind}'; use one of {BAY_KINDS}")

    return resolved


def _layout(
    bays: tuple[Bay, ...], design: GroupDesign, pi: RaspberryPi5Spec
) -> tuple[tuple[BayLayout, ...], float]:
    """Each bay's gap, slot, and heights, and the cavity's inner width."""

    layouts: list[BayLayout] = []
    cursor = 0.0

    for index, bay in enumerate(bays):
        is_open = bay.kind == "open"
        divider_start = 0.0

        if bay.divider is not None:
            if index == 0:
                raise ValueError(
                    "bay 0: a divider stands to a bay's left, so the first bay "
                    "takes none"
                )

            check_divider(bay.divider, f"bay {index} ({bay.kind})")
            divider_start = cursor + design.divider_clearance_mm
            cursor = divider_start + design.divider_mm

        gap = _OPEN_BAY_STRIP_MM if is_open else design.service_gap_mm
        slot = (
            design.open_bay_width_mm
            if is_open
            else pi.board_width_mm + 2 * design.slot_pad_mm
        )
        standoff, headroom = _heights(bay, index, design, pi)
        board_bottom = design.floor_mm + standoff
        board_top = board_bottom + (0.0 if is_open else pi.board_thickness_mm)
        layouts.append(
            BayLayout(
                index=index,
                kind=bay.kind,
                gap_start_mm=cursor,
                slot_start_mm=cursor + gap,
                slot_end_mm=cursor + gap + slot,
                standoff_height_mm=standoff,
                headroom_mm=headroom,
                board_bottom_z_mm=board_bottom,
                board_top_z_mm=board_top,
                openings=_check_openings(bay, index, slot),
                divider=bay.divider,
                divider_start_mm=divider_start,
            )
        )
        cursor += gap + slot

    return tuple(layouts), cursor + design.end_margin_mm


def _check_openings(bay: Bay, index: int, slot_width: float) -> tuple[BayOpening, ...]:
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
            slot_width / 2 - _OPENING_RIM_MM
        ):
            raise ValueError(
                f"{label}: a {opening.width_mm:g} mm opening at offset "
                f"{opening.offset_mm:g} mm does not fit the {slot_width:g} mm shelf "
                f"with {_OPENING_RIM_MM:g} mm of wall to each side"
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
    bay: Bay, index: int, design: GroupDesign, pi: RaspberryPi5Spec
) -> tuple[float, float]:
    """A bay's standoff height and headroom, from its own or the design's."""

    label = f"bay {index} ({bay.kind})"
    headroom = bay.headroom_mm if bay.headroom_mm is not None else design.headroom_mm

    if headroom <= 0:
        raise ValueError(f"{label}: headroom_mm must be greater than zero")

    if bay.kind == "open":
        if bay.standoff_height_mm is not None:
            raise ValueError(f"{label}: an open bay has no board to stand off")

        return 0.0, headroom

    standoff = (
        bay.standoff_height_mm
        if bay.standoff_height_mm is not None
        else design.standoff_height_mm
    )
    minimum = pi.sd_card_depth_below_board_mm + _MINIMUM_SD_FLOOR_GAP_MM

    if standoff < minimum:
        raise ValueError(
            f"{label}: standoff_height_mm must be at least {minimum:.1f} mm "
            "so the microSD card clears the floor"
        )

    return standoff, headroom


def _boss_columns(
    layouts: tuple[BayLayout, ...],
    radius: float,
    corner_x: float,
    wall: float,
    inner_width: float,
) -> tuple[float, ...]:
    """Boss centres along X: the two end corners, and one at the start of
    each gap after the first, clear of the neighbouring Pi."""

    interior = [_gap_boss_x(layout, radius, wall) for layout in layouts[1:]]

    return (wall + corner_x, *interior, wall + inner_width - corner_x)


def _gap_boss_x(layout: BayLayout, radius: float, wall: float) -> float:
    """The boss at the start of a bay's gap. Behind a divider it sits against
    the divider, sunk into it like a corner boss into its walls, so the two
    fuse; otherwise it stands a millimetre clear of the neighbouring Pi."""

    inset = radius - _BOSS_WALL_OVERLAP_MM if layout.divider else radius + 1.0

    return wall + layout.gap_start_mm + inset


def _hole_positions(pi: RaspberryPi5Spec) -> tuple[tuple[float, float], ...]:
    """The Pi's mounting holes about its centre, portrait."""

    half_x = pi.mounting_hole_spacing_x_mm / 2
    half_y = pi.mounting_hole_spacing_y_mm / 2

    return tuple((sx * half_x, sy * half_y) for sx in (-1, 1) for sy in (-1, 1))


def _box(
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    z_range: tuple[float, float],
) -> cq.Solid:
    return cq.Solid.makeBox(
        x_range[1] - x_range[0],
        y_range[1] - y_range[0],
        z_range[1] - z_range[0],
        pnt=cq.Vector(x_range[0], y_range[0], z_range[0]),
    )


def _pi_envelope(
    pi: RaspberryPi5Spec,
    center_x: float,
    center_y: float,
    board_bottom: float,
    board_top: float,
) -> cq.Shape:
    """A Pi 5 as unioned boxes: board, ports, header, cooler, microSD."""

    half_x = pi.board_width_mm / 2
    half_y = pi.board_length_mm / 2
    boxes = [
        _box(
            (center_x - half_x, center_x + half_x),
            (center_y - half_y, center_y + half_y),
            (board_bottom, board_top),
        )
    ]

    for port in pi.ports:
        top = board_top + port.height_mm

        if port.edge == "positive_y":
            x_range = (
                center_x + port.center_mm - port.width_mm / 2,
                center_x + port.center_mm + port.width_mm / 2,
            )
            y_range = (
                center_y + half_y - port.depth_mm,
                center_y + half_y + port.overhang_mm,
            )
        elif port.edge == "negative_x":
            x_range = (
                center_x - half_x - port.overhang_mm,
                center_x - half_x + port.depth_mm,
            )
            y_range = (
                center_y + port.center_mm - port.width_mm / 2,
                center_y + port.center_mm + port.width_mm / 2,
            )
        else:
            raise ValueError(f"unsupported port edge '{port.edge}'")

        boxes.append(_box(x_range, y_range, (board_top, top)))

    header_x = center_x + pi.mounting_hole_spacing_x_mm / 2
    boxes.append(
        _box(
            (header_x - pi.header_width_mm / 2, header_x + pi.header_width_mm / 2),
            (
                center_y + pi.header_center_y_mm - pi.header_length_mm / 2,
                center_y + pi.header_center_y_mm + pi.header_length_mm / 2,
            ),
            (board_top, board_top + pi.header_height_mm),
        )
    )
    boxes.append(
        _box(
            (
                center_x - pi.cooler_width_mm / 2,
                center_x + pi.cooler_width_mm / 2,
            ),
            (
                center_y + pi.cooler_center_y_mm - pi.cooler_length_mm / 2,
                center_y + pi.cooler_center_y_mm + pi.cooler_length_mm / 2,
            ),
            (board_top, board_top + pi.cooler_height_mm),
        )
    )
    boxes.append(
        _box(
            (
                center_x - pi.sd_card_width_mm / 2,
                center_x + pi.sd_card_width_mm / 2,
            ),
            (center_y - half_y - pi.sd_card_overhang_mm, center_y - half_y + 15.0),
            (board_bottom - pi.sd_card_depth_below_board_mm, board_bottom),
        )
    )

    return _shape(cq.Workplane("XY").add(boxes).combine())


def _shell(
    outer: tuple[float, float, float], wall: float, floor: float
) -> cq.Workplane:
    """Floor and walls, open at the top."""

    body = cq.Workplane("XY").box(*outer, centered=False)
    cavity = (
        cq.Workplane("XY")
        .box(
            outer[0] - 2 * wall,
            outer[1] - 2 * wall,
            outer[2] - floor + 1.0,
            centered=False,
        )
        .translate((wall, wall, floor))
    )

    return body.cut(cavity)


def _corner_fills(
    positions: tuple[tuple[float, float], ...],
    outer: tuple[float, float, float],
    wall: float,
    floor: float,
    inner_height: float,
) -> cq.Workplane:
    """Fill the cavity corner behind each end boss, where a round boss
    meeting two walls would leave a narrow void the full cavity height."""

    fills = cq.Workplane("XY")
    left, right = wall, outer[0] - wall
    front, back = wall, outer[1] - wall
    middle_x, middle_y = outer[0] / 2, outer[1] / 2

    for x, y in positions:
        if x not in (min(p[0] for p in positions), max(p[0] for p in positions)):
            continue

        corner_x = left if x < middle_x else right
        corner_y = front if y < middle_y else back
        fills = fills.add(
            _box(
                (min(x, corner_x), max(x, corner_x)),
                (min(y, corner_y), max(y, corner_y)),
                (floor - _FLOOR_EMBED_MM, floor + inner_height),
            )
        )

    return fills.combine()


def _cut_pi_openings(
    base: cq.Workplane,
    *,
    layouts: tuple[BayLayout, ...],
    design: GroupDesign,
    pi: RaspberryPi5Spec,
    radius: float,
    wall: float,
    pi_center_y: float,
) -> cq.Workplane:
    """Back-wall openings for each Pi's Ethernet and USB plugs, a front-wall
    opening for its microSD card, and one at the end of its service gap for
    the power and HDMI cables."""

    depth = 2 * (wall + 0.5)
    margin = 2 * design.plug_margin_mm

    for layout in layouts:
        if not layout.holds_pi:
            continue

        center_x = wall + layout.center_x_mm

        for port in pi.ports:
            if port.edge != "positive_y":
                continue

            base = cut_connector_opening(
                base,
                parameters=ConnectorCutoutParameters(
                    edge="positive_y",
                    center_offset_mm=center_x + port.center_mm,
                    bottom_z_mm=layout.board_top_z_mm - 0.5,
                    width_mm=port.width_mm,
                    height_mm=port.height_mm,
                    width_clearance_mm=margin,
                    height_clearance_mm=design.plug_margin_mm,
                    cutter_depth_mm=depth,
                ),
            )

        base = cut_connector_opening(
            base,
            parameters=ConnectorCutoutParameters(
                edge="negative_y",
                center_offset_mm=center_x,
                bottom_z_mm=layout.board_bottom_z_mm - _SD_OPENING_MARGIN_MM,
                width_mm=pi.sd_card_width_mm,
                height_mm=_SD_OPENING_HEIGHT_MM,
                width_clearance_mm=_SD_OPENING_MARGIN_MM,
                height_clearance_mm=0.0,
                cutter_depth_mm=depth,
            ),
        )

        # The gap's front opening starts past the boss at the gap's start
        # and stops a millimetre short of the Pi's slot.
        start = _gap_boss_x(layout, radius, wall) + radius + _BOSS_CLEARANCE_MM
        end = wall + layout.slot_start_mm - 1.0
        width = end - start

        if width < 6.0:
            raise ValueError(
                "service_gap_mm leaves under 6 mm for the power and HDMI cables"
            )

        base = cut_connector_opening(
            base,
            parameters=ConnectorCutoutParameters(
                edge="negative_y",
                center_offset_mm=(start + end) / 2,
                bottom_z_mm=layout.board_top_z_mm - 1.0,
                width_mm=width,
                height_mm=_CABLE_EXIT_HEIGHT_MM,
                width_clearance_mm=0.0,
                height_clearance_mm=0.0,
                cutter_depth_mm=depth,
            ),
        )

    return base


def _dividers(
    layouts: tuple[BayLayout, ...],
    *,
    design: GroupDesign,
    pi: RaspberryPi5Spec,
    inner_height: float,
    inner_depth: float,
    pi_center_y: float,
) -> list[tuple[Divider, DividerPlacement]]:
    """Each bay's divider and where it stands, refused if it does not fit.

    A divider stands just past the previous bay's header edge, so its notch
    is centred on that bay's header and rises from that bay's board.
    """

    placed: list[tuple[Divider, DividerPlacement]] = []

    for layout in layouts:
        if layout.divider is None:
            continue

        left = layouts[layout.index - 1]
        notch_y = pi_center_y + (pi.header_center_y_mm if left.holds_pi else 0.0)
        notch_bottom = left.board_top_z_mm if left.holds_pi else design.floor_mm + 2.0
        placement = DividerPlacement(
            x_start_mm=design.wall_mm + layout.divider_start_mm,
            thickness_mm=design.divider_mm,
            front_y_mm=design.wall_mm,
            back_y_mm=design.wall_mm + inner_depth,
            floor_top_z_mm=design.floor_mm,
            inner_height_mm=inner_height,
            notch_center_y_mm=notch_y,
            notch_bottom_z_mm=notch_bottom,
            notch_width_mm=design.divider_notch_width_mm,
            notch_height_mm=design.divider_notch_height_mm,
        )
        require_divider_fits(
            layout.divider, placement, f"bay {layout.index} ({layout.kind})"
        )
        placed.append((layout.divider, placement))

    return placed


def _require_openings_under_lid(
    layouts: tuple[BayLayout, ...], inner_height: float
) -> None:
    """Refuse an opening that would reach the lid's seat, and say how to
    make room: the box is as tall as its tallest bay needs."""

    for layout in layouts:
        for opening in layout.openings:
            top = opening.bottom_mm + opening.height_mm

            if top > inner_height - _OPENING_RIM_MM:
                raise ValueError(
                    f"bay {layout.index}: the opening reaches {top:g} mm but the "
                    f"box is {inner_height:g} mm tall inside and needs "
                    f"{_OPENING_RIM_MM:g} mm of wall under the lid; lower the "
                    "opening or raise headroom_mm on a bay"
                )


def _cut_bay_openings(
    base: cq.Workplane, layouts: tuple[BayLayout, ...], design: GroupDesign
) -> cq.Workplane:
    """The front and back wall openings an ``open`` bay asks for."""

    depth = 2 * (design.wall_mm + 0.5)

    for layout in layouts:
        for opening in layout.openings:
            base = cut_connector_opening(
                base,
                parameters=ConnectorCutoutParameters(
                    edge="negative_y" if opening.wall == "front" else "positive_y",
                    center_offset_mm=(
                        design.wall_mm + layout.center_x_mm + opening.offset_mm
                    ),
                    bottom_z_mm=design.floor_mm + opening.bottom_mm,
                    width_mm=opening.width_mm,
                    height_mm=opening.height_mm,
                    width_clearance_mm=0.0,
                    height_clearance_mm=0.0,
                    cutter_depth_mm=depth,
                ),
            )

    return base


def _add_join_features(
    base: cq.Workplane,
    *,
    positions: tuple[tuple[float, float], ...],
    fastener: FastenerSpec,
    design: GroupDesign,
    outer_width: float,
    radius: float,
) -> cq.Workplane:
    """Insert bosses in the left wall, clearance holes in the right.

    A second unit continues the row: its left wall meets this unit's right
    wall, and a screw passes through the hole in one wall and the other into
    the insert. Each insert is pressed in from the left wall's outer face.
    """

    wall = design.wall_mm
    insert_diameter = fastener.heat_set_insert_diameter_mm or 0.0
    insert_depth = fastener.heat_set_insert_depth_mm or 0.0

    if wall + _JOIN_BOSS_REACH_MM <= insert_depth:
        raise ValueError("wall_mm leaves no room for the join insert")

    for y, z in positions:
        block = _box(
            (wall - 0.5, wall + _JOIN_BOSS_REACH_MM),
            (y - radius, y + radius),
            (design.floor_mm - _FLOOR_EMBED_MM, z),
        )
        cylinder = (
            cq.Workplane("YZ")
            .center(y, z)
            .circle(radius)
            .extrude(wall + _JOIN_BOSS_REACH_MM)
        )
        base = base.union(cylinder).union(block)
        pilot = (
            cq.Workplane("YZ")
            .center(y, z)
            .circle(fastener.tap_hole_mm / 2)
            .extrude(wall + _JOIN_BOSS_REACH_MM)
        )
        pocket = (
            cq.Workplane("YZ")
            .center(y, z)
            .circle(insert_diameter / 2)
            .extrude(insert_depth)
        )
        base = base.cut(pilot).cut(pocket)
        clearance = (
            cq.Workplane("YZ")
            .workplane(offset=outer_width - wall - 0.5)
            .center(y, z)
            .circle(fastener.clearance_hole_mm / 2)
            .extrude(wall + 1.0)
        )
        base = base.cut(clearance)

    return base


def _lid(
    outer: tuple[float, float, float],
    *,
    wall: float,
    design: GroupDesign,
    cavity_top: float,
    fastener: FastenerSpec,
    boss_positions: tuple[tuple[float, float], ...],
    layouts: tuple[BayLayout, ...],
    pi: RaspberryPi5Spec,
    pi_center_y: float,
) -> cq.Workplane:
    """A plate over the walls, a clearance hole over each boss, and vent
    slots over each Pi's SoC and cooler."""

    lid = (
        cq.Workplane("XY")
        .box(outer[0], outer[1], design.lid_mm, centered=False)
        .translate((0, 0, cavity_top))
    )
    holes = (
        cq.Workplane("XY")
        .pushPoints(list(boss_positions))
        .circle(fastener.clearance_hole_mm / 2)
        .extrude(design.lid_mm + 2.0)
        .translate((0, 0, cavity_top - 1.0))
    )
    lid = lid.cut(holes)

    if not design.vents:
        return lid

    for layout in layouts:
        if not layout.holds_pi:
            continue

        center_x = wall + layout.center_x_mm
        soc_y = pi_center_y + pi.cooler_center_y_mm

        for index in range(_VENT_SLOTS):
            offset = (index - (_VENT_SLOTS - 1) / 2) * _VENT_PITCH_MM
            lid = lid.cut(
                _box(
                    (
                        center_x - _VENT_LENGTH_MM / 2,
                        center_x + _VENT_LENGTH_MM / 2,
                    ),
                    (
                        soc_y + offset - _VENT_WIDTH_MM / 2,
                        soc_y + offset + _VENT_WIDTH_MM / 2,
                    ),
                    (cavity_top - 1.0, cavity_top + design.lid_mm + 1.0),
                )
            )

    return lid


def _shape(model: cq.Workplane) -> cq.Shape:
    shapes = [value for value in model.vals() if isinstance(value, cq.Shape)]

    if not shapes:
        raise ValueError("Expected geometry on the workplane")

    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def _checks(
    base: cq.Workplane, lid: cq.Workplane, hardware: dict[str, cq.Shape]
) -> dict[str, bool]:
    base_shape, lid_shape = _shape(base), _shape(lid)

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
