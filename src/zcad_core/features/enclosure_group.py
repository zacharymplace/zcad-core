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

This module holds the builder, :func:`build_group_enclosure`. What it uses
beside the types and bays in ``enclosure_group_model`` and
``enclosure_group_modules``: ``enclosure_group_base`` (the shell, corner fills,
mount, cradle, join features and dividers), ``enclosure_group_lid`` (the lid and
how it is attached), ``enclosure_group_cooling`` (vents and fans) and
``enclosure_group_checks`` (the refusals and the checks of what was built).

The frame: the outer bottom-left-front corner is the origin, +X runs along
the row, +Y runs front to back, +Z is up. The floor's top face is at
``z == floor_mm``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import cadquery as cq

from zcad_core.features.enclosure_group_base import (
    _add_cradle,
    _add_join_features,
    _add_mount,
    _corner_fills,
    _dividers,
    _module,
    _shell,
)
from zcad_core.features.enclosure_group_checks import (
    _checks,
    _longest_screw,
    _part_collisions,
    _require_stack_top_possible,
)
from zcad_core.features.enclosure_group_cooling import (
    _add_vents,
    _cut_fans,
    _drawn_mm2,
)
from zcad_core.features.enclosure_group_dividers import build_divider
from zcad_core.features.enclosure_group_envelope import single_shape
from zcad_core.features.enclosure_group_join import cut_pass_through, joint_positions
from zcad_core.features.enclosure_group_layout import (
    BOSS_WALL_OVERLAP_MM,
    boss_column_xs,
    layout_bays,
    resolve_bay,
)
from zcad_core.features.enclosure_group_lid import (
    _VENT_LENGTH_MM,
    _VENT_SLOTS,
    _VENT_WIDTH_MM,
    _attach_lid,
    _lid,
    _vent_centres,
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
    bay_openings,
    board_openings,
    cut_openings,
    pi_openings,
    require_openings_under_lid,
)
from zcad_core.features.fan_bay import fan_report
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.mount_stack import (
    TopHolding,
    build_stack_top,
    latch_sides,
    lid_openings,
    plain_lid,
)
from zcad_core.features.pcb_mounts import PcbStandoffParameters, add_pcb_standoff
from zcad_core.features.stack_profile import load_profile
from zcad_core.hardware import RaspberryPi5Spec, get_fastener, get_raspberry_pi5
from zcad_core.printing.bed import laid_flat

# Kept importable from here, where they were defined before the split.
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

        if module.support == "cradle":
            base = _add_cradle(base, layout, module, design, center_x)

        for hx, hy in module.holes:
            standoff_fastener = get_fastener(module.standoff_screw)
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
            layouts=layouts,
            modules=modules,
            design=design,
            inner_depth=inner_depth,
            radius=radius,
            boss_columns=boss_columns,
        )
        + bay_openings(layouts, design)
    )
    base = cut_openings(base, openings)

    join_positions: tuple[tuple[float, float], ...] = ()

    if design.join_bolts:
        join_positions = joint_positions(
            design,
            wall=wall,
            inner_depth=inner_depth,
            outer_depth=outer[1],
            radius=radius,
            corner_x=corner_x,
            screwed=screwed,
        )
        base = _add_join_features(
            base,
            positions=join_positions,
            fastener=fastener,
            design=design,
            outer_width=outer[0],
            radius=radius,
        )

    base = cut_pass_through(
        base,
        design,
        outer=outer,
        cavity_top=cavity_top,
        radius=radius,
        corner_x=corner_x,
        screwed=screwed,
    )

    lid = _lid(
        outer,
        wall=wall,
        design=design,
        cavity_top=cavity_top,
        fastener=fastener,
        boss_positions=boss_positions,
        layouts=layouts,
        modules=modules,
        pi=pi,
    )

    lid, fan_bodies, fan_cuts = _cut_fans(
        base,
        lid,
        specs=specs,
        layouts=layouts,
        design=design,
        outer=outer,
        inner_size=(inner_width, inner_depth),
        cavity_top=cavity_top,
        hardware=hardware,
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
        carried=fan_bodies,
    )
    hardware.update(fan_bodies)
    slots_mm2 = (
        len(_vent_centres(layouts, modules, pi, wall))
        * _VENT_SLOTS
        * _VENT_LENGTH_MM
        * _VENT_WIDTH_MM
        if design.vents
        else 0.0
    )
    fans = tuple(
        fan_report(
            plan,
            guard,
            plate_mm=design.lid_mm,
            screw=get_fastener(plan.fan.screw),
            openings=openings,
            vent_free_mm2=slots_mm2 + _drawn_mm2(vents, plan.direction),
        )
        for plan, guard in fan_cuts
    )
    base, pads, mount = _add_mount(
        base,
        design=design,
        fastener=fastener,
        outer=outer,
        # The real top, so a hinge's knuckles or a slide's raised walls count
        # against a rack unit, not just the lid's plate.
        height_mm=max(
            single_shape(base).BoundingBox().zmax,
            single_shape(lid).BoundingBox().zmax,
        ),
    )
    stack_top = None

    if design.stack_top and design.stack_profile:
        _require_stack_top_possible(design, fans=len(fan_cuts))
        lid_windows = lid_openings(
            lid,
            plain_lid(
                (outer[0] / 2, outer[1] / 2),
                (outer[0], outer[1]),
                cavity_top,
                design.lid_mm,
                boss_positions,
                fastener.clearance_hole_mm,
            ),
            cavity_top,
            cavity_top + design.lid_mm,
        )
        stack_top = build_stack_top(
            boss_positions,
            centre=(outer[0] / 2, outer[1] / 2),
            lid_size_mm=(outer[0], outer[1]),
            lid_top_z_mm=cavity_top + design.lid_mm,
            lid_mm=design.lid_mm,
            fastener=fastener,
            profile=load_profile(Path(design.stack_profile)),
            compensation=0.0,
            openings=lid_windows,
            holding=TopHolding(
                design.stack_top_holding,
                design.stack_top_magnet or "",
                latch_sides(design.stack_top_latch),
                design.stack_top_engagement_mm,
                design.slide_clearance_mm,
            ),
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
        stack_top=stack_top,
        vents=vents,
        hinge=hinge,
        slide=slide,
        fans=fans,
        lid_carried=tuple(fan_bodies),
    )


def print_oriented_parts(group: GroupEnclosure) -> dict[str, cq.Shape]:
    """Each part it exports, as it goes on the bed: the base on its floor, the
    lid on its outer face, so the face you see sits against the plate, and
    each mount piece or a stack top on whichever face lies flattest. A part
    that still has little of itself on the bed is sliced with supports (see
    :mod:`zcad_core.printing.bed`)."""

    parts = {
        "base": single_shape(group.base),
        "lid": single_shape(group.lid).rotate((0, 0, 0), (1, 0, 0), 180),
    }

    if group.mount is not None:
        for name, piece in group.mount.parts.items():
            parts[name] = laid_flat(single_shape(piece))

    if group.stack_top is not None:
        parts["stack_top"] = laid_flat(single_shape(group.stack_top.plate))

    return parts
