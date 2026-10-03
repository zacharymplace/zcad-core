"""The openings an enclosure's walls carry: the cable's and those a board declares."""

from __future__ import annotations

import cadquery as cq

from zcad_core.assemblies import DeviceAssembly, EnclosureSpecification
from zcad_core.features.connector_cutouts import (
    ConnectorCutoutParameters,
    cut_connector_opening,
    merge_close_openings,
)
from zcad_core.features.enclosure_geometry import _boss_radius, _bounds, _overlap
from zcad_core.features.enclosure_model import EnclosureDesign
from zcad_core.hardware import BoardSpec, FastenerSpec

# The cable opening's cutter reaches this far past the wall's inner face.
_OPENING_OVERCUT_MM = 0.5


# The builder's default fits, before hole compensation widens them.
_OPENING_CLEARANCE_MM = 0.6


# A board's declared wall openings pass a plug's shell, not just the socket:
# this much wider on each side and taller, as the group enclosure's ports.
_PLUG_MARGIN_MM = 1.5


def _cable_opening(
    spec: EnclosureSpecification, design: EnclosureDesign
) -> ConnectorCutoutParameters:
    """The cable opening, big enough for the plug, through one wall only."""

    width = max(spec.cable_width_mm, design.cable_plug_width_mm)
    height = max(spec.cable_height_mm, design.cable_plug_height_mm)
    center_z = spec.cable_bottom_z_mm + spec.cable_height_mm / 2
    bottom_z = max(center_z - height / 2, spec.bottom_z_mm)
    along_y = spec.cable_edge in ("negative_y", "positive_y")

    return ConnectorCutoutParameters(
        edge=spec.cable_edge,
        center_offset_mm=(spec.center_x_mm if along_y else spec.center_y_mm)
        + spec.cable_center_offset_mm,
        bottom_z_mm=bottom_z,
        width_mm=width,
        height_mm=center_z + height / 2 - bottom_z,
        cutter_depth_mm=2 * (design.wall_mm + _OPENING_OVERCUT_MM),
        width_clearance_mm=_OPENING_CLEARANCE_MM + design.hole_compensation_mm,
    )


def _openings(
    spec: EnclosureSpecification,
    design: EnclosureDesign,
    assembly: DeviceAssembly,
    board: BoardSpec,
    board_identifier: str,
) -> list[ConnectorCutoutParameters]:
    """The cable opening, the board's declared wall openings, and one for
    each other board part reached through a wall, such as a barrel jack."""

    declared = _declared_openings(design, assembly, board, board_identifier)
    openings = [_cable_opening(spec, design), *declared]
    board_top = _bounds(assembly, board_identifier).zmax

    for component in assembly.components:
        edge = component.metadata.get("access_edge")

        if component.metadata.get("board_identifier") != board_identifier or not edge:
            continue

        bounds = _bounds(assembly, component.identifier)

        # Only the part above the board is reached; its pins below are not.
        if bounds.zmin < board_top - 1e-6:
            continue

        along_y = edge in ("negative_y", "positive_y")
        opening = ConnectorCutoutParameters(
            edge=edge,
            center_offset_mm=(
                (bounds.xmin + bounds.xmax) / 2
                if along_y
                else (bounds.ymin + bounds.ymax) / 2
            ),
            bottom_z_mm=bounds.zmin,
            width_mm=bounds.xlen if along_y else bounds.ylen,
            height_mm=bounds.zlen,
            cutter_depth_mm=2 * (design.wall_mm + _OPENING_OVERCUT_MM),
            width_clearance_mm=_OPENING_CLEARANCE_MM + design.hole_compensation_mm,
        )

        # A declared opening already passes the plug for this part.
        if not any(_overlap(opening, other) for other in declared):
            openings.append(opening)

    return merge_close_openings(openings, design.minimum_opening_web_mm)


def _declared_openings(
    design: EnclosureDesign,
    assembly: DeviceAssembly,
    board: BoardSpec,
    board_identifier: str,
) -> list[ConnectorCutoutParameters]:
    """The openings the board declares, placed with it and grown for the
    plug that passes each."""

    if not board.wall_openings:
        return []

    bounds = _bounds(assembly, board_identifier)
    center_x = (bounds.xmin + bounds.xmax) / 2
    center_y = (bounds.ymin + bounds.ymax) / 2

    return [
        ConnectorCutoutParameters(
            edge=wall.edge,
            center_offset_mm=wall.center_offset_mm
            + (center_x if wall.edge in ("negative_y", "positive_y") else center_y),
            bottom_z_mm=bounds.zmax
            + wall.bottom_offset_from_board_top_mm
            - _PLUG_MARGIN_MM / 2,
            width_mm=wall.width_mm,
            height_mm=wall.height_mm,
            width_clearance_mm=2 * _PLUG_MARGIN_MM + design.hole_compensation_mm,
            height_clearance_mm=_PLUG_MARGIN_MM,
            cutter_depth_mm=2 * (design.wall_mm + _OPENING_OVERCUT_MM),
        )
        for wall in board.wall_openings
    ]


def _opening_hits_boss(
    openings: list[ConnectorCutoutParameters],
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> bool:
    radius = _boss_radius(fastener, design)

    return any(
        abs(
            (x if opening.edge in ("negative_y", "positive_y") else y)
            - opening.center_offset_mm
        )
        < opening.opening_width_mm / 2 + radius
        for opening in openings
        for x, y in positions
    )


def _cut_openings(
    base: cq.Workplane,
    openings: list[ConnectorCutoutParameters],
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> cq.Workplane:
    if _opening_hits_boss(openings, design, fastener, positions):
        raise ValueError(
            "An opening in the wall would cut a corner boss; increase "
            "side_clearance_mm or reduce cable_plug_width_mm"
        )

    for opening in openings:
        base = cut_connector_opening(base, parameters=opening)

    return base
