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
    DisplayPostParameters,
    DisplayRetainerParameters,
    add_display_posts,
    add_display_retainer,
)
from zcad_core.features.enclosure_lid import (
    LIP_DEPTH_MM,
    SNAP_SKIRT_DEPTH_MM,
    VENT_RIM_MM,
    Cavity,
    countersinks,
    notch_skirt,
    relief_slits,
    skirt,
    snap_grooves,
    snap_ridges,
    vents,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.pcb_mounts import (
    BoardHolePattern,
    add_pcb_standoff,
    board_hole_pattern,
)
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
# Supports are notched this far clear of the parts under the board.
_UNDER_BOARD_CLEARANCE_MM = 0.3
_DISPLAY_POST_WALL_MM = 1.2
# Printers print holes small far more often than large, and the cradle's
# 0.3 mm fit leaves little room to shrink.
HOLE_COMPENSATION_RANGE_MM = (-0.2, 1.0)
LID_ATTACHMENTS = ("screws", "snap")
# A flat-head screw's head is about twice its thread (ISO 10642 M3: 6 mm).
_COUNTERSINK_HEAD_ALLOWANCE_MM = 0.0
# The builder's default fits, before hole compensation widens them.
_OPENING_CLEARANCE_MM = 0.6
_CRADLE_CLEARANCE_MM = 0.3
_RETAINER_CLEARANCE_MM = 0.3


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
    to the connector alone. ``display_retainer`` holds the display under
    its window: screw posts over a display's mounting holes, for
    ``display_fastener`` self-tapping screws, or, for a display without
    holes, corner posts and snap clips.
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
    display_fastener: str = "M2"
    # How much wider than intended every hole and opening is modelled, to
    # make up for a printer that prints them undersized. A trial measures
    # the intended sizes; ``enclosure revise`` sets this from the shortfall.
    hole_compensation_mm: float = 0.0
    # "screws" into heat-set inserts, or a "snap" lid with no fasteners.
    lid_attachment: str = "screws"
    # Sink flat-head lid screws flush (screwed lids only).
    countersunk_screws: bool = False
    # A skirt under a screwed lid that keys it onto the base.
    locating_lip: bool = False
    # Vertical vent slots in each long wall that carries no opening.
    vent_slots: int = 0

    def validate(self) -> None:
        for name in ("wall_mm", "floor_mm", "lid_mm", "boss_radial_wall_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.floor_mm <= _FLOOR_EMBED_MM:
            raise ValueError(f"floor_mm must exceed {_FLOOR_EMBED_MM} mm")

        low, high = HOLE_COMPENSATION_RANGE_MM

        if not low <= self.hole_compensation_mm <= high:
            raise ValueError(f"hole_compensation_mm must be from {low} to {high} mm")

        if self.side_clearance_mm is not None and self.side_clearance_mm < 0:
            raise ValueError("side_clearance_mm must not be negative")

        self._validate_lid()

        for name in (
            "bottom_clearance_mm",
            "top_clearance_mm",
            "cable_plug_width_mm",
            "cable_plug_height_mm",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

    def _validate_lid(self) -> None:
        if self.lid_attachment not in LID_ATTACHMENTS:
            raise ValueError(f"lid_attachment must be one of {LID_ATTACHMENTS}")

        snap = self.lid_attachment == "snap"

        if snap and self.countersunk_screws:
            raise ValueError("A snap-fit lid has no screws to countersink")

        if snap and self.locating_lip:
            raise ValueError("A snap-fit lid already locates on its skirt")

        if self.vent_slots < 0:
            raise ValueError("vent_slots must not be negative")

    @property
    def skirt_depth_mm(self) -> float | None:
        """How far the lid's skirt reaches into the base, if it has one."""
        if self.lid_attachment == "snap":
            return SNAP_SKIRT_DEPTH_MM

        return LIP_DEPTH_MM if self.locating_lip else None


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
    display_support: str | None = None
    # Screws up through the display's PCB into its posts: how many, and the
    # longest that fits (PCB thickness plus post length).
    display_screw_count: int = 0
    display_screw_reach_mm: float | None = None
    # The cable opening first, then one per board part reached through a wall.
    openings: tuple[ConnectorCutoutParameters, ...] = ()


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

    base = _shell(spec, design)

    if positions:
        base = base.union(_corner_fills(spec, positions))

    for x, y in positions:
        base = add_heat_set_insert_boss(
            base,
            parameters=_compensated_boss(
                InsertBossParameters.from_fastener(
                    fastener=fastener,
                    x=x,
                    y=y,
                    base_height_mm=_FLOOR_EMBED_MM,
                    base_z_mm=spec.bottom_z_mm - _FLOOR_EMBED_MM,
                    boss_height_mm=spec.inner_height_mm,
                    radial_wall_mm=design.boss_radial_wall_mm,
                ),
                design.hole_compensation_mm,
            ),
        )

    base, board_support = _add_board_support(
        base,
        assembly=assembly,
        board=board,
        board_identifier=board_identifier,
        spec=spec,
        hole_compensation_mm=design.hole_compensation_mm,
    )
    base = _clear_parts_under_board(base, spec, assembly, board_identifier)
    openings = _openings(spec, design, assembly, board_identifier)
    base = _cut_openings(base, openings, design, fastener, positions)
    cavity = _cavity(spec, design)
    base = _lid_options_in_base(base, cavity, design, fastener, positions, openings)
    lid = _lid(spec, design, cavity_top, fastener, positions)
    lid = _lid_options_in_lid(lid, cavity, design, fastener, positions, openings)

    display_support = None
    display_screws: tuple[int, float] | None = None

    if display is not None:
        lid, display_support, display_screws = _add_display_features(
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
        display_support=display_support,
        openings=tuple(openings),
        display_screw_count=display_screws[0] if display_screws else 0,
        display_screw_reach_mm=display_screws[1] if display_screws else None,
    )


def _add_display_features(
    lid: cq.Workplane,
    *,
    assembly: DeviceAssembly,
    display: DisplaySpec,
    display_identifier: str,
    design: EnclosureDesign,
    cavity_top: float,
) -> tuple[cq.Workplane, str | None, tuple[int, float] | None]:
    """Cut the display window and hang what holds the display under it; for
    screw posts, also the number of screws and the longest that fits."""

    component = assembly.get(display_identifier)
    lid = cut_display_window(
        lid,
        parameters=DisplayWindowParameters.from_display(
            display=display,
            panel_base_z_mm=cavity_top,
            panel_thickness_mm=design.lid_mm,
            x=component.placement.x_mm,
            y=component.placement.y_mm,
            window_clearance_mm=display.recommended_window_clearance_mm
            + design.hole_compensation_mm / 2,
        ),
    )

    if not design.display_retainer:
        return lid, None, None

    bounds = _all_solids(component.transformed_geometry()).BoundingBox()
    holes = board_hole_pattern(display)

    if holes is not None:
        pcb_face = bounds.zmax - (display.panel_thickness_mm or 0.0)
        reach = cavity_top - pcb_face + (display.pcb_thickness_mm or 0.0)

        return (
            _add_display_posts(lid, display, holes, bounds, design, cavity_top),
            "posts",
            (len(holes.positions), reach),
        )

    return (
        add_display_retainer(
            lid,
            parameters=DisplayRetainerParameters(
                center_x_mm=(bounds.xmin + bounds.xmax) / 2,
                center_y_mm=(bounds.ymin + bounds.ymax) / 2,
                module_width_mm=bounds.xlen,
                module_depth_mm=bounds.ylen,
                module_thickness_mm=bounds.zlen,
                module_top_z_mm=bounds.zmax,
                lid_underside_z_mm=cavity_top,
                clearance_mm=_RETAINER_CLEARANCE_MM + design.hole_compensation_mm / 2,
            ),
        ),
        "clips",
        None,
    )


def _add_display_posts(
    lid: cq.Workplane,
    display: DisplaySpec,
    holes: BoardHolePattern,
    bounds: cq.BoundBox,
    design: EnclosureDesign,
    cavity_top: float,
) -> cq.Workplane:
    """Posts from the lid down to the display's PCB, over its holes."""

    fastener = get_fastener(design.display_fastener)

    if fastener.clearance_hole_mm > holes.hole_diameter_mm:
        raise ValueError(
            f"{fastener.identifier} screws do not fit the display's "
            f"{holes.hole_diameter_mm} mm holes; choose a smaller display_fastener"
        )

    center_x = (bounds.xmin + bounds.xmax) / 2
    center_y = (bounds.ymin + bounds.ymax) / 2

    return add_display_posts(
        lid,
        parameters=DisplayPostParameters(
            positions=tuple((center_x + x, center_y + y) for x, y in holes.positions),
            pcb_face_z_mm=bounds.zmax - (display.panel_thickness_mm or 0.0),
            lid_underside_z_mm=cavity_top,
            pilot_hole_mm=fastener.tap_hole_mm + design.hole_compensation_mm,
            outer_diameter_mm=fastener.tap_hole_mm + 2 * _DISPLAY_POST_WALL_MM,
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
    """The smallest cavity whose corner bosses, and lid skirt if it has one,
    clear the hardware, the board's supports, and the cable opening, with
    its X and Y clearances."""

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

        if _opening_hits_boss(
            _openings(spec, design, assembly, board_identifier),
            design,
            fastener,
            positions,
        ):
            continue

        blockers: list[cq.Shape] = [
            cq.Solid.makeCylinder(
                radius, spec.inner_height_mm, pnt=cq.Vector(x, y, spec.bottom_z_mm)
            )
            for x, y in positions
        ]

        if design.skirt_depth_mm is not None:
            blockers.append(
                _all_solids(skirt(_cavity(spec, design), design.skirt_depth_mm))
            )

        if all(
            intersection_volume(blocker, obstacle) <= _INTERFERENCE_TOLERANCE_MM3
            for blocker in blockers
            for obstacle in obstacles
        ):
            return spec, (
                _MINIMUM_SIDE_CLEARANCE_MM + widen_x,
                _MINIMUM_SIDE_CLEARANCE_MM + widen_y,
            )

    raise ValueError("No side clearance clears the corner bosses; set one")


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
    board_identifier: str,
) -> list[ConnectorCutoutParameters]:
    """The cable opening, and one for each board part reached through a
    wall, such as a barrel jack."""

    openings = [_cable_opening(spec, design)]
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
        openings.append(
            ConnectorCutoutParameters(
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
        )

    return openings


def _bounds(assembly: DeviceAssembly, identifier: str) -> cq.BoundBox:
    return _all_solids(assembly.get(identifier).transformed_geometry()).BoundingBox()


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
    none for a snap-fit lid."""

    if design.lid_attachment == "snap":
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
    if not positions:
        return lid

    holes = (
        cq.Workplane("XY")
        .pushPoints(list(positions))
        .circle((fastener.clearance_hole_mm + design.hole_compensation_mm) / 2)
        .extrude(design.lid_mm + 2.0)
        .translate((0, 0, cavity_top - 1.0))
    )

    return lid.cut(holes)


def _lid_options_in_base(
    base: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
    openings: list[ConnectorCutoutParameters],
) -> cq.Workplane:
    """Cut the snap grooves and the vents into the walls."""

    if design.lid_attachment == "snap":
        base = base.cut(snap_grooves(cavity))

    if design.vent_slots:
        skirt = design.skirt_depth_mm
        base = base.cut(
            vents(
                cavity,
                slots_per_wall=design.vent_slots,
                blocked_edges=[opening.edge for opening in openings],
                top_z_mm=cavity.top_z_mm
                - (skirt + 1.0 if skirt is not None else VENT_RIM_MM),
                corner_keepout_mm=(
                    2 * _boss_radius(fastener, design) + 1.0 if positions else 3.0
                ),
            )
        )

    return base


def _lid_options_in_lid(
    lid: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
    openings: list[ConnectorCutoutParameters],
) -> cq.Workplane:
    """Countersink the screw holes and hang the lip or snap skirt."""

    if design.countersunk_screws:
        lid = lid.cut(
            countersinks(
                positions,
                hole_diameter_mm=fastener.clearance_hole_mm
                + design.hole_compensation_mm,
                head_diameter_mm=2 * fastener.nominal_diameter_mm
                + _COUNTERSINK_HEAD_ALLOWANCE_MM,
                lid_top_z_mm=cavity.top_z_mm + design.lid_mm,
                lid_thickness_mm=design.lid_mm,
            )
        )

    depth = design.skirt_depth_mm

    if depth is None:
        return lid

    body = skirt(cavity, depth)

    if design.lid_attachment == "snap":
        body = body.union(snap_ridges(cavity)).cut(relief_slits(cavity))

    return lid.union(
        notch_skirt(
            body,
            boss_positions=positions,
            boss_radius_mm=_boss_radius(fastener, design),
            openings=openings,
            cavity=cavity,
            depth_mm=depth,
        )
    )


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
