"""A fan bay: a round opening with a guard, and four holes to mount a fan.

The fan sits inside the enclosure, its frame flat against the inside of the
lid or of a long wall, and is screwed from outside: a screw passes through a
clearance hole in the plate and into a hole in the fan's frame, as a case fan
is. The opening is round, 90 per cent of the frame, and crossed by a guard of
hex cells 5 mm across flats, with webs 1.2 mm thick, so a finger cannot reach
the blades. The guard is made with the same cells as the vents, kept clear of
anything in the plate.

The bay is planned first, against the base and the parts inside, and cut
later, once the lid is made; the plan carries the fan's body, which the rest
of the build treats as a part: swept with a hinged lid, refused by a sliding
one, and never opened onto by a vent.

Which way the fan blows is recorded and changes no geometry: mount it with
the airflow arrow on its frame the way the design says.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.lid_hinge import EDGE_SIGN, hinge_edges, wall_anchor
from zcad_core.features.vent_patterns import (
    LID_INSET_MM,
    CellSpec,
    LidZone,
    VentFill,
    WallZone,
    cell_area,
    cell_fits,
    cut_fill,
    grid,
    solid_tester,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import FanSpec, FastenerSpec

FAN_POSITIONS = ("lid", "wall")
FAN_DIRECTIONS = ("in", "out")
# The guard's cells, in millimetres across flats: small enough to keep a finger
# out of the blades.
GUARD_CELL_MM = 5.0
# The fan's frame keeps this far inside the lid's footprint or the wall's band.
FAN_MARGIN_MM = 3.0
_SCREW_LENGTHS_MM = (4, 5, 6, 8, 10, 12, 16, 20, 25, 30)
# How much of the frame's depth a screw may reach into it.
_FRAME_BITE_REDUCTION_MM = 2.0


@dataclass(frozen=True)
class FanPlan:
    """Where a fan goes, and its body, before the plate is cut."""

    fan: FanSpec
    position: str
    direction: str
    edge: str | None
    zone: LidZone | WallZone
    center: tuple[float, float]
    body: cq.Shape
    # For a wall fan, a stand-in for the opening it makes, so the hinge, the
    # catch, the slide, and the vents treat that wall as taken.
    opening: ConnectorCutoutParameters | None


@dataclass(frozen=True)
class FanReport:
    """What the fan bay came out as."""

    fan: str
    model: str
    position: str
    direction: str
    wall: str | None
    opening_mm: float
    opening_area_mm2: float
    guard_cells: int
    guard_free_mm2: float
    screws: str
    airflow_free_air_m3h: float | None
    power_typical_w: float | None
    other_openings_mm2: float
    datasheet_read: bool

    @property
    def open_ratio(self) -> float:
        return self.guard_free_mm2 / self.opening_area_mm2

    @property
    def air_path(self) -> bool:
        """Whether the other openings pass at least what the guard does, so
        the fan has somewhere to draw from or push to."""

        return self.other_openings_mm2 >= self.guard_free_mm2

    def to_dict(self) -> dict[str, Any]:
        return {
            "fan": self.fan,
            "model": self.model,
            "position": self.position,
            "wall": self.wall,
            "direction": self.direction,
            "opening_mm": round(self.opening_mm, 1),
            "guard_cells": self.guard_cells,
            "guard_free_mm2": round(self.guard_free_mm2, 1),
            "open_ratio": round(self.open_ratio, 2),
            "screws": self.screws,
            "airflow_free_air_m3h": self.airflow_free_air_m3h,
            "power_typical_w": (
                None if self.power_typical_w is None else round(self.power_typical_w, 3)
            ),
            "other_openings_mm2": round(self.other_openings_mm2, 1),
            "air_path": self.air_path,
            "datasheet_read": self.datasheet_read,
            "note": (
                "The airflow is the maker's free-air figure and is not credited "
                "in the temperature estimate; mount the fan with its airflow "
                "arrow pointing "
                + ("into" if self.direction == "in" else "out of")
                + " the box."
                + (
                    ""
                    if self.air_path
                    else " The other openings pass less than the guard does: add "
                    "vents so the fan has somewhere to draw from or push to."
                )
                + (
                    ""
                    if self.datasheet_read
                    else " The fan's figures were not read from the maker's own "
                    "page; check them."
                )
            ),
        }


def _free_long_wall(
    cavity: Cavity, openings: Sequence[ConnectorCutoutParameters]
) -> str:
    """The long wall that carries no opening, the back one if both are free."""

    return hinge_edges(cavity, openings)[0]


def _mount_points(
    center: tuple[float, float], spacing: float
) -> list[tuple[float, float]]:
    half = spacing / 2

    return [
        (center[0] + du * half, center[1] + dv * half)
        for du in (-1, 1)
        for dv in (-1, 1)
    ]


def plan_fan(
    base: cq.Workplane,
    cavity: Cavity,
    *,
    fan: FanSpec,
    position: str,
    direction: str,
    lid_mm: float,
    offset_mm: tuple[float, float],
    openings: Sequence[ConnectorCutoutParameters],
    wall_top_z_mm: float,
    hardware: Mapping[str, cq.Shape],
    display_bounds: cq.BoundBox | None,
) -> FanPlan:
    """Place a fan, refusing a place where it does not fit or would hit
    something. ``offset_mm`` moves it from the middle of the lid, or along the
    wall and up it from the middle of the wall's usable height."""

    if position not in FAN_POSITIONS:
        raise ValueError(f"fan_position must be one of {FAN_POSITIONS}")

    if direction not in FAN_DIRECTIONS:
        raise ValueError(f"fan_direction must be one of {FAN_DIRECTIONS}")

    size = fan.size_mm
    need = size + 2 * FAN_MARGIN_MM
    zone: LidZone | WallZone
    edge: str | None = None
    opening: ConnectorCutoutParameters | None = None

    if position == "lid":
        zone = LidZone(cavity, lid_mm=lid_mm, inset_mm=LID_INSET_MM)
        u0, u1, v0, v1 = zone.region

        if u1 - u0 < size or v1 - v0 < size:
            raise ValueError(
                f"The {fan.model} is {size:.0f} mm square and the lid has "
                f"{u1 - u0:.0f} x {v1 - v0:.0f} mm clear of its edges"
            )

        center = (
            cavity.center_x_mm + offset_mm[0],
            cavity.center_y_mm + offset_mm[1],
        )

        if not (
            u0 <= center[0] - size / 2
            and center[0] + size / 2 <= u1
            and v0 <= center[1] - size / 2
            and center[1] + size / 2 <= v1
        ):
            raise ValueError(
                f"The {fan.model} would reach past the lid's usable area; "
                "move it with fan_offset_mm"
            )

        if display_bounds is not None and _overlaps(center, size, display_bounds):
            raise ValueError(
                f"The display is under the {fan.model}; a fan there would "
                "draw no air. Move the fan with fan_offset_mm"
            )
    else:
        edge = _free_long_wall(cavity, openings)
        bottom = cavity.floor_z_mm + FAN_MARGIN_MM
        top = wall_top_z_mm - FAN_MARGIN_MM

        if top - bottom < size:
            raise ValueError(
                f"The wall is {top - bottom + 2 * FAN_MARGIN_MM:.1f} mm tall and a "
                f"{size:.0f} mm fan needs {need:.1f} mm"
            )

        zone = WallZone(edge, cavity, v_range=(bottom, top), keepout_mm=0.0)
        long_side = cavity.wall_length(edge)

        if long_side - 2 * FAN_MARGIN_MM < size:
            raise ValueError(
                f"The {fan.model} is {size:.0f} mm square and the wall is "
                f"{long_side:.0f} mm long"
            )

        center = (offset_mm[0], (bottom + top) / 2 + offset_mm[1])

        if abs(center[0]) + size / 2 > long_side / 2 - FAN_MARGIN_MM or not (
            bottom <= center[1] - size / 2 and center[1] + size / 2 <= top
        ):
            raise ValueError(
                f"The {fan.model} would reach past the wall's usable area; "
                "move it with fan_offset_mm"
            )

        anchor = wall_anchor(edge, cavity)
        along = center[0] * EDGE_SIGN[edge]
        opening = ConnectorCutoutParameters(
            edge=edge,  # type: ignore[arg-type]
            center_offset_mm=(
                anchor[0] + along if edge.endswith("_y") else anchor[1] + along
            ),
            bottom_z_mm=center[1] - size / 2,
            width_mm=size,
            height_mm=size,
            width_clearance_mm=0.0,
            height_clearance_mm=0.0,
        )

    body = zone.body(center[0], center[1], size, fan.thickness_mm)
    _require_clear(body, fan, base, hardware, position)

    return FanPlan(
        fan=fan,
        position=position,
        direction=direction,
        edge=edge,
        zone=zone,
        center=center,
        body=body,
        opening=opening,
    )


def _overlaps(center: tuple[float, float], size: float, bounds: cq.BoundBox) -> bool:
    return (
        center[0] - size / 2 < bounds.xmax
        and bounds.xmin < center[0] + size / 2
        and center[1] - size / 2 < bounds.ymax
        and bounds.ymin < center[1] + size / 2
    )


def _solids(model: cq.Workplane) -> cq.Shape:
    return cq.Compound.makeCompound(
        [
            solid
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for solid in item.Solids()
        ]
    )


def _require_clear(
    body: cq.Shape,
    fan: FanSpec,
    base: cq.Workplane,
    hardware: Mapping[str, cq.Shape],
    position: str,
) -> None:
    """Refuse a fan whose frame would meet the base or a part inside."""

    for name, shape in {"the base": _solids(base), **hardware}.items():
        overlap = intersection_volume(body, shape)

        if overlap > 1e-6:
            raise ValueError(
                f"The {fan.model} would hit {name} ({overlap:.0f} mm3); move it "
                "with fan_offset_mm, choose a smaller fan"
                + (
                    ", raise top_clearance_mm so it sits above the parts, or use "
                    "a snap lid, which has no corner bosses"
                    if position == "lid"
                    else ", or make the box deeper"
                )
            )


def screw_length_mm(plate_mm: float, fan: FanSpec) -> int:
    """The longest standard screw that stops short of the frame's far face."""

    reach = plate_mm + fan.thickness_mm - _FRAME_BITE_REDUCTION_MM
    fitting = [length for length in _SCREW_LENGTHS_MM if length <= reach]

    if not fitting:
        raise ValueError(f"No standard screw is short enough for {reach:.1f} mm")

    return fitting[-1]


def _guard(plan: FanPlan, plate: Any) -> VentFill:
    """The guard's cells: hex cells whole inside the round opening, in plate."""

    fan = plan.fan
    radius = fan.opening_diameter_mm / 2
    spec = CellSpec("hex", GUARD_CELL_MM, 0.0)
    reach = GUARD_CELL_MM / math.sqrt(3.0)
    u, v = plan.center
    region = (u - radius, u + radius, v - radius, v + radius)
    is_solid = solid_tester(plate)
    centers = [
        c
        for c in grid(spec, region)
        if math.hypot(c[0] - u, c[1] - v) + reach <= radius
        and cell_fits(plan.zone, spec, c, is_solid)
    ]

    if not centers:
        raise ValueError(f"No guard cell fits in the {fan.model}'s opening")

    return VentFill(spec, tuple(centers), len(centers) * cell_area(spec, wall=True))


def cut_fan_bay(
    model: cq.Workplane,
    plan: FanPlan,
    *,
    plate_mm: float,
    screw: FastenerSpec,
    hole_compensation_mm: float,
) -> tuple[cq.Workplane, VentFill]:
    """Cut the guard and the four mounting holes into the lid or the base."""

    fan = plan.fan
    points = _mount_points(plan.center, fan.hole_spacing_mm)
    is_solid = solid_tester(model)

    for u, v in points:
        for depth in (0.3, plate_mm / 2):
            if not is_solid(plan.zone.point(u, v, depth)):
                raise ValueError(
                    f"A mounting hole for the {fan.model} would fall on a gap in "
                    "the plate; move it with fan_offset_mm"
                )

    guard = _guard(plan, model)
    model = cut_fill(model, plan.zone, guard)
    radius = (screw.clearance_hole_mm + hole_compensation_mm) / 2
    model = model.cut(cq.Workplane("XY").add(plan.zone.drill(points, radius)))

    return model, guard


def fan_report(
    plan: FanPlan,
    guard: VentFill,
    *,
    plate_mm: float,
    screw: FastenerSpec,
    openings: Sequence[ConnectorCutoutParameters],
    vent_free_mm2: float,
) -> FanReport:
    """What the bay came out as, once the vents are known too."""

    fan = plan.fan
    others = sum(o.opening_width_mm * o.opening_height_mm for o in openings)

    return FanReport(
        fan=fan.identifier,
        model=f"{fan.maker} {fan.model}",
        position=plan.position,
        direction=plan.direction,
        wall=plan.edge,
        opening_mm=fan.opening_diameter_mm,
        opening_area_mm2=math.pi * (fan.opening_diameter_mm / 2) ** 2,
        guard_cells=len(guard.centers),
        guard_free_mm2=guard.area_mm2,
        screws=f"{screw.identifier} x {screw_length_mm(plate_mm, fan)} mm, 4",
        airflow_free_air_m3h=fan.airflow_m3h,
        power_typical_w=fan.typical_w,
        other_openings_mm2=others + vent_free_mm2,
        datasheet_read=fan.source.read,
    )
