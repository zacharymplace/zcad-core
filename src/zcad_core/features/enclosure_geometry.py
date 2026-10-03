"""Cavity, boss, shell and support geometry the enclosure builder shares."""

from __future__ import annotations

from dataclasses import replace

import cadquery as cq

from zcad_core.assemblies import DeviceAssembly, EnclosureSpecification
from zcad_core.features.board_cradle import BoardCradleParameters, add_board_cradle
from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.enclosure_model import _FLOOR_EMBED_MM, EnclosureDesign
from zcad_core.features.insert_bosses import InsertBossParameters
from zcad_core.features.pcb_mounts import add_pcb_standoff, board_hole_pattern
from zcad_core.hardware import BoardSpec, FastenerSpec

_INTERFERENCE_TOLERANCE_MM3 = 1e-6


# Corner bosses overlap both walls by this much. Tangent contact leaves
# zero-width seams that mesh as non-manifold edges and fail STL validation.
_BOSS_WALL_OVERLAP_MM = 0.5


_SUPPORT_MARGIN_MM = 2.0


# Supports are notched this far clear of the parts under the board.
_UNDER_BOARD_CLEARANCE_MM = 0.3


_CRADLE_CLEARANCE_MM = 0.3


def _cavity(spec: EnclosureSpecification, design: EnclosureDesign) -> Cavity:
    return Cavity(
        center_x_mm=spec.center_x_mm,
        center_y_mm=spec.center_y_mm,
        width_mm=spec.inner_width_mm,
        depth_mm=spec.inner_depth_mm,
        floor_z_mm=spec.bottom_z_mm,
        top_z_mm=spec.bottom_z_mm + spec.inner_height_mm,
        wall_mm=design.wall_mm,
    )


def _boss_obstacles(
    assembly: DeviceAssembly, board_identifier: str, display_identifier: str | None
) -> list[cq.Shape]:
    """Every component, and the zones its supports and retainers use."""

    zones = [board_identifier]

    if display_identifier is not None:
        zones.append(display_identifier)

    return [
        *(
            _all_solids(component.transformed_geometry())
            for component in assembly.components
        ),
        *(
            _grown(_all_solids(assembly.get(name).transformed_geometry()))
            for name in zones
        ),
    ]


def _grown(shape: cq.Shape) -> cq.Shape:
    """A shape's bounding box grown by the support margin all round, where
    supports, cradle clips, and retainer clips reach."""

    bounds = shape.BoundingBox()

    return cq.Solid.makeBox(
        bounds.xlen + 2 * _SUPPORT_MARGIN_MM,
        bounds.ylen + 2 * _SUPPORT_MARGIN_MM,
        bounds.zlen + 2 * _SUPPORT_MARGIN_MM,
        pnt=cq.Vector(
            bounds.xmin - _SUPPORT_MARGIN_MM,
            bounds.ymin - _SUPPORT_MARGIN_MM,
            bounds.zmin - _SUPPORT_MARGIN_MM,
        ),
    )


def _boss_radius(fastener: FastenerSpec, design: EnclosureDesign) -> float:
    return (fastener.heat_set_insert_diameter_mm or 0) / 2 + design.boss_radial_wall_mm


def _add_board_support(
    base: cq.Workplane,
    *,
    assembly: DeviceAssembly,
    board: BoardSpec,
    board_identifier: str,
    spec: EnclosureSpecification,
    hole_compensation_mm: float = 0.0,
) -> tuple[cq.Workplane, str]:
    """Standoffs under a board's holes, or a cradle for a board without."""

    component = assembly.get(board_identifier)
    placement = component.placement

    # The connector edge the cable opening is cut in is the board's own, so
    # a rotated board would put the opening in the wrong wall.
    if placement.rotation_x_deg or placement.rotation_y_deg or placement.rotation_z_deg:
        raise ValueError("The board must not be rotated; rotate the enclosure")

    bounds = _all_solids(component.transformed_geometry()).BoundingBox()
    floor_top = spec.bottom_z_mm
    support_height = bounds.zmin - floor_top

    if support_height <= 0:
        raise ValueError("The board must sit above the enclosure floor")

    pattern = board_hole_pattern(board)

    if pattern is None:
        cradle = BoardCradleParameters(
            center_x_mm=(bounds.xmin + bounds.xmax) / 2,
            center_y_mm=(bounds.ymin + bounds.ymax) / 2,
            board_width_mm=bounds.xlen,
            board_depth_mm=bounds.ylen,
            board_bottom_z_mm=bounds.zmin,
            board_thickness_mm=bounds.zlen,
            base_z_mm=floor_top - _FLOOR_EMBED_MM,
            connector_edge=spec.cable_edge,
            clearance_mm=_CRADLE_CLEARANCE_MM + hole_compensation_mm / 2,
            outline_points_mm=getattr(board, "outline_points_mm", None),
        )

        return add_board_cradle(base, parameters=cradle), "cradle"

    for x, y in pattern.positions:
        standoff = pattern.standoff(
            x=placement.x_mm + x,
            y=placement.y_mm + y,
            base_height_mm=_FLOOR_EMBED_MM,
            base_z_mm=floor_top - _FLOOR_EMBED_MM,
            standoff_height_mm=support_height,
        )
        base = add_pcb_standoff(
            base,
            parameters=replace(
                standoff,
                hole_diameter_mm=standoff.hole_diameter_mm + hole_compensation_mm,
            ),
        )

    return base, "standoffs"


def _overlap(a: ConnectorCutoutParameters, b: ConnectorCutoutParameters) -> bool:
    """Whether two openings in the same wall overlap."""

    along = (
        abs(a.center_offset_mm - b.center_offset_mm)
        < (a.opening_width_mm + b.opening_width_mm) / 2
    )
    up = (
        a.bottom_z_mm < b.bottom_z_mm + b.opening_height_mm
        and b.bottom_z_mm < a.bottom_z_mm + a.opening_height_mm
    )

    return a.edge == b.edge and along and up


def _bounds(assembly: DeviceAssembly, identifier: str) -> cq.BoundBox:
    return _all_solids(assembly.get(identifier).transformed_geometry()).BoundingBox()


def _clear_parts_under_board(
    base: cq.Workplane,
    spec: EnclosureSpecification,
    assembly: DeviceAssembly,
    board_identifier: str,
) -> cq.Workplane:
    """Notch the board's supports around the parts on its underside, such as
    header pins, so a standoff beside them still reaches the board."""

    board_bottom = _bounds(assembly, board_identifier).zmin

    for component in assembly.components:
        if component.metadata.get("board_identifier") != board_identifier:
            continue

        part = _bounds(assembly, component.identifier)

        if part.zmax > board_bottom + 1e-6:
            continue

        bottom = max(part.zmin - _UNDER_BOARD_CLEARANCE_MM, spec.bottom_z_mm)
        base = base.cut(
            cq.Workplane("XY")
            .box(
                part.xlen + 2 * _UNDER_BOARD_CLEARANCE_MM,
                part.ylen + 2 * _UNDER_BOARD_CLEARANCE_MM,
                board_bottom - bottom,
                centered=False,
            )
            .translate(
                (
                    part.xmin - _UNDER_BOARD_CLEARANCE_MM,
                    part.ymin - _UNDER_BOARD_CLEARANCE_MM,
                    bottom,
                )
            )
        )

    return base


def _compensated_boss(
    boss: InsertBossParameters, hole_compensation_mm: float
) -> InsertBossParameters:
    return replace(
        boss,
        insert_pocket_diameter_mm=boss.insert_pocket_diameter_mm + hole_compensation_mm,
        pilot_hole_diameter_mm=boss.pilot_hole_diameter_mm + hole_compensation_mm,
    )


def _corner_boss_positions(
    spec: EnclosureSpecification,
    fastener: FastenerSpec,
    design: EnclosureDesign,
) -> tuple[tuple[float, float], ...]:
    """Boss centres at each cavity corner, sunk slightly into both walls;
    none for a snap-fit or hinged lid."""

    if design.lid_attachment != "screws":
        return ()

    insert_diameter = fastener.heat_set_insert_diameter_mm

    if insert_diameter is None:
        raise ValueError(
            f"Fastener {fastener.identifier} has no heat-set insert dimensions"
        )

    inset = insert_diameter / 2 + design.boss_radial_wall_mm - _BOSS_WALL_OVERLAP_MM
    half_x = spec.inner_width_mm / 2 - inset
    half_y = spec.inner_depth_mm / 2 - inset

    if half_x <= 0 or half_y <= 0:
        raise ValueError("The cavity is too small for corner insert bosses")

    return tuple(
        (spec.center_x_mm + sx * half_x, spec.center_y_mm + sy * half_y)
        for sx in (-1, 1)
        for sy in (-1, 1)
    )


def _shell(spec: EnclosureSpecification, design: EnclosureDesign) -> cq.Workplane:
    """Floor and walls around the cavity, open at the top."""

    outer = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm + 2 * design.wall_mm,
            spec.inner_depth_mm + 2 * design.wall_mm,
            spec.inner_height_mm + design.floor_mm,
            centered=(True, True, False),
        )
        .translate(
            (spec.center_x_mm, spec.center_y_mm, spec.bottom_z_mm - design.floor_mm)
        )
    )
    cavity = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm,
            spec.inner_depth_mm,
            spec.inner_height_mm + 1.0,
            centered=(True, True, False),
        )
        .translate((spec.center_x_mm, spec.center_y_mm, spec.bottom_z_mm))
    )

    return outer.cut(cavity)


def _corner_fills(
    spec: EnclosureSpecification, positions: tuple[tuple[float, float], ...]
) -> cq.Workplane:
    """Fill each cavity corner behind its boss, where a round boss meeting
    two walls would otherwise leave a narrow void the full cavity height."""

    fills = cq.Workplane("XY")

    for x, y in positions:
        corner_x = spec.center_x_mm + (
            spec.inner_width_mm / 2
            if x > spec.center_x_mm
            else -spec.inner_width_mm / 2
        )
        corner_y = spec.center_y_mm + (
            spec.inner_depth_mm / 2
            if y > spec.center_y_mm
            else -spec.inner_depth_mm / 2
        )
        fills = fills.add(
            cq.Solid.makeBox(
                abs(corner_x - x),
                abs(corner_y - y),
                spec.inner_height_mm + _FLOOR_EMBED_MM,
                pnt=cq.Vector(
                    min(x, corner_x),
                    min(y, corner_y),
                    spec.bottom_z_mm - _FLOOR_EMBED_MM,
                ),
            )
        )

    return fills.combine()


def _all_solids(model: cq.Workplane) -> cq.Shape:
    """Every shape on the workplane, not just the first ``val()``."""

    shapes = [value for value in model.vals() if isinstance(value, cq.Shape)]

    if not shapes:
        raise ValueError("Expected geometry on the workplane")

    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
