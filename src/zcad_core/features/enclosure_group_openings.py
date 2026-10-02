"""The wall openings of a group enclosure.

A Pi's own openings (its Ethernet and USB plugs, its microSD card, and the
cable exit at the end of its service gap), the openings a board bay's connectors
need, and the openings an ``open`` bay asks for."""

from __future__ import annotations

import cadquery as cq

from zcad_core.features.connector_cutouts import (
    ConnectorCutoutParameters,
    cut_connector_opening,
    merge_close_openings,
)
from zcad_core.features.enclosure_group_model import (
    OPENING_RIM_MM,
    BayLayout,
    GroupDesign,
)
from zcad_core.features.enclosure_group_modules import BayModule
from zcad_core.hardware import RaspberryPi5Spec

_BOSS_CLEARANCE_MM = 1.0
_CABLE_EXIT_HEIGHT_MM = 12.0
_SD_OPENING_HEIGHT_MM = 4.0
_SD_OPENING_MARGIN_MM = 2.0


def pi_openings(
    *,
    layouts: tuple[BayLayout, ...],
    design: GroupDesign,
    pi: RaspberryPi5Spec,
    radius: float,
    wall: float,
    boss_columns: tuple[float, ...],
) -> list[ConnectorCutoutParameters]:
    """Back-wall openings for each Pi's Ethernet and USB plugs, a front-wall
    opening for its microSD card, and one along its service gap for the
    power and HDMI cables."""

    depth = 2 * (wall + 0.5)
    margin = 2 * design.plug_margin_mm
    openings: list[ConnectorCutoutParameters] = []

    for layout in layouts:
        if not layout.holds_pi:
            continue

        center_x = wall + layout.center_x_mm
        back = [
            ConnectorCutoutParameters(
                edge="positive_y",
                center_offset_mm=center_x + port.center_mm,
                bottom_z_mm=layout.board_top_z_mm - 0.5,
                width_mm=port.width_mm,
                height_mm=port.height_mm,
                width_clearance_mm=margin,
                height_clearance_mm=design.plug_margin_mm,
                cutter_depth_mm=depth,
            )
            for port in pi.ports
            if port.edge == "positive_y"
        ]
        openings.extend(merge_close_openings(back, design.minimum_opening_web_mm))
        openings.append(
            ConnectorCutoutParameters(
                edge="negative_y",
                center_offset_mm=center_x,
                bottom_z_mm=layout.board_bottom_z_mm - _SD_OPENING_MARGIN_MM,
                width_mm=pi.sd_card_width_mm,
                height_mm=_SD_OPENING_HEIGHT_MM,
                width_clearance_mm=_SD_OPENING_MARGIN_MM,
                height_clearance_mm=0.0,
                cutter_depth_mm=depth,
            )
        )

        # The gap's front opening starts a millimetre past the Pi's slot and
        # stops short of the boss that closes the gap.
        start = wall + layout.slot_end_mm + 1.0
        end = boss_columns[layout.index + 1] - radius - _BOSS_CLEARANCE_MM
        width = end - start

        if width < 6.0:
            raise ValueError(
                "service_gap_mm leaves under 6 mm for the power and HDMI cables"
            )

        openings.append(
            ConnectorCutoutParameters(
                edge="negative_y",
                center_offset_mm=(start + end) / 2,
                bottom_z_mm=layout.board_top_z_mm - 1.0,
                width_mm=width,
                height_mm=_CABLE_EXIT_HEIGHT_MM,
                width_clearance_mm=0.0,
                height_clearance_mm=0.0,
                cutter_depth_mm=depth,
            )
        )

    return openings


def board_openings(
    *,
    layouts: tuple[BayLayout, ...],
    modules: tuple[BayModule | None, ...],
    design: GroupDesign,
    inner_depth: float,
    radius: float,
    boss_columns: tuple[float, ...],
) -> list[ConnectorCutoutParameters]:
    """Back and front wall openings for each board bay's connectors, refusing a
    connector whose board edge is too far from its wall to reach it, and a front
    opening along each service space, for the cable of a connector on a side."""

    wall = design.wall_mm
    depth = 2 * (wall + 0.5)
    margin = 2 * design.plug_margin_mm
    openings: list[ConnectorCutoutParameters] = []

    for layout, module in zip(layouts, modules, strict=True):
        if module is None or module.is_pi:
            continue

        front_gap = layout.center_y_mm - module.depth_mm / 2 - wall
        back_gap = wall + inner_depth - (layout.center_y_mm + module.depth_mm / 2)
        by_wall: dict[str, list[ConnectorCutoutParameters]] = {}

        for port in module.openings:
            gap = back_gap if port.wall == "positive_y" else front_gap

            if gap > design.board_reach_mm:
                side = "back" if port.wall == "positive_y" else "front"
                raise ValueError(
                    f"bay {layout.index} (board): {port.label} is at the {side} "
                    f"edge, which stands {gap:.1f} mm from the {side} wall, and an "
                    f"opening reaches only {design.board_reach_mm:g} mm: set "
                    "align= the other way, or make the row deeper"
                )

            by_wall.setdefault(port.wall, []).append(
                ConnectorCutoutParameters(
                    edge=port.wall,  # type: ignore[arg-type]
                    center_offset_mm=wall + layout.center_x_mm + port.along_mm,
                    bottom_z_mm=layout.board_top_z_mm + port.bottom_mm - 0.5,
                    width_mm=port.width_mm,
                    height_mm=port.height_mm,
                    width_clearance_mm=margin,
                    height_clearance_mm=design.plug_margin_mm,
                    cutter_depth_mm=depth,
                )
            )

        for group in by_wall.values():
            openings.extend(merge_close_openings(group, design.minimum_opening_web_mm))

        openings.extend(_service_exits(layout, module, design, radius, boss_columns))

    return openings


def _service_exits(
    layout: BayLayout,
    module: BayModule,
    design: GroupDesign,
    radius: float,
    boss_columns: tuple[float, ...],
) -> list[ConnectorCutoutParameters]:
    """The front-wall opening at the end of a board bay's service space on each
    side with a connector, where a plugged-in cable bends toward the front and
    leaves, as a Pi's does along its gap. It stops short of the boss that closes
    the gap."""

    wall = design.wall_mm
    depth = 2 * (wall + 0.5)
    spans = []

    if module.faces_right:
        spans.append(
            (
                wall + layout.slot_end_mm + 1.0,
                boss_columns[layout.index + 1] - radius - _BOSS_CLEARANCE_MM,
                "right",
            )
        )

    if module.faces_left:
        spans.append(
            (
                wall + layout.slot_start_mm - layout.left_space_mm + 1.0,
                wall + layout.slot_start_mm - 1.0,
                "left",
            )
        )

    exits = []

    for start, end, side in spans:
        if end - start < 6.0:
            raise ValueError(
                f"bay {layout.index} (board): the {side} service space leaves "
                f"{max(end - start, 0.0):.1f} mm for the cable, and the least is 6 mm: "
                "raise service_gap_mm"
            )

        exits.append(
            ConnectorCutoutParameters(
                edge="negative_y",
                center_offset_mm=(start + end) / 2,
                bottom_z_mm=layout.board_top_z_mm - 1.0,
                width_mm=end - start,
                height_mm=_CABLE_EXIT_HEIGHT_MM,
                width_clearance_mm=0.0,
                height_clearance_mm=0.0,
                cutter_depth_mm=depth,
            )
        )

    return exits


def require_openings_under_lid(
    layouts: tuple[BayLayout, ...], inner_height: float
) -> None:
    """Refuse an opening that would reach the lid's seat, and say how to
    make room: the box is as tall as its tallest bay needs."""

    for layout in layouts:
        for opening in layout.openings:
            top = opening.bottom_mm + opening.height_mm

            if top > inner_height - OPENING_RIM_MM:
                raise ValueError(
                    f"bay {layout.index}: the opening reaches {top:g} mm but the "
                    f"box is {inner_height:g} mm tall inside and needs "
                    f"{OPENING_RIM_MM:g} mm of wall under the lid; lower the "
                    "opening or raise headroom_mm on a bay"
                )


def bay_openings(
    layouts: tuple[BayLayout, ...], design: GroupDesign
) -> list[ConnectorCutoutParameters]:
    """The front and back wall openings an ``open`` bay asks for."""

    depth = 2 * (design.wall_mm + 0.5)

    return [
        ConnectorCutoutParameters(
            edge="negative_y" if opening.wall == "front" else "positive_y",
            center_offset_mm=design.wall_mm + layout.center_x_mm + opening.offset_mm,
            bottom_z_mm=design.floor_mm + opening.bottom_mm,
            width_mm=opening.width_mm,
            height_mm=opening.height_mm,
            width_clearance_mm=0.0,
            height_clearance_mm=0.0,
            cutter_depth_mm=depth,
        )
        for layout in layouts
        for opening in layout.openings
    ]


def cut_openings(
    base: cq.Workplane, openings: list[ConnectorCutoutParameters]
) -> cq.Workplane:
    """Cut each opening through its wall."""

    for opening in openings:
        base = cut_connector_opening(base, parameters=opening)

    return base
