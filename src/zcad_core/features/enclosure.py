"""Build a printable two-part enclosure around a board-and-display assembly.

The base carries the floor, walls, board supports, a heat-set insert boss in
each corner, and the cable opening; the lid carries screw clearance holes
over the bosses and the display window. A board with mounting holes sits on
standoffs; one without sits in a snap-in cradle. Both parts are derived from
the assembly through
:func:`~zcad_core.assemblies.derive_enclosure_specification`, and the
builder refuses to return an enclosure whose features intersect any part of
the assembly.

This module holds the builder itself, :func:`build_enclosure`, which puts the
parts together. What it uses is in layers, each importing only from those
above it:

- ``enclosure_model``: :class:`EnclosureDesign` and :class:`Enclosure`, which
  are data;
- ``enclosure_geometry``: the cavity, the corner bosses, the shell and the
  board's supports, which the others share;
- ``enclosure_openings``: the cable's opening and those a board declares;
- ``enclosure_specification``: the fixed specification and the automatic side
  clearance;
- ``enclosure_cooling``: the thermal estimate, a fan's bay and the lid's vents;
- ``enclosure_display``, ``enclosure_lid_build``: the display's features, and
  the lid and its options;
- ``enclosure_checks``: the refusals.

The design and result types stay importable from here.
"""

from __future__ import annotations

from pathlib import Path

from zcad_core.assemblies import DeviceAssembly
from zcad_core.features.enclosure_checks import (
    _require_clear_of_assembly,
    _require_parts_clear,
    _require_stack_top_possible,
)
from zcad_core.features.enclosure_cooling import (
    _cut_fan,
    _cut_lid_vents,
    _finish_cooling,
    _plan_cooling,
    _thermal_estimate,
)
from zcad_core.features.enclosure_display import _add_display_features
from zcad_core.features.enclosure_geometry import (
    _add_board_support,
    _cavity,
    _clear_parts_under_board,
    _compensated_boss,
    _corner_boss_positions,
    _corner_fills,
    _shell,
)
from zcad_core.features.enclosure_lid_build import (
    _lid,
    _lid_options_in_base,
    _lid_options_in_lid,
)
from zcad_core.features.enclosure_model import (
    _FLOOR_EMBED_MM,
    HOLE_COMPENSATION_RANGE_MM,
    LID_ATTACHMENTS,
    Enclosure,
    EnclosureDesign,
)
from zcad_core.features.enclosure_openings import _cut_openings, _openings
from zcad_core.features.enclosure_specification import (
    _automatic_specification,
    _specification,
)
from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.features.lid_hinge import add_hinge
from zcad_core.features.lid_slide import add_slide
from zcad_core.features.mount_stack import (
    TopHolding,
    build_stack_top,
    latch_sides,
    lid_openings,
    plain_lid,
)
from zcad_core.features.mounts import (
    add_mount_pads,
    build_mount,
    mount_pads,
    require_mount_clear,
)
from zcad_core.features.stack_profile import load_profile
from zcad_core.hardware import BoardSpec, DisplaySpec, get_fastener

# Kept importable from here: the builder's public types.
__all__ = [
    "HOLE_COMPENSATION_RANGE_MM",
    "LID_ATTACHMENTS",
    "Enclosure",
    "EnclosureDesign",
    "build_enclosure",
]


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

    if design.stack_top:
        _require_stack_top_possible(design)

    if design.side_clearance_mm is None:
        spec, side_clearance = _automatic_specification(
            assembly,
            design=design,
            fastener=fastener,
            board_identifier=board_identifier,
            connector_identifier=connector_identifier,
            display_identifier=display_identifier if display is not None else None,
            board=board,
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
    openings = _openings(spec, design, assembly, board, board_identifier)
    base = _cut_openings(base, openings, design, fastener, positions)
    cavity = _cavity(spec, design)
    base = _lid_options_in_base(base, cavity, design, fastener, positions, openings)
    base, cooling = _plan_cooling(
        base,
        cavity,
        design,
        assembly,
        display,
        display_identifier,
        openings,
        fastener,
        positions,
    )
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

    lid = _cut_lid_vents(
        lid, assembly, board_identifier, display_identifier, cavity_top, design
    )
    base, lid, guard = _cut_fan(base, lid, cooling, design)

    hinge = None

    if design.lid_attachment == "hinge":
        base, lid, hinge = add_hinge(
            base,
            lid,
            cavity,
            lid_mm=design.lid_mm,
            pin=get_fastener(design.hinge_pin),
            hole_compensation_mm=design.hole_compensation_mm,
            openings=cooling.feature_openings,
            hardware=cooling.shapes,
            carried=cooling.carried,
        )

    slide = None

    if design.lid_attachment == "slide":
        base, lid, slide = add_slide(
            base,
            lid,
            cavity,
            lid_mm=design.lid_mm,
            clearance_mm=design.slide_clearance_mm,
            hole_compensation_mm=design.hole_compensation_mm,
            openings=cooling.feature_openings,
            hardware=cooling.shapes,
            carried=cooling.carried,
        )

    lid, vents_report, fan_summary = _finish_cooling(
        lid, cavity, design, cooling, openings, guard
    )

    pads = None
    mount = None

    if design.mount is not None:
        half_x = spec.inner_width_mm / 2 + design.wall_mm
        half_y = spec.inner_depth_mm / 2 + design.wall_mm
        pads = mount_pads(
            x_span_mm=(spec.center_x_mm - half_x, spec.center_x_mm + half_x),
            y_span_mm=(spec.center_y_mm - half_y, spec.center_y_mm + half_y),
            floor_underside_z_mm=spec.bottom_z_mm - design.floor_mm,
            floor_mm=design.floor_mm,
            wall_mm=design.wall_mm,
            fastener=fastener,
            hole_compensation_mm=design.hole_compensation_mm,
        )
        base = add_mount_pads(base, pads)
        mount = build_mount(
            design.mount,
            pads,
            fastener=fastener,
            plate_mm=design.mount_plate_mm,
            hole_compensation_mm=design.hole_compensation_mm,
            stack_profile=(
                load_profile(Path(design.stack_profile))
                if design.stack_profile
                else None
            ),
        )
        require_mount_clear(base, mount)

    stack_top = None

    if design.stack_top and design.stack_profile:
        lid_size = (
            spec.inner_width_mm + 2 * design.wall_mm,
            spec.inner_depth_mm + 2 * design.wall_mm,
        )
        lid_windows = lid_openings(
            lid,
            plain_lid(
                (spec.center_x_mm, spec.center_y_mm),
                lid_size,
                cavity_top,
                design.lid_mm,
                positions,
                fastener.clearance_hole_mm + design.hole_compensation_mm,
            ),
            cavity_top,
            cavity_top + design.lid_mm,
        )
        stack_top = build_stack_top(
            positions,
            centre=(spec.center_x_mm, spec.center_y_mm),
            lid_size_mm=(
                spec.inner_width_mm + 2 * design.wall_mm,
                spec.inner_depth_mm + 2 * design.wall_mm,
            ),
            lid_top_z_mm=cavity_top + design.lid_mm,
            lid_mm=design.lid_mm,
            fastener=fastener,
            profile=load_profile(Path(design.stack_profile)),
            compensation=design.hole_compensation_mm,
            openings=lid_windows,
            holding=TopHolding(
                design.stack_top_holding,
                design.stack_top_magnet or "",
                latch_sides(design.stack_top_latch),
                design.stack_top_engagement_mm,
                design.slide_clearance_mm,
            ),
        )

    _require_clear_of_assembly(assembly, base=base, lid=lid)
    _require_parts_clear(base, lid)
    thermal = _thermal_estimate(
        base, lid, assembly, board=board, display=display, design=design
    )

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
        mount_pads=pads,
        mount=mount,
        stack_top=stack_top,
        hinge=hinge,
        slide=slide,
        thermal=thermal,
        vents=vents_report,
        fan=fan_summary,
        fan_body=cooling.fan_plan.body if cooling.fan_plan else None,
    )
