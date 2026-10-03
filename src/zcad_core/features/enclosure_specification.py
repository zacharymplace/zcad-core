"""The enclosure's specification: the fixed one, and the automatic side
clearance that widens X and Y until the corner bosses clear the hardware.
"""

from __future__ import annotations

from dataclasses import replace

import cadquery as cq

from zcad_core.assemblies import (
    DeviceAssembly,
    EnclosureSpecification,
    derive_enclosure_specification,
)
from zcad_core.features.enclosure_geometry import (
    _INTERFERENCE_TOLERANCE_MM3,
    _all_solids,
    _boss_obstacles,
    _boss_radius,
    _cavity,
    _corner_boss_positions,
)
from zcad_core.features.enclosure_lid import skirt
from zcad_core.features.enclosure_model import EnclosureDesign
from zcad_core.features.enclosure_openings import _opening_hits_boss, _openings
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import BoardSpec, FastenerSpec

# An automatic side clearance starts at the minimum and widens X and Y
# independently in steps, taking the smallest footprint that works. Bosses
# must also clear the board outline grown by the support margin, so
# standoffs and cradle clips never fuse to a boss.
_MINIMUM_SIDE_CLEARANCE_MM = 2.0


# A hinged lid swings what hangs from it toward the closure wall by about
# b^2 / 2a, for b below the axis and a from it: 1 mm or so for a display's
# retainer, so the walls stand a millimetre further off.
_HINGE_SIDE_CLEARANCE_MM = 3.0


_AUTOMATIC_WIDENING_MM = tuple(0.5 * step for step in range(25))


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
    board: BoardSpec,
) -> tuple[EnclosureSpecification, tuple[float, float]]:
    """The smallest cavity whose corner bosses, and lid skirt if it has one,
    clear the hardware, the board's supports, and the cable opening, with
    its X and Y clearances."""

    obstacles = _boss_obstacles(assembly, board_identifier, display_identifier)
    radius = _boss_radius(fastener, design)
    minimum = _specification(
        assembly, design, _minimum_side_clearance(design), connector_identifier
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
            _openings(spec, design, assembly, board, board_identifier),
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
                _minimum_side_clearance(design) + widen_x,
                _minimum_side_clearance(design) + widen_y,
            )

    raise ValueError("No side clearance clears the corner bosses; set one")


def _minimum_side_clearance(design: EnclosureDesign) -> float:
    return (
        _HINGE_SIDE_CLEARANCE_MM
        if design.lid_attachment == "hinge"
        else _MINIMUM_SIDE_CLEARANCE_MM
    )
