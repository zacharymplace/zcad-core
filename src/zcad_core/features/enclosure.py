"""Build a printable two-part enclosure around a board-and-display assembly.

The base carries the floor, walls, board supports, a heat-set insert boss in
each corner, and the cable opening; the lid carries screw clearance holes
over the bosses and the display window. A board with mounting holes sits on
standoffs; one without sits in a snap-in cradle. Both parts are derived from
the assembly through
:func:`~zcad_core.assemblies.derive_enclosure_specification`, and the
builder refuses to return an enclosure whose features intersect any part of
the assembly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import cadquery as cq

from zcad_core.assemblies import (
    DeviceAssembly,
    EnclosureSpecification,
    derive_enclosure_specification,
)
from zcad_core.features.board_cradle import BoardCradleParameters, add_board_cradle
from zcad_core.features.connector_cutouts import (
    ConnectorCutoutParameters,
    cut_connector_opening,
)
from zcad_core.features.display_cutouts import (
    DisplayWindowParameters,
    cut_display_window,
)
from zcad_core.features.display_retainer import (
    DisplayRetainerParameters,
    add_display_retainer,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.pcb_mounts import add_pcb_standoff, board_hole_pattern
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import BoardSpec, DisplaySpec, FastenerSpec, get_fastener

# Bosses and standoffs start this far down inside the floor, so they fuse to
# it and their pilot holes do not break through the underside.
_FLOOR_EMBED_MM = 0.5
_INTERFERENCE_TOLERANCE_MM3 = 1e-6
# Corner bosses overlap both walls by this much. Tangent contact leaves
# zero-width seams that mesh as non-manifold edges and fail STL validation.
_BOSS_WALL_OVERLAP_MM = 0.5
# The cable opening's cutter reaches this far past the wall's inner face.
_OPENING_OVERCUT_MM = 0.5
# An automatic side clearance starts at the minimum and widens X and Y
# independently in steps, taking the smallest footprint that works. Bosses
# must also clear the board outline grown by the support margin, so
# standoffs and cradle clips never fuse to a boss.
_MINIMUM_SIDE_CLEARANCE_MM = 2.0
_AUTOMATIC_WIDENING_MM = tuple(0.5 * step for step in range(25))
_SUPPORT_MARGIN_MM = 2.0


@dataclass(frozen=True)
class EnclosureDesign:
    """Wall, floor, and lid thicknesses, the lid fastener, the gaps between
    the hardware and the cavity, and the cable plug the opening must pass.

    ``side_clearance_mm`` sets how far the walls, and so the corner bosses,
    stand off the hardware; left unset, it starts at 2 mm and widens X and Y
    separately, in 0.5 mm steps, to the smallest footprint at which the
    bosses clear the hardware and the cable opening; ``bottom_clearance_mm`` is the standoff height
    under the lowest part; ``top_clearance_mm`` is the gap under the lid.
    The cable opening is at least ``cable_plug_width_mm`` by
    ``cable_plug_height_mm``, so a cable's moulded plug body reaches the
    connector through the wall and the gap inside it; the defaults fit
    common USB-C and micro-USB cables. Set both to zero for an opening sized
    to the connector alone. ``display_retainer`` hangs corner posts and snap
    clips from the lid to hold the display under its window.
    """

    wall_mm: float = 2.0
    floor_mm: float = 2.0
    lid_mm: float = 2.0
    fastener: str = "M3"
    boss_radial_wall_mm: float = 1.8
    side_clearance_mm: float | None = None
    bottom_clearance_mm: float = 2.0
    top_clearance_mm: float = 2.0
    cable_plug_width_mm: float = 12.5
    cable_plug_height_mm: float = 7.5
    display_retainer: bool = True

    def validate(self) -> None:
        for name in ("wall_mm", "floor_mm", "lid_mm", "boss_radial_wall_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.floor_mm <= _FLOOR_EMBED_MM:
            raise ValueError(f"floor_mm must exceed {_FLOOR_EMBED_MM} mm")

        if self.side_clearance_mm is not None and self.side_clearance_mm < 0:
            raise ValueError("side_clearance_mm must not be negative")

        for name in (
            "bottom_clearance_mm",
            "top_clearance_mm",
            "cable_plug_width_mm",
            "cable_plug_height_mm",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class Enclosure:
    """The two printable parts and the geometry they were built from."""

    base: cq.Workplane
    lid: cq.Workplane
    specification: EnclosureSpecification
    design: EnclosureDesign
    side_clearance_mm: tuple[float, float]
    fastener: FastenerSpec
    fastener_positions: tuple[tuple[float, float], ...]
    board_support: str


def build_enclosure(
    assembly: DeviceAssembly,
    *,
    board: BoardSpec,
    display: DisplaySpec | None = None,
    board_identifier: str = "board",
    display_identifier: str = "display",
    connector_identifier: str = "board_connector",
    design: EnclosureDesign | None = None,
) -> Enclosure:
    """Build the base and lid for an assembly's board, display, and cable.

    Raises ``ValueError`` when a boss, support, or opening would intersect a
    part of the assembly or another feature; a larger ``side_clearance_mm``
    moves the corner bosses away from the board.
    """

    design = design or EnclosureDesign()
    design.validate()
    fastener = get_fastener(design.fastener)
    if design.side_clearance_mm is None:
        spec, side_clearance = _automatic_specification(
            assembly,
            design=design,
            fastener=fastener,
            board_identifier=board_identifier,
            connector_identifier=connector_identifier,
            display_identifier=display_identifier if display is not None else None,
        )
    else:
        spec = _specification(
            assembly, design, design.side_clearance_mm, connector_identifier
        )
        side_clearance = (design.side_clearance_mm, design.side_clearance_mm)

    cavity_top = spec.bottom_z_mm + spec.inner_height_mm
    positions = _corner_boss_positions(spec, fastener, design)

    base = _shell(spec, design).union(_corner_fills(spec, positions))

    for x, y in positions:
        base = add_heat_set_insert_boss(
            base,
            parameters=InsertBossParameters.from_fastener(
                fastener=fastener,
                x=x,
                y=y,
                base_height_mm=_FLOOR_EMBED_MM,
                base_z_mm=spec.bottom_z_mm - _FLOOR_EMBED_MM,
                boss_height_mm=spec.inner_height_mm,
                radial_wall_mm=design.boss_radial_wall_mm,
            ),
        )

    base, board_support = _add_board_support(
        base,
        assembly=assembly,
        board=board,
        board_identifier=board_identifier,
        spec=spec,
    )
    base = _cut_cable_opening(base, spec, design, fastener, positions)

    lid = _lid(spec, design, cavity_top, fastener, positions)

    if display is not None:
        lid = _add_display_features(
            lid,
            assembly=assembly,
            display=display,
            display_identifier=display_identifier,
            design=design,
            cavity_top=cavity_top,
        )

    _require_clear_of_assembly(assembly, base=base, lid=lid)
    _require_parts_clear(base, lid)

    return Enclosure(
        base=base,
        lid=lid,
        specification=spec,
        design=design,
        side_clearance_mm=side_clearance,
        fastener=fastener,
        fastener_positions=positions,
        board_support=board_support,
    )


def _add_display_features(
    lid: cq.Workplane,
    *,
    assembly: DeviceAssembly,
    display: DisplaySpec,
    display_identifier: str,
    design: EnclosureDesign,
    cavity_top: float,
) -> cq.Workplane:
    """Cut the display window and hang the retainer under it."""

    component = assembly.get(display_identifier)
    lid = cut_display_window(
        lid,
        parameters=DisplayWindowParameters.from_display(
            display=display,
            panel_base_z_mm=cavity_top,
            panel_thickness_mm=design.lid_mm,
            x=component.placement.x_mm,
            y=component.placement.y_mm,
        ),
    )

    if not design.display_retainer:
        return lid

    bounds = _all_solids(component.transformed_geometry()).BoundingBox()

    return add_display_retainer(
        lid,
        parameters=DisplayRetainerParameters(
            center_x_mm=(bounds.xmin + bounds.xmax) / 2,
            center_y_mm=(bounds.ymin + bounds.ymax) / 2,
            module_width_mm=bounds.xlen,
            module_depth_mm=bounds.ylen,
            module_thickness_mm=bounds.zlen,
            module_top_z_mm=bounds.zmax,
            lid_underside_z_mm=cavity_top,
        ),
    )


def _specification(
    assembly: DeviceAssembly,
    design: EnclosureDesign,
    side_clearance: float,
    connector_identifier: str,
) -> EnclosureSpecification:
    return derive_enclosure_specification(
        assembly,
        connector_identifier=connector_identifier,
        side_clearance_mm=side_clearance,
        bottom_clearance_mm=design.bottom_clearance_mm,
        top_clearance_mm=design.top_clearance_mm,
    )


def _automatic_specification(
    assembly: DeviceAssembly,
    *,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    board_identifier: str,
    connector_identifier: str,
    display_identifier: str | None,
) -> tuple[EnclosureSpecification, tuple[float, float]]:
    """The smallest cavity whose corner bosses clear the hardware, the
    board's supports, and the cable opening, with its X and Y clearances."""

    obstacles = _boss_obstacles(assembly, board_identifier, display_identifier)
    radius = _boss_radius(fastener, design)
    minimum = _specification(
        assembly, design, _MINIMUM_SIDE_CLEARANCE_MM, connector_identifier
    )
    widenings = sorted(
        ((x, y) for x in _AUTOMATIC_WIDENING_MM for y in _AUTOMATIC_WIDENING_MM),
        key=lambda xy: (
            (minimum.inner_width_mm + 2 * xy[0]) * (minimum.inner_depth_mm + 2 * xy[1]),
            max(xy),
        ),
    )

    for widen_x, widen_y in widenings:
        spec = replace(
            minimum,
            inner_width_mm=minimum.inner_width_mm + 2 * widen_x,
            inner_depth_mm=minimum.inner_depth_mm + 2 * widen_y,
        )
        positions = _corner_boss_positions(spec, fastener, design)

        if _opening_hits_boss(spec, design, fastener, positions):
            continue

        bosses = [
            cq.Solid.makeCylinder(
                radius, spec.inner_height_mm, pnt=cq.Vector(x, y, spec.bottom_z_mm)
            )
            for x, y in positions
        ]

        if all(
            intersection_volume(boss, obstacle) <= _INTERFERENCE_TOLERANCE_MM3
            for boss in bosses
            for obstacle in obstacles
        ):
            return spec, (
                _MINIMUM_SIDE_CLEARANCE_MM + widen_x,
                _MINIMUM_SIDE_CLEARANCE_MM + widen_y,
            )

    raise ValueError("No side clearance clears the corner bosses; set one")


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
    """A shape's bounding box grown by the support margin in X and Y, and
    down by it, where supports and retainer clips reach."""

    bounds = shape.BoundingBox()

    return cq.Solid.makeBox(
        bounds.xlen + 2 * _SUPPORT_MARGIN_MM,
        bounds.ylen + 2 * _SUPPORT_MARGIN_MM,
        bounds.zlen + _SUPPORT_MARGIN_MM,
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
        )

        return add_board_cradle(base, parameters=cradle), "cradle"

    for x, y in pattern.positions:
        base = add_pcb_standoff(
            base,
            parameters=pattern.standoff(
                x=placement.x_mm + x,
                y=placement.y_mm + y,
                base_height_mm=_FLOOR_EMBED_MM,
                base_z_mm=floor_top - _FLOOR_EMBED_MM,
                standoff_height_mm=support_height,
            ),
        )

    return base, "standoffs"


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
    )


def _opening_hits_boss(
    spec: EnclosureSpecification,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> bool:
    opening = _cable_opening(spec, design)
    along_y = opening.edge in ("negative_y", "positive_y")
    reach = opening.opening_width_mm / 2 + _boss_radius(fastener, design)

    return any(
        abs((x if along_y else y) - opening.center_offset_mm) < reach
        for x, y in positions
    )


def _cut_cable_opening(
    base: cq.Workplane,
    spec: EnclosureSpecification,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> cq.Workplane:
    if _opening_hits_boss(spec, design, fastener, positions):
        raise ValueError(
            "The cable opening would cut a corner boss; increase "
            "side_clearance_mm or reduce cable_plug_width_mm"
        )

    return cut_connector_opening(base, parameters=_cable_opening(spec, design))


def _corner_boss_positions(
    spec: EnclosureSpecification,
    fastener: FastenerSpec,
    design: EnclosureDesign,
) -> tuple[tuple[float, float], ...]:
    """Boss centres at each cavity corner, sunk slightly into both walls."""

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


def _lid(
    spec: EnclosureSpecification,
    design: EnclosureDesign,
    cavity_top: float,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> cq.Workplane:
    """A plate over the walls with a clearance hole above each boss."""

    lid = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm + 2 * design.wall_mm,
            spec.inner_depth_mm + 2 * design.wall_mm,
            design.lid_mm,
            centered=(True, True, False),
        )
        .translate((spec.center_x_mm, spec.center_y_mm, cavity_top))
    )
    holes = (
        cq.Workplane("XY")
        .pushPoints(list(positions))
        .circle(fastener.clearance_hole_mm / 2)
        .extrude(design.lid_mm + 2.0)
        .translate((0, 0, cavity_top - 1.0))
    )

    return lid.cut(holes)


def _all_solids(model: cq.Workplane) -> cq.Shape:
    """Every shape on the workplane, not just the first ``val()``."""

    shapes = [value for value in model.vals() if isinstance(value, cq.Shape)]

    if not shapes:
        raise ValueError("Expected geometry on the workplane")

    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def _require_parts_clear(base: cq.Workplane, lid: cq.Workplane) -> None:
    """Refuse a lid whose retainer would run into the base's features."""

    overlap = intersection_volume(_all_solids(base), _all_solids(lid))

    if overlap > _INTERFERENCE_TOLERANCE_MM3:
        raise ValueError(
            f"The enclosure lid intersects the base by {overlap:.3f} mm3; "
            "increase side_clearance_mm or move the display"
        )


def _require_clear_of_assembly(
    assembly: DeviceAssembly, *, base: cq.Workplane, lid: cq.Workplane
) -> None:
    """Refuse an enclosure whose material intersects any assembly part."""

    parts = {"base": _all_solids(base), "lid": _all_solids(lid)}

    for component in assembly.components:
        geometry = _all_solids(component.transformed_geometry())

        for part_name, part in parts.items():
            overlap = intersection_volume(part, geometry)

            if overlap > _INTERFERENCE_TOLERANCE_MM3:
                raise ValueError(
                    f"The enclosure {part_name} intersects '{component.identifier}' "
                    f"by {overlap:.3f} mm3; increase the design's clearances or "
                    "move the part"
                )
