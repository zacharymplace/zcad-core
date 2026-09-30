"""Build one printable enclosure around a row of Raspberry Pi 5 bays.

Every Pi sits portrait, its Ethernet and USB edge against the back wall and
its microSD end against the front wall. Its USB-C power and micro-HDMI edge
faces a service gap on its own right, so a cable plugged in there bends
toward the front wall and leaves through an opening at the end of the gap;
its 40-pin header faces left. Because every bay repeats the same
slot-then-gap pattern, any bay can hold a Pi 5 now or later, and a bay can
be an open shelf for an SSD, a switch, or a power supply.

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

import cadquery as cq

from zcad_core.features.enclosure_group_dividers import (
    Divider,
    DividerPlacement,
    build_divider,
    require_divider_fits,
)
from zcad_core.features.enclosure_group_envelope import (
    make_box,
    pi_envelope,
    pi_parts,
    single_shape,
)
from zcad_core.features.enclosure_group_layout import (
    BOSS_WALL_OVERLAP_MM,
    boss_column_xs,
    hole_positions,
    layout_bays,
    resolve_bay,
)
from zcad_core.features.enclosure_group_model import (
    BAY_KINDS,
    FLOOR_EMBED_MM,
    OPENING_WALLS,
    Bay,
    BayKind,
    BayLayout,
    BayLike,
    BayOpening,
    GroupDesign,
    GroupEnclosure,
    OpeningWall,
)
from zcad_core.features.enclosure_group_openings import (
    cut_bay_openings,
    cut_pi_openings,
    require_openings_under_lid,
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

__all__ = [
    "BAY_KINDS",
    "OPENING_WALLS",
    "Bay",
    "BayKind",
    "BayLayout",
    "BayLike",
    "BayOpening",
    "GroupDesign",
    "GroupEnclosure",
    "OpeningWall",
    "build_group_enclosure",
    "print_oriented_parts",
]

_INTERFERENCE_TOLERANCE_MM3 = 1e-6
_STANDOFF_DIAMETER_MM = 6.0
_PI_STANDOFF_FASTENER = "M2.5"
_VENT_SLOTS = 5
_VENT_PITCH_MM = 5.0
_VENT_LENGTH_MM = 30.0
_VENT_WIDTH_MM = 2.4
_JOIN_HEIGHT_ABOVE_FLOOR_MM = 8.0
_JOIN_BOSS_REACH_MM = 8.0
_JOIN_Y_FRACTIONS = (0.65, 0.83)
_SCREW_LENGTHS_MM = (4, 5, 6, 8, 10, 12, 16, 20)


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

    specs = tuple(resolve_bay(bay) for bay in bays)

    fastener = get_fastener(design.fastener)
    insert_diameter = fastener.heat_set_insert_diameter_mm
    insert_depth = fastener.heat_set_insert_depth_mm

    if insert_diameter is None or insert_depth is None:
        raise ValueError(f"Fastener {fastener.identifier} has no heat-set insert")

    radius = insert_diameter / 2 + design.boss_radial_wall_mm
    layouts, inner_width = layout_bays(specs, design, pi)
    inner_depth = (
        design.front_clearance_mm + pi.board_length_mm + (design.back_clearance_mm)
    )
    cavity_top = max(layout.needed_top_z_mm for layout in layouts)
    inner_height = cavity_top - design.floor_mm
    require_openings_under_lid(layouts, inner_height)
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

    corner_x = radius - BOSS_WALL_OVERLAP_MM
    front_y = wall + corner_x
    back_y = wall + inner_depth - corner_x
    boss_columns = boss_column_xs(layouts, radius, corner_x, wall, inner_width)
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
                base_height_mm=FLOOR_EMBED_MM,
                base_z_mm=design.floor_mm - FLOOR_EMBED_MM,
                boss_height_mm=inner_height,
                radial_wall_mm=design.boss_radial_wall_mm,
            ),
        )

    for divider, placement in dividers:
        base = base.union(build_divider(divider, placement))

    standoff_fastener = get_fastener(_PI_STANDOFF_FASTENER)
    hardware: dict[str, cq.Shape] = {}
    parts: dict[str, dict[str, cq.Shape]] = {}

    for layout in layouts:
        if not layout.holds_pi:
            continue

        center_x = wall + layout.center_x_mm

        for hx, hy in hole_positions(pi):
            base = add_pcb_standoff(
                base,
                parameters=PcbStandoffParameters(
                    x=center_x + hx,
                    y=pi_center_y + hy,
                    base_height_mm=FLOOR_EMBED_MM,
                    standoff_height_mm=layout.standoff_height_mm,
                    outer_diameter_mm=_STANDOFF_DIAMETER_MM,
                    hole_diameter_mm=standoff_fastener.tap_hole_mm,
                    base_z_mm=design.floor_mm - FLOOR_EMBED_MM,
                ),
            )

        hardware[f"bay-{layout.index}"] = pi_envelope(
            pi,
            center_x,
            pi_center_y,
            layout.board_bottom_z_mm,
            layout.board_top_z_mm,
        )
        parts[f"bay-{layout.index}"] = pi_parts(
            pi, center_x, pi_center_y, layout.board_top_z_mm
        )

    base = cut_pi_openings(
        base,
        layouts=layouts,
        design=design,
        pi=pi,
        radius=radius,
        wall=wall,
        pi_center_y=pi_center_y,
        boss_columns=boss_columns,
    )
    base = cut_bay_openings(base, layouts, design)

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
    collisions = _part_collisions(base, lid, parts)
    checks["parts_clear_of_base"] = not any(c.endswith("base") for c in collisions)
    checks["parts_clear_of_lid"] = not any(c.endswith("lid") for c in collisions)
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
        part_collisions=collisions,
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
            together = cq.Compound.makeCompound(list(shapes.values()))

            if intersection_volume(solid, together) <= _INTERFERENCE_TOLERANCE_MM3:
                continue

            collisions.extend(
                f"{bay} {part} meets the {name}"
                for part, shape in shapes.items()
                if intersection_volume(solid, shape) > _INTERFERENCE_TOLERANCE_MM3
            )

    return tuple(collisions)


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

    A divider stands just clear of its own bay's header edge, so its notch
    is centred on that bay's header and rises from that bay's board.
    """

    placed: list[tuple[Divider, DividerPlacement]] = []

    for layout in layouts:
        if layout.divider is None:
            continue

        notch_y = pi_center_y + (pi.header_center_y_mm if layout.holds_pi else 0.0)
        notch_bottom = (
            layout.board_top_z_mm if layout.holds_pi else design.floor_mm + 2.0
        )
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
            make_box(
                (min(x, corner_x), max(x, corner_x)),
                (min(y, corner_y), max(y, corner_y)),
                (floor - FLOOR_EMBED_MM, floor + inner_height),
            )
        )

    return fills.combine()


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
        block = make_box(
            (wall - 0.5, wall + _JOIN_BOSS_REACH_MM),
            (y - radius, y + radius),
            (design.floor_mm - FLOOR_EMBED_MM, z),
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

        fan_x = wall + layout.center_x_mm + pi.fan_center_x_mm
        fan_y = pi_center_y + pi.fan_center_y_mm

        for index in range(_VENT_SLOTS):
            offset = (index - (_VENT_SLOTS - 1) / 2) * _VENT_PITCH_MM
            lid = lid.cut(
                make_box(
                    (
                        fan_x - _VENT_LENGTH_MM / 2,
                        fan_x + _VENT_LENGTH_MM / 2,
                    ),
                    (
                        fan_y + offset - _VENT_WIDTH_MM / 2,
                        fan_y + offset + _VENT_WIDTH_MM / 2,
                    ),
                    (cavity_top - 1.0, cavity_top + design.lid_mm + 1.0),
                )
            )

    return lid


def print_oriented_parts(group: GroupEnclosure) -> dict[str, cq.Shape]:
    """Each part as it goes on the bed: the base on its floor, the lid on its
    outer face, so the face you see sits against the plate."""

    return {
        "base": single_shape(group.base),
        "lid": single_shape(group.lid).rotate((0, 0, 0), (1, 0, 0), 180),
    }


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
