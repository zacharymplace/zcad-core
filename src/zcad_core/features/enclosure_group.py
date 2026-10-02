"""Build one printable enclosure around a row of bays.

A bay holds a Raspberry Pi 5, a board from a board file, or an open shelf; what a
bay holds is read from a module (:mod:`zcad_core.features.enclosure_group_modules`).
The rest of this describes a Pi bay.

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

from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_group_dividers import (
    Divider,
    DividerPlacement,
    build_divider,
    require_divider_fits,
)
from zcad_core.features.enclosure_group_envelope import make_box, single_shape
from zcad_core.features.enclosure_group_layout import (
    BOSS_WALL_OVERLAP_MM,
    boss_column_xs,
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
from zcad_core.features.enclosure_group_modules import (
    BayModule,
    board_module,
    pi_module,
)
from zcad_core.features.enclosure_group_openings import (
    bay_openings,
    board_openings,
    cut_openings,
    pi_openings,
    require_openings_under_lid,
)
from zcad_core.features.enclosure_lid import VENT_RIM_MM, Cavity
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.lid_hinge import HINGE_WEB_DEPTH_MM, HingeReport, add_hinge
from zcad_core.features.lid_slide import SlideReport, add_slide
from zcad_core.features.mount_rack import (
    FrontPads,
    add_front_pads,
    build_rack_ears,
    front_pads,
    is_rack,
)
from zcad_core.features.mounts import (
    MountPads,
    MountPlate,
    add_mount_pads,
    build_mount,
    mount_pads,
    require_mount_clear,
)
from zcad_core.features.pcb_mounts import PcbStandoffParameters, add_pcb_standoff
from zcad_core.features.vent_patterns import (
    VentReport,
    add_lid_outlets,
    add_wall_inlets,
)
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
_VENT_SLOTS = 5
_VENT_PITCH_MM = 5.0
_VENT_LENGTH_MM = 30.0
_VENT_WIDTH_MM = 2.4
_JOIN_HEIGHT_ABOVE_FLOOR_MM = 8.0
_JOIN_BOSS_REACH_MM = 8.0
_JOIN_Y_FRACTIONS = (0.65, 0.83)
_SCREW_LENGTHS_MM = (4, 5, 6, 8, 10, 12, 16, 20)
# A divider stops this far below a sliding lid, beyond the slide's clearance.
_SLIDE_DIVIDER_DROP_MM = 0.3


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
    modules = tuple(_module(spec, pi, index) for index, spec in enumerate(specs))

    fastener = get_fastener(design.fastener)
    insert_diameter = fastener.heat_set_insert_diameter_mm
    insert_depth = fastener.heat_set_insert_depth_mm

    if insert_diameter is None or insert_depth is None:
        raise ValueError(f"Fastener {fastener.identifier} has no heat-set insert")

    radius = insert_diameter / 2 + design.boss_radial_wall_mm
    # The row is as deep as its deepest board needs, and a row of shelves is as
    # deep as a Pi.
    depths = [module.depth_mm for module in modules if module is not None]
    inner_depth = (
        design.front_clearance_mm
        + (max(depths) if depths else pi.board_length_mm)
        + design.back_clearance_mm
    )
    layouts, inner_width = layout_bays(specs, design, modules, inner_depth)
    cavity_top = max(layout.needed_top_z_mm for layout in layouts)
    inner_height = cavity_top - design.floor_mm
    require_openings_under_lid(layouts, inner_height)
    wall = design.wall_mm
    pi_layouts = [layout for layout in layouts if layout.holds_pi]
    pi_center_y = (
        pi_layouts[0].center_y_mm
        if pi_layouts
        else wall + design.front_clearance_mm + pi.board_length_mm / 2
    )
    screwed = design.lid_attachment == "screws"
    # A sliding lid rides over the dividers, so they stop short of it.
    divider_height = inner_height - (
        design.slide_clearance_mm + _SLIDE_DIVIDER_DROP_MM
        if design.lid_attachment == "slide"
        else 0.0
    )
    dividers = _dividers(
        layouts,
        design=design,
        pi=pi,
        inner_height=divider_height,
        inner_depth=inner_depth,
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
    # Only a screwed lid has bosses to take its screws.
    boss_positions = (
        tuple((x, y) for x in boss_columns for y in (front_y, back_y))
        if screwed
        else ()
    )

    if screwed:
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

    hardware: dict[str, cq.Shape] = {}
    parts: dict[str, dict[str, cq.Shape]] = {}

    for layout, module in zip(layouts, modules, strict=True):
        if module is None:
            continue

        center_x = wall + layout.center_x_mm
        standoff_fastener = get_fastener(module.standoff_screw)

        for hx, hy in module.holes:
            base = add_pcb_standoff(
                base,
                parameters=PcbStandoffParameters(
                    x=center_x + hx,
                    y=layout.center_y_mm + hy,
                    base_height_mm=FLOOR_EMBED_MM,
                    standoff_height_mm=layout.standoff_height_mm,
                    outer_diameter_mm=module.standoff_diameter_mm,
                    hole_diameter_mm=standoff_fastener.tap_hole_mm,
                    base_z_mm=design.floor_mm - FLOOR_EMBED_MM,
                ),
            )

        hardware[f"bay-{layout.index}"] = module.envelope(
            center_x,
            layout.center_y_mm,
            layout.board_bottom_z_mm,
            layout.board_top_z_mm,
        )
        parts[f"bay-{layout.index}"] = module.parts(
            center_x, layout.center_y_mm, layout.board_top_z_mm
        )

    openings = (
        pi_openings(
            layouts=layouts,
            design=design,
            pi=pi,
            radius=radius,
            wall=wall,
            boss_columns=boss_columns,
        )
        + board_openings(
            layouts=layouts, modules=modules, design=design, inner_depth=inner_depth
        )
        + bay_openings(layouts, design)
    )
    base = cut_openings(base, openings)

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
    )

    base, lid, vents = _add_vents(
        base,
        lid,
        design=design,
        outer=outer,
        inner_size=(inner_width, inner_depth),
        cavity_top=cavity_top,
        keepout_mm=2 * radius + 1.0,
    )
    base, lid, hinge, slide = _attach_lid(
        base,
        lid,
        design=design,
        outer=outer,
        inner_size=(inner_width, inner_depth),
        cavity_top=cavity_top,
        openings=openings,
        hardware=hardware,
    )
    base, pads, mount = _add_mount(
        base,
        design=design,
        fastener=fastener,
        outer=outer,
        height_mm=cavity_top + design.lid_mm,
    )

    checks = _checks(base, lid, hardware)
    collisions = _part_collisions(base, lid, parts)
    checks["parts_clear_of_base"] = not any(c.endswith("base") for c in collisions)
    checks["parts_clear_of_lid"] = not any(c.endswith("lid") for c in collisions)
    lid_screw = _longest_screw(design.lid_mm + insert_depth) if screwed else None
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
        mount_pads=pads,
        mount=mount,
        vents=vents,
        hinge=hinge,
        slide=slide,
    )


def _attach_lid(
    base: cq.Workplane,
    lid: cq.Workplane,
    *,
    design: GroupDesign,
    outer: tuple[float, float, float],
    inner_size: tuple[float, float],
    cavity_top: float,
    openings: list[ConnectorCutoutParameters],
    hardware: dict[str, cq.Shape],
) -> tuple[cq.Workplane, cq.Workplane, HingeReport | None, SlideReport | None]:
    """Hinge or slide the lid, as the design asks; a screwed lid is left as it
    is. Both are the single-board builders on the group's cavity, and refuse a
    lid that cannot swing or slide clear of the base and the Pis."""

    if design.lid_attachment == "screws":
        return base, lid, None, None

    cavity = Cavity(
        center_x_mm=outer[0] / 2,
        center_y_mm=outer[1] / 2,
        width_mm=inner_size[0],
        depth_mm=inner_size[1],
        floor_z_mm=design.floor_mm,
        top_z_mm=cavity_top,
        wall_mm=design.wall_mm,
    )

    if design.lid_attachment == "hinge":
        _require_openings_clear_of_knuckles(openings, cavity_top)
        front = [opening for opening in openings if opening.edge == "negative_y"]
        base, lid, hinge = add_hinge(
            base,
            lid,
            cavity,
            lid_mm=design.lid_mm,
            pin=get_fastener(design.hinge_pin),
            hole_compensation_mm=0.0,
            openings=front,
            hardware=hardware,
            hinge_edge="positive_y",
        )

        return base, lid, hinge, None

    if not cavity.long_walls_on_y:
        raise ValueError(
            "A sliding lid runs along the row, which must be at least as wide as "
            "it is deep; add a bay, or use a hinged or screwed lid"
        )

    base, lid, slide = add_slide(
        base,
        lid,
        cavity,
        lid_mm=design.lid_mm,
        clearance_mm=design.slide_clearance_mm,
        hole_compensation_mm=0.0,
        openings=openings,
        hardware=hardware,
        entry=design.slide_entry,
    )

    return base, lid, None, slide


def _require_openings_clear_of_knuckles(
    openings: list[ConnectorCutoutParameters], cavity_top: float
) -> None:
    """The hinge's knuckles stand on the back wall's top edge, so no back-wall
    opening may reach it."""

    limit = cavity_top - HINGE_WEB_DEPTH_MM

    for opening in openings:
        top = opening.bottom_z_mm + opening.opening_height_mm

        if opening.edge == "positive_y" and top > limit:
            raise ValueError(
                f"A back-wall opening reaches {top:.1f} mm and the hinge's knuckles "
                f"need the wall above {limit:.1f} mm; raise headroom_mm by at "
                f"least {top - limit:.1f} mm, lower the opening, or use a "
                "sliding or screwed lid"
            )


def _add_vents(
    base: cq.Workplane,
    lid: cq.Workplane,
    *,
    design: GroupDesign,
    outer: tuple[float, float, float],
    inner_size: tuple[float, float],
    cavity_top: float,
    keepout_mm: float,
) -> tuple[cq.Workplane, cq.Workplane, VentReport | None]:
    """Inlets low in the two side walls and outlets in the lid, sized to the
    design's free area. The long walls are the front and back, which carry the
    Pis' openings; the side walls carry only the row's join features, which the
    cells keep clear of."""

    if not design.vent_area_mm2:
        return base, lid, None

    wall = design.wall_mm
    cavity = Cavity(
        center_x_mm=outer[0] / 2,
        center_y_mm=outer[1] / 2,
        width_mm=inner_size[0],
        depth_mm=inner_size[1],
        floor_z_mm=design.floor_mm,
        top_z_mm=cavity_top,
        wall_mm=wall,
    )
    base, inlets = add_wall_inlets(
        base,
        cavity,
        kind=design.vent_pattern,
        target_mm2=design.vent_area_mm2,
        blocked_edges=[],
        # The slide's entry wall comes down to the groove floor, a clearance
        # below the lid, so the inlets stop that much lower.
        top_z_mm=cavity_top
        - VENT_RIM_MM
        - (design.slide_clearance_mm if design.lid_attachment == "slide" else 0.0),
        corner_keepout_mm=keepout_mm,
        edges=("negative_x", "positive_x"),
    )
    inlet_mm2 = sum(fill.area_mm2 for fill in inlets)
    # Louvers are for walls, so the lid takes slots.
    kind = "slots" if design.vent_pattern == "louvers" else design.vent_pattern
    lid, outlet = add_lid_outlets(
        lid,
        cavity,
        lid_mm=design.lid_mm,
        kind=kind,
        target_mm2=max(design.vent_area_mm2, inlet_mm2),
    )

    return (
        base,
        lid,
        VentReport(
            pattern=design.vent_pattern,
            target_mm2=design.vent_area_mm2,
            inlet_mm2=inlet_mm2,
            outlet_mm2=outlet.area_mm2,
            inlet_cells=sum(len(fill.centers) for fill in inlets),
            outlet_cells=len(outlet.centers),
            inlet=inlets[0].spec.describe(),
            outlet=outlet.spec.describe(),
        ),
    )


def _add_mount(
    base: cq.Workplane,
    *,
    design: GroupDesign,
    fastener: FastenerSpec,
    outer: tuple[float, float, float],
    height_mm: float,
) -> tuple[cq.Workplane, MountPads | FrontPads | None, MountPlate | None]:
    """The base with the pads for the design's mount, the pads, and the
    mount's plate or ears; unchanged and empty when the design has none."""

    if design.mount is None:
        return base, None, None

    if is_rack(design.mount):
        front = front_pads(
            base,
            outer_size_mm=outer,
            enclosure_height_mm=height_mm,
            wall_mm=design.wall_mm,
            fastener=fastener,
        )
        base = add_front_pads(base, front)
        ears = build_rack_ears(
            front,
            enclosure_height_mm=height_mm,
            fastener=fastener,
            plate_mm=design.mount_plate_mm,
        )
        require_mount_clear(base, ears)

        return base, front, ears

    pads = mount_pads(
        x_span_mm=(0.0, outer[0]),
        y_span_mm=(0.0, outer[1]),
        floor_underside_z_mm=0.0,
        floor_mm=design.floor_mm,
        wall_mm=design.wall_mm,
        fastener=fastener,
    )
    base = add_mount_pads(base, pads)
    plate = build_mount(
        design.mount, pads, fastener=fastener, plate_mm=design.mount_plate_mm
    )
    require_mount_clear(base, plate)

    return base, pads, plate


def _module(bay: Bay, pi: RaspberryPi5Spec, index: int) -> BayModule | None:
    """What a bay holds: a Pi, a board from a board file, or nothing."""

    if bay.kind == "open":
        return None

    if bay.kind != "board" or bay.board is None:
        return pi_module(pi)

    try:
        return board_module(bay.board, rotate=bay.rotate, screw=bay.screw)
    except ValueError as error:
        raise ValueError(f"bay {index} (board): {error}") from error


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
) -> list[tuple[Divider, DividerPlacement]]:
    """Each bay's divider and where it stands, refused if it does not fit.

    A divider stands just clear of its own bay's header edge, so its notch
    is centred on that bay's header and rises from that bay's board.
    """

    placed: list[tuple[Divider, DividerPlacement]] = []

    for layout in layouts:
        if layout.divider is None:
            continue

        notch_y = layout.center_y_mm + (
            pi.header_center_y_mm if layout.holds_pi else 0.0
        )
        notch_bottom = (
            layout.board_top_z_mm if layout.holds_board else design.floor_mm + 2.0
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
) -> cq.Workplane:
    """A plate over the walls, a clearance hole over each boss, and vent
    slots over each Pi's SoC and cooler."""

    lid = (
        cq.Workplane("XY")
        .box(outer[0], outer[1], design.lid_mm, centered=False)
        .translate((0, 0, cavity_top))
    )

    if boss_positions:
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
        fan_y = layout.center_y_mm + pi.fan_center_y_mm

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
