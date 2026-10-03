"""A group enclosure's base: its shell, its corner fills, and what is added to it: a mount,
a cradle, the join features that bolt units together, and the dividers between bays.
"""

from __future__ import annotations

from pathlib import Path

import cadquery as cq

from zcad_core.features.board_cradle import BoardCradleParameters, add_board_cradle
from zcad_core.features.enclosure_group_dividers import (
    Divider,
    DividerPlacement,
    require_divider_fits,
)
from zcad_core.features.enclosure_group_envelope import make_box
from zcad_core.features.enclosure_group_model import (
    FLOOR_EMBED_MM,
    Bay,
    BayLayout,
    GroupDesign,
)
from zcad_core.features.enclosure_group_modules import (
    BayModule,
    board_module,
    pi_module,
)
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
from zcad_core.features.stack_profile import load_profile
from zcad_core.hardware import FastenerSpec, RaspberryPi5Spec

_JOIN_BOSS_REACH_MM = 8.0


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
        design.mount,
        pads,
        fastener=fastener,
        plate_mm=design.mount_plate_mm,
        stack_profile=(
            load_profile(Path(design.stack_profile)) if design.stack_profile else None
        ),
    )
    require_mount_clear(base, plate)

    return base, pads, plate


def _add_cradle(
    base: cq.Workplane,
    layout: BayLayout,
    module: BayModule,
    design: GroupDesign,
    center_x: float,
) -> cq.Workplane:
    """A snap-in cradle for a board with no mounting holes."""

    try:
        return add_board_cradle(
            base,
            parameters=BoardCradleParameters(
                center_x_mm=center_x,
                center_y_mm=layout.center_y_mm,
                board_width_mm=module.width_mm,
                board_depth_mm=module.depth_mm,
                board_bottom_z_mm=layout.board_bottom_z_mm,
                board_thickness_mm=module.thickness_mm,
                base_z_mm=design.floor_mm - FLOOR_EMBED_MM,
                connector_edge=module.connector_wall,  # type: ignore[arg-type]
                outline_points_mm=module.outline,
            ),
        )
    except ValueError as error:
        raise ValueError(f"bay {layout.index} (board): {error}") from error


def _module(bay: Bay, pi: RaspberryPi5Spec, index: int) -> BayModule | None:
    """What a bay holds: a Pi, a board from a board file, or nothing."""

    if bay.kind in ("open", "fan"):
        return None

    if bay.kind != "board" or bay.board is None:
        return pi_module(pi)

    try:
        return board_module(bay.board, rotate=bay.rotate, screw=bay.screw)
    except ValueError as error:
        raise ValueError(f"bay {index} (board): {error}") from error


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
