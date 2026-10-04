"""A group enclosure's lid: how it is attached, its vents, and the openings it must keep
clear of a hinge's knuckles.
"""

from __future__ import annotations

import cadquery as cq

from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_group_envelope import make_box
from zcad_core.features.enclosure_group_model import BayLayout, GroupDesign
from zcad_core.features.enclosure_group_modules import BayModule
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.lid_hinge import HINGE_WEB_DEPTH_MM, HingeReport, add_hinge
from zcad_core.features.lid_slide import SlideReport, add_slide
from zcad_core.hardware import FastenerSpec, RaspberryPi5Spec, get_fastener

_VENT_SLOTS = 5


_VENT_PITCH_MM = 5.0


_VENT_LENGTH_MM = 30.0


_VENT_WIDTH_MM = 2.4


def _attach_lid(
    base: cq.Workplane,
    lid: cq.Workplane,
    *,
    design: GroupDesign,
    outer: tuple[float, float, float],
    inner_size: tuple[float, float],
    cavity_top: float,
    openings: list[ConnectorCutoutParameters],
    hardware: dict[str, cq.Shape],
    carried: dict[str, cq.Shape],
) -> tuple[cq.Workplane, cq.Workplane, HingeReport | None, SlideReport | None]:
    """Hinge or slide the lid, as the design asks; a screwed lid is left as it
    is. Both are the single-board builders on the group's cavity, and refuse a
    lid that cannot swing or slide clear of the base and the Pis."""

    if design.lid_attachment == "screws":
        return base, lid, None, None

    cavity = Cavity(
        center_x_mm=outer[0] / 2,
        center_y_mm=outer[1] / 2,
        width_mm=inner_size[0],
        depth_mm=inner_size[1],
        floor_z_mm=design.floor_mm,
        top_z_mm=cavity_top,
        wall_mm=design.wall_mm,
    )

    if design.lid_attachment == "hinge":
        _require_openings_clear_of_knuckles(openings, cavity_top)
        front = [opening for opening in openings if opening.edge == "negative_y"]
        base, lid, hinge = add_hinge(
            base,
            lid,
            cavity,
            lid_mm=design.lid_mm,
            pin=get_fastener(design.hinge_pin),
            hole_compensation_mm=0.0,
            openings=front,
            hardware=hardware,
            carried=carried,
            hinge_edge="positive_y",
        )

        return base, lid, hinge, None

    if not cavity.long_walls_on_y:
        raise ValueError(
            "A sliding lid runs along the row, which must be at least as wide as "
            "it is deep; add a bay, or use a hinged or screwed lid"
        )

    base, lid, slide = add_slide(
        base,
        lid,
        cavity,
        lid_mm=design.lid_mm,
        clearance_mm=design.slide_clearance_mm,
        hole_compensation_mm=0.0,
        openings=openings,
        hardware=hardware,
        carried=carried,
        entry=design.slide_entry,
    )

    return base, lid, None, slide


def _require_openings_clear_of_knuckles(
    openings: list[ConnectorCutoutParameters], cavity_top: float
) -> None:
    """The hinge's knuckles stand on the back wall's top edge, so no back-wall
    opening may reach it."""

    limit = cavity_top - HINGE_WEB_DEPTH_MM

    for opening in openings:
        top = opening.bottom_z_mm + opening.opening_height_mm

        if opening.edge == "positive_y" and top > limit:
            raise ValueError(
                f"A back-wall opening reaches {top:.1f} mm and the hinge's knuckles "
                f"need the wall above {limit:.1f} mm; raise headroom_mm by at "
                f"least {top - limit:.1f} mm, lower the opening, or use a "
                "sliding or screwed lid"
            )


def _vent_centres(
    layouts: tuple[BayLayout, ...],
    modules: tuple[BayModule | None, ...],
    pi: RaspberryPi5Spec,
    wall: float,
) -> list[tuple[float, float]]:
    """Where the lid's slots go: over each Pi's fan, and over each part of a board
    that draws air from above."""

    centres: list[tuple[float, float]] = []

    for layout, module in zip(layouts, modules, strict=True):
        if layout.holds_pi:
            centres.append(
                (
                    wall + layout.center_x_mm + pi.fan_center_x_mm,
                    layout.center_y_mm + pi.fan_center_y_mm,
                )
            )
        elif module is not None:
            centres.extend(
                (wall + layout.center_x_mm + x, layout.center_y_mm + y)
                for x, y in module.vents
            )

    return centres


def _lid(
    outer: tuple[float, float, float],
    *,
    wall: float,
    design: GroupDesign,
    cavity_top: float,
    fastener: FastenerSpec,
    boss_positions: tuple[tuple[float, float], ...],
    layouts: tuple[BayLayout, ...],
    modules: tuple[BayModule | None, ...],
    pi: RaspberryPi5Spec,
) -> cq.Workplane:
    """A plate over the walls, a clearance hole over each boss, and vent
    slots over each Pi's SoC and cooler."""

    lid = (
        cq.Workplane("XY")
        .box(outer[0], outer[1], design.lid_mm, centered=False)
        .translate((0, 0, cavity_top))
    )

    if boss_positions:
        holes = (
            cq.Workplane("XY")
            .pushPoints(list(boss_positions))
            .circle(fastener.clearance_hole_mm / 2)
            .extrude(design.lid_mm + 2.0)
            .translate((0, 0, cavity_top - 1.0))
        )
        lid = lid.cut(holes)

    if not design.vents:
        return lid

    centres = _vent_centres(layouts, modules, pi, wall)

    for fan_x, fan_y in centres:
        for index in range(_VENT_SLOTS):
            offset = (index - (_VENT_SLOTS - 1) / 2) * _VENT_PITCH_MM
            lid = lid.cut(
                make_box(
                    (
                        fan_x - _VENT_LENGTH_MM / 2,
                        fan_x + _VENT_LENGTH_MM / 2,
                    ),
                    (
                        fan_y + offset - _VENT_WIDTH_MM / 2,
                        fan_y + offset + _VENT_WIDTH_MM / 2,
                    ),
                    (cavity_top - 1.0, cavity_top + design.lid_mm + 1.0),
                )
            )

    return lid
