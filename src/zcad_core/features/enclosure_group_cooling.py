"""Cooling a group enclosure: the vents in its walls and lid, and a fan's cut-outs."""

from __future__ import annotations

import cadquery as cq

from zcad_core.features.enclosure_group_model import Bay, BayLayout, GroupDesign
from zcad_core.features.enclosure_lid import VENT_RIM_MM, Cavity
from zcad_core.features.fan_bay import FanPlan, cut_fan_bay, plan_fan
from zcad_core.features.vent_patterns import (
    VentFill,
    VentReport,
    add_lid_outlets,
    add_wall_inlets,
)
from zcad_core.hardware import get_fan, get_fastener


def _add_vents(
    base: cq.Workplane,
    lid: cq.Workplane,
    *,
    design: GroupDesign,
    outer: tuple[float, float, float],
    inner_size: tuple[float, float],
    cavity_top: float,
    keepout_mm: float,
) -> tuple[cq.Workplane, cq.Workplane, VentReport | None]:
    """Inlets low in the two side walls and outlets in the lid, sized to the
    design's free area. The long walls are the front and back, which carry the
    Pis' openings; the side walls carry only the row's join features, which the
    cells keep clear of."""

    if not design.vent_area_mm2:
        return base, lid, None

    wall = design.wall_mm
    cavity = Cavity(
        center_x_mm=outer[0] / 2,
        center_y_mm=outer[1] / 2,
        width_mm=inner_size[0],
        depth_mm=inner_size[1],
        floor_z_mm=design.floor_mm,
        top_z_mm=cavity_top,
        wall_mm=wall,
    )
    base, inlets = add_wall_inlets(
        base,
        cavity,
        kind=design.vent_pattern,
        target_mm2=design.vent_area_mm2,
        blocked_edges=[],
        # The slide's entry wall comes down to the groove floor, a clearance
        # below the lid, so the inlets stop that much lower.
        top_z_mm=cavity_top
        - VENT_RIM_MM
        - (design.slide_clearance_mm if design.lid_attachment == "slide" else 0.0),
        corner_keepout_mm=keepout_mm,
        edges=("negative_x", "positive_x"),
    )
    inlet_mm2 = sum(fill.area_mm2 for fill in inlets)
    # Louvers are for walls, so the lid takes slots.
    kind = "slots" if design.vent_pattern == "louvers" else design.vent_pattern
    lid, outlet = add_lid_outlets(
        lid,
        cavity,
        lid_mm=design.lid_mm,
        kind=kind,
        target_mm2=max(design.vent_area_mm2, inlet_mm2),
    )

    return (
        base,
        lid,
        VentReport(
            pattern=design.vent_pattern,
            target_mm2=design.vent_area_mm2,
            inlet_mm2=inlet_mm2,
            outlet_mm2=outlet.area_mm2,
            inlet_cells=sum(len(fill.centers) for fill in inlets),
            outlet_cells=len(outlet.centers),
            inlet=inlets[0].spec.describe(),
            outlet=outlet.spec.describe(),
        ),
    )


def _cut_fans(
    base: cq.Workplane,
    lid: cq.Workplane,
    *,
    specs: tuple[Bay, ...],
    layouts: tuple[BayLayout, ...],
    design: GroupDesign,
    outer: tuple[float, float, float],
    inner_size: tuple[float, float],
    cavity_top: float,
    hardware: dict[str, cq.Shape],
) -> tuple[cq.Workplane, dict[str, cq.Shape], list[tuple[FanPlan, VentFill]]]:
    """Each fan bay's fan: its frame flat against the lid's inside over the bay's
    middle, and the guarded opening and four screw holes in the lid. The frames
    go with the lid, so the hinge and the slide carry them."""

    cavity = Cavity(
        center_x_mm=outer[0] / 2,
        center_y_mm=outer[1] / 2,
        width_mm=inner_size[0],
        depth_mm=inner_size[1],
        floor_z_mm=design.floor_mm,
        top_z_mm=cavity_top,
        wall_mm=design.wall_mm,
    )
    bodies: dict[str, cq.Shape] = {}
    cuts: list[tuple[FanPlan, VentFill]] = []

    for bay, layout in zip(specs, layouts, strict=True):
        if bay.kind != "fan":
            continue

        fan = get_fan(str(bay.fan))
        label = f"bay {layout.index} (fan)"

        try:
            plan = plan_fan(
                base,
                cavity,
                fan=fan,
                position="lid",
                direction=bay.fan_direction,
                lid_mm=design.lid_mm,
                offset_mm=(
                    design.wall_mm + layout.center_x_mm - cavity.center_x_mm,
                    layout.center_y_mm - cavity.center_y_mm,
                ),
                openings=[],
                wall_top_z_mm=cavity_top,
                hardware={**hardware, **bodies},
                display_bounds=None,
            )
            lid, guard = cut_fan_bay(
                lid,
                plan,
                plate_mm=design.lid_mm,
                screw=get_fastener(fan.screw),
                hole_compensation_mm=0.0,
            )
        except ValueError as error:
            raise ValueError(f"{label}: {error}") from error

        bodies[f"bay-{layout.index}"] = plan.body
        cuts.append((plan, guard))

    return lid, bodies, cuts


def _drawn_mm2(vents: VentReport | None, direction: str) -> float:
    """The vents on the far side of a lid fan's airflow: the lid outlets when
    it blows in, the wall inlets when it draws out, as the single enclosure."""

    if vents is None:
        return 0.0

    return vents.outlet_mm2 if direction == "in" else vents.inlet_mm2
