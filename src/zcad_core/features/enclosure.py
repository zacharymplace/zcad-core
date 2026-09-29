"""Build a printable two-part enclosure around a board-and-display assembly.

The base carries the floor, walls, board standoffs, a heat-set insert boss in
each corner, and the cable opening; the lid carries screw clearance holes
over the bosses and the display window. Both are derived from the assembly
through :func:`~zcad_core.assemblies.derive_enclosure_specification`, and the
builder refuses to return an enclosure whose features intersect any part of
the assembly.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.assemblies import (
    DeviceAssembly,
    EnclosureSpecification,
    derive_enclosure_specification,
)
from zcad_core.features.connector_cutouts import (
    ConnectorCutoutParameters,
    cut_connector_opening,
)
from zcad_core.features.display_cutouts import (
    DisplayWindowParameters,
    cut_display_window,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.pcb_mounts import (
    MountableBoardSpec,
    PcbStandoffParameters,
    add_pcb_standoff,
    centered_mounting_hole_positions,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import DisplaySpec, FastenerSpec, get_fastener

# Bosses and standoffs start this far down inside the floor, so they fuse to
# it and their pilot holes do not break through the underside.
_FLOOR_EMBED_MM = 0.5
_INTERFERENCE_TOLERANCE_MM3 = 1e-6
# Corner bosses overlap both walls by this much. Tangent contact leaves
# zero-width seams that mesh as non-manifold edges and fail STL validation.
_BOSS_WALL_OVERLAP_MM = 0.5


@dataclass(frozen=True)
class EnclosureDesign:
    """Wall, floor, and lid thicknesses and the lid fastener."""

    wall_mm: float = 2.0
    floor_mm: float = 2.0
    lid_mm: float = 2.0
    fastener: str = "M3"
    boss_radial_wall_mm: float = 1.8
    internal_clearance_mm: float = 2.0

    def validate(self) -> None:
        for name in ("wall_mm", "floor_mm", "lid_mm", "boss_radial_wall_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.floor_mm <= _FLOOR_EMBED_MM:
            raise ValueError(f"floor_mm must exceed {_FLOOR_EMBED_MM} mm")

        if self.internal_clearance_mm < 0:
            raise ValueError("internal_clearance_mm must not be negative")


@dataclass(frozen=True)
class Enclosure:
    """The two printable parts and the geometry they were built from."""

    base: cq.Workplane
    lid: cq.Workplane
    specification: EnclosureSpecification
    fastener: FastenerSpec
    fastener_positions: tuple[tuple[float, float], ...]


def build_enclosure(
    assembly: DeviceAssembly,
    *,
    board: MountableBoardSpec,
    display: DisplaySpec | None = None,
    board_identifier: str = "board",
    display_identifier: str = "display",
    connector_identifier: str = "board_connector",
    design: EnclosureDesign | None = None,
) -> Enclosure:
    """Build the base and lid for an assembly's board, display, and cable.

    Raises ``ValueError`` when a boss or standoff would intersect a part of
    the assembly; a larger ``internal_clearance_mm`` moves the corner bosses
    away from the board.
    """

    design = design or EnclosureDesign()
    design.validate()
    fastener = get_fastener(design.fastener)
    spec = derive_enclosure_specification(
        assembly,
        connector_identifier=connector_identifier,
        internal_clearance_mm=design.internal_clearance_mm,
    )
    floor_top = spec.bottom_z_mm
    cavity_top = spec.bottom_z_mm + spec.inner_height_mm
    board_placement = assembly.get(board_identifier).placement
    standoff_height = board_placement.z_mm - floor_top

    if standoff_height <= 0:
        raise ValueError("The board must sit above the enclosure floor")

    positions = _corner_boss_positions(spec, fastener, design)

    base = _shell(spec, design)

    for x, y in positions:
        base = add_heat_set_insert_boss(
            base,
            parameters=InsertBossParameters.from_fastener(
                fastener=fastener,
                x=x,
                y=y,
                base_height_mm=_FLOOR_EMBED_MM,
                base_z_mm=floor_top - _FLOOR_EMBED_MM,
                boss_height_mm=spec.inner_height_mm,
                radial_wall_mm=design.boss_radial_wall_mm,
            ),
        )

    for x, y in centered_mounting_hole_positions(board):
        base = add_pcb_standoff(
            base,
            parameters=PcbStandoffParameters.from_board(
                board=board,
                x=board_placement.x_mm + x,
                y=board_placement.y_mm + y,
                base_height_mm=_FLOOR_EMBED_MM,
                base_z_mm=floor_top - _FLOOR_EMBED_MM,
                standoff_height_mm=standoff_height,
            ),
        )

    base = cut_connector_opening(
        base,
        parameters=ConnectorCutoutParameters(
            edge=spec.cable_edge,
            center_offset_mm=spec.cable_center_offset_mm,
            bottom_z_mm=spec.cable_bottom_z_mm,
            width_mm=spec.cable_width_mm,
            height_mm=spec.cable_height_mm,
        ),
    )

    lid = _lid(spec, design, cavity_top, fastener, positions)

    if display is not None:
        display_placement = assembly.get(display_identifier).placement
        lid = cut_display_window(
            lid,
            parameters=DisplayWindowParameters.from_display(
                display=display,
                panel_base_z_mm=cavity_top,
                panel_thickness_mm=design.lid_mm,
                x=display_placement.x_mm,
                y=display_placement.y_mm,
            ),
        )

    _require_clear_of_assembly(assembly, base=base, lid=lid)

    return Enclosure(
        base=base,
        lid=lid,
        specification=spec,
        fastener=fastener,
        fastener_positions=positions,
    )


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
                    f"by {overlap:.3f} mm3; increase internal_clearance_mm or move "
                    "the part"
                )
