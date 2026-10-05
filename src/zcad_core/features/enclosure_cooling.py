"""Cooling an enclosure: the thermal estimate, a fan's bay, and the lid's vents."""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.assemblies import DeviceAssembly
from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_geometry import _all_solids, _boss_radius, _bounds
from zcad_core.features.enclosure_lid import VENT_RIM_MM, Cavity
from zcad_core.features.enclosure_model import EnclosureDesign
from zcad_core.features.enclosure_thermal import (
    ThermalEstimate,
    estimate_thermal,
    require_not_too_hot,
)
from zcad_core.features.fan_bay import (
    FanPlan,
    FanReport,
    cut_fan_bay,
    fan_report,
    plan_fan,
)
from zcad_core.features.lid_hinge import hinge_web_depth_mm
from zcad_core.features.lid_slide import SLIDE_VENT_DROP_MM
from zcad_core.features.vent_patterns import (
    VentFill,
    VentReport,
    add_lid_outlets,
    add_wall_inlets,
)
from zcad_core.geometry.boxes import box_between
from zcad_core.hardware import (
    BoardSpec,
    DisplaySpec,
    FastenerSpec,
    get_fan,
    get_fastener,
)

# Slots through the lid over a part that draws air from above, such as a
# cooler's fan, as the group enclosure's.
_LID_VENT_WIDTH_MM = 2.4


_LID_VENT_PITCH_MM = 5.0


def _is_closed(design: EnclosureDesign, assembly: DeviceAssembly) -> bool:
    """Whether the box has nothing that moves air: no vent, no fan, and no
    lid slots over a part that draws air from above."""

    lid_slots = any(
        component.metadata.get("lid_vent") for component in assembly.components
    )

    return not (design.vent_slots or design.vent_area_mm2 or design.fan or lid_slots)


def _thermal_estimate(
    base: cq.Workplane,
    lid: cq.Workplane,
    assembly: DeviceAssembly,
    *,
    board: BoardSpec,
    display: DisplaySpec | None,
    design: EnclosureDesign,
) -> ThermalEstimate:
    """Estimate the closed box, refusing one too hot unless allowed."""

    box = _all_solids(base).BoundingBox()
    cap = _all_solids(lid).BoundingBox()
    size = (
        max(box.xmax, cap.xmax) - min(box.xmin, cap.xmin),
        max(box.ymax, cap.ymax) - min(box.ymin, cap.ymin),
        max(box.zmax, cap.zmax) - min(box.zmin, cap.zmin),
    )
    parts = [board.identifier]

    if display is not None:
        parts.append(display.identifier)

    if design.fan:
        parts.append(design.fan)

    # A fitted Active Cooler is one more source of heat, its fan; the catalog
    # has no figure for it, so the estimate names it as unknown.
    for component in assembly.components:
        hardware = component.metadata.get("hardware_identifier")

        if hardware and str(hardware).endswith(":active-cooler-fan"):
            parts.append(str(hardware))

    estimate = estimate_thermal(
        parts,
        outer_size_mm=size,
        declared_power_w=design.declared_power_w,
        ambient_c=design.ambient_c,
        limit_c=design.service_limit_c,
        coefficient_w_m2k=design.convection_w_m2k,
        coefficient_source=design.convection_source,
        closed=_is_closed(design, assembly),
        # A board from a file may bring its own power figure.
        figures=(
            {board.identifier: figure}
            if (figure := getattr(board, "power_figure", None)) is not None
            else None
        ),
    )
    require_not_too_hot(estimate, allow_hot=design.allow_hot)

    return estimate


@dataclass
class _Cooling:
    """What the fan and the wall vents leave for the rest of the build: the
    parts inside, and those the lid carries, for the hinge and slide to sweep;
    the openings that take a wall; and the fan's plan and the inlets cut."""

    shapes: dict[str, cq.Shape]
    carried: dict[str, cq.Shape]
    feature_openings: list[ConnectorCutoutParameters]
    fan_plan: FanPlan | None
    inlets: list[VentFill]


def _plan_cooling(
    base: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    assembly: DeviceAssembly,
    display: DisplaySpec | None,
    display_identifier: str,
    openings: list[ConnectorCutoutParameters],
    fastener: FastenerSpec,
    positions: tuple[tuple[float, float], ...],
) -> tuple[cq.Workplane, _Cooling]:
    """Place the fan, if there is one, and cut the wall inlets, if there are
    any; nothing is cut in the lid yet."""

    shapes = {
        component.identifier: _all_solids(component.transformed_geometry())
        for component in assembly.components
        if component.identifier != display_identifier
    }
    # A display screws to the lid's posts, so it goes where the lid does.
    carried = (
        {
            display_identifier: _all_solids(
                assembly.get(display_identifier).transformed_geometry()
            )
        }
        if display is not None
        else {}
    )
    cooling = _Cooling(shapes, carried, list(openings), None, [])

    if design.fan:
        plan = plan_fan(
            base,
            cavity,
            fan=get_fan(design.fan),
            position=design.fan_position,
            direction=design.fan_direction,
            lid_mm=design.lid_mm,
            offset_mm=(design.fan_offset_x_mm, design.fan_offset_y_mm),
            openings=openings,
            wall_top_z_mm=_vent_top_z(cavity, design),
            hardware={**shapes, **carried},
            display_bounds=(
                _bounds(assembly, display_identifier) if display is not None else None
            ),
        )
        cooling.fan_plan = plan

        # A fan in a wall takes that wall, as an opening does, and is fixed;
        # one in the lid goes where the lid goes.
        if plan.opening is not None:
            cooling.feature_openings.append(plan.opening)
            shapes["fan"] = plan.body
        else:
            carried["fan"] = plan.body

    if design.vent_area_mm2:
        base, cooling.inlets = add_wall_inlets(
            base,
            cavity,
            kind=design.vent_pattern,
            target_mm2=design.vent_area_mm2,
            blocked_edges=[opening.edge for opening in cooling.feature_openings],
            top_z_mm=_vent_top_z(cavity, design),
            corner_keepout_mm=_vent_corner_keepout(fastener, design, positions),
            obstruction=cooling.fan_plan.body
            if cooling.fan_plan and cooling.fan_plan.opening
            else None,
        )

    return base, cooling


def _cut_fan(
    base: cq.Workplane,
    lid: cq.Workplane,
    cooling: _Cooling,
    design: EnclosureDesign,
) -> tuple[cq.Workplane, cq.Workplane, VentFill | None]:
    """Cut the fan's guard and mounting holes into the lid or the wall."""

    plan = cooling.fan_plan

    if plan is None:
        return base, lid, None

    screw = get_fastener(plan.fan.screw)

    if plan.position == "lid":
        lid, guard = cut_fan_bay(
            lid,
            plan,
            plate_mm=design.lid_mm,
            screw=screw,
            hole_compensation_mm=design.hole_compensation_mm,
        )
    else:
        base, guard = cut_fan_bay(
            base,
            plan,
            plate_mm=design.wall_mm,
            screw=screw,
            hole_compensation_mm=design.hole_compensation_mm,
        )

    return base, lid, guard


def _finish_cooling(
    lid: cq.Workplane,
    cavity: Cavity,
    design: EnclosureDesign,
    cooling: _Cooling,
    openings: list[ConnectorCutoutParameters],
    guard: VentFill | None,
) -> tuple[cq.Workplane, VentReport | None, FanReport | None]:
    """Cut the outlets in the lid, clear of a fan behind it, and report the
    vents and the fan."""

    plan = cooling.fan_plan
    vents_report = None

    if design.vent_area_mm2:
        inlet_mm2 = sum(fill.area_mm2 for fill in cooling.inlets)
        # The outlets are at least as large as the inlets, and of the same
        # pattern, but never louvers: those are for walls.
        lid, outlet = add_lid_outlets(
            lid,
            cavity,
            lid_mm=design.lid_mm,
            kind="slots" if design.vent_pattern == "louvers" else design.vent_pattern,
            target_mm2=max(design.vent_area_mm2, inlet_mm2),
            obstruction=plan.body if plan and plan.position == "lid" else None,
        )
        vents_report = VentReport(
            pattern=design.vent_pattern,
            target_mm2=design.vent_area_mm2,
            inlet_mm2=inlet_mm2,
            outlet_mm2=outlet.area_mm2,
            inlet_cells=sum(len(fill.centers) for fill in cooling.inlets),
            outlet_cells=len(outlet.centers),
            inlet=cooling.inlets[0].spec.describe(),
            outlet=outlet.spec.describe(),
        )

    if plan is None or guard is None:
        return lid, vents_report, None

    # An intake draws through the outlets and an exhaust through the inlets,
    # so those and the wall openings are what the fan draws on.
    drawn = 0.0

    if vents_report is not None:
        drawn = (
            vents_report.outlet_mm2
            if plan.direction == "in"
            else vents_report.inlet_mm2
        )

    summary = fan_report(
        plan,
        guard,
        plate_mm=design.lid_mm if plan.position == "lid" else design.wall_mm,
        screw=get_fastener(plan.fan.screw),
        openings=openings,
        vent_free_mm2=drawn,
    )

    return lid, vents_report, summary


def _cut_lid_vents(
    lid: cq.Workplane,
    assembly: DeviceAssembly,
    board_identifier: str,
    display_identifier: str,
    cavity_top: float,
    design: EnclosureDesign,
) -> cq.Workplane:
    """Slots through the lid across the footprint of each board part that
    draws air from above; refused where the display would cover them."""

    for component in assembly.components:
        metadata = component.metadata

        if metadata.get("board_identifier") != board_identifier or not metadata.get(
            "lid_vent"
        ):
            continue

        vent = _bounds(assembly, component.identifier)

        if display_identifier in assembly.identifiers:
            display = _bounds(assembly, display_identifier)

            if (
                vent.xmin < display.xmax
                and display.xmin < vent.xmax
                and vent.ymin < display.ymax
                and display.ymin < vent.ymax
            ):
                raise ValueError(
                    f"The display covers the lid vent over '{component.identifier}'; "
                    "a fan under it would draw no air"
                )

        count = int((vent.ylen - _LID_VENT_WIDTH_MM) // _LID_VENT_PITCH_MM) + 1
        middle = (vent.ymin + vent.ymax) / 2

        for index in range(count):
            y = middle + (index - (count - 1) / 2) * _LID_VENT_PITCH_MM
            lid = lid.cut(
                box_between(
                    (vent.xmin, vent.xmax),
                    (y - _LID_VENT_WIDTH_MM / 2, y + _LID_VENT_WIDTH_MM / 2),
                    (cavity_top - 1.0, cavity_top + design.lid_mm + 1.0),
                )
            )

    return lid


def _vent_top_z(cavity: Cavity, design: EnclosureDesign) -> float:
    """The highest a wall vent may reach: below the lid's skirt, and below the
    hinge's webs or the slide's thickening where there are any."""

    skirt = design.skirt_depth_mm

    return cavity.top_z_mm - (
        skirt + 1.0
        if skirt is not None
        else VENT_RIM_MM
        + (
            hinge_web_depth_mm(get_fastener(design.hinge_pin), design.lid_mm)
            if design.lid_attachment == "hinge"
            else 0.0
        )
        + (SLIDE_VENT_DROP_MM if design.lid_attachment == "slide" else 0.0)
    )


def _vent_corner_keepout(
    fastener: FastenerSpec,
    design: EnclosureDesign,
    positions: tuple[tuple[float, float], ...],
) -> float:
    return 2 * _boss_radius(fastener, design) + 1.0 if positions else 3.0
