"""The enclosure's lid, and the lid options that follow from the base and the lid."""

from __future__ import annotations

import cadquery as cq

from zcad_core.assemblies import EnclosureSpecification
from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_cooling import _vent_corner_keepout, _vent_top_z
from zcad_core.features.enclosure_geometry import _boss_radius
from zcad_core.features.enclosure_lid import (
    Cavity,
    countersinks,
    notch_skirt,
    relief_slits,
    skirt,
    snap_grooves,
    snap_ridges,
    vents,
)
from zcad_core.features.enclosure_model import EnclosureDesign
from zcad_core.hardware import FastenerSpec

# A flat-head screw's head is about twice its thread (ISO 10642 M3: 6 mm).
_COUNTERSINK_HEAD_ALLOWANCE_MM = 0.0


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
        base = base.cut(
            vents(
                cavity,
                slots_per_wall=design.vent_slots,
                blocked_edges=[opening.edge for opening in openings],
                top_z_mm=_vent_top_z(cavity, design),
                corner_keepout_mm=_vent_corner_keepout(fastener, design, positions),
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
