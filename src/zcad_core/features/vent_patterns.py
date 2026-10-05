"""Vent patterns sized to a free area: slots, hex grids, round holes, louvers.

``--vent-slots`` cuts a fixed number of fixed slots. This module cuts a pattern
sized to a free area instead. A pattern fills a zone, a rectangle on a wall or
on the lid, with cells on a grid whose webs are at least ``MIN_WEB_MM`` thick;
it takes the smallest cells that reach the target, so the holes stay as small
as the area allows.

Where a cell may go is decided against the finished solids, not against a list
of keep-outs. A cell is kept only when the plate is solid all round it (so it
never meets an opening, a screw hole, a window, a slit, or an edge) and when
nothing hangs behind it (so it never opens onto a boss, a standoff, a post, or
a clip). That finds every feature that is already there, including those that
later features add, without anyone having to list them.

Inlets are cells in the walls, low; outlets are cells in the lid, high. A hole
through a wall is drawn as a teardrop, pointed at the top, and a hex with a
flat top, whose roof is a bridge a few millimetres long and whose other edges
are 60 degrees from level, so none overhangs by more than 45 degrees.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Literal, cast

import cadquery as cq

from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.lid_hinge import EDGE_ANGLE, wall_anchor

PATTERNS = ("slots", "hex", "round", "louvers")
MIN_WEB_MM = 1.2
MAX_CELLS = 400
# Cells in a wall start this far above the floor.
WALL_FLOOR_RIM_MM = 1.5
WALL_BAND_MM = 12.0
# The lid's vents stay this far inside the cavity's footprint.
LID_INSET_MM = 3.0
# A louver slopes down to the outside at 45 degrees across a wall about this
# thick. Its height is measured square to the slant, as is its web, and its
# free area is counted at the cosine of that slant, a loss for the turn.
_LOUVER_LENGTH_MM = 14.0
_LOUVER_WALL_MM = 2.0
_COS_45 = math.cos(math.radians(45.0))
_CHECK_RING = 8
_BEHIND_MM = (1.0, 2.5)

Kind = Literal["slots", "hex", "round", "louvers"]


@dataclass(frozen=True)
class CellSpec:
    """One size of cell: ``width`` along the zone, ``height`` across it."""

    kind: str
    width_mm: float
    height_mm: float

    def describe(self) -> str:
        if self.kind == "round":
            return f"round holes, {self.width_mm:g} mm"

        if self.kind == "hex":
            return f"hex cells, {self.width_mm:g} mm across flats"

        if self.kind == "louvers":
            return f"louvers, {self.height_mm:g} mm slots, {self.width_mm:g} mm long"

        return f"slots, {self.width_mm:g} mm wide, {self.height_mm:g} mm long"


@dataclass(frozen=True)
class VentFill:
    """The cells a zone took, and the free area they give."""

    spec: CellSpec
    centers: tuple[tuple[float, float], ...]
    area_mm2: float


@dataclass(frozen=True)
class VentReport:
    """What the vents came out as."""

    pattern: str
    target_mm2: float
    inlet_mm2: float
    outlet_mm2: float
    inlet_cells: int
    outlet_cells: int
    inlet: str
    outlet: str

    @property
    def outlet_not_smaller(self) -> bool:
        return self.outlet_mm2 >= self.inlet_mm2

    def to_dict(self) -> dict[str, object]:
        return {
            "pattern": self.pattern,
            "target_mm2": self.target_mm2,
            "inlet_mm2": round(self.inlet_mm2, 1),
            "outlet_mm2": round(self.outlet_mm2, 1),
            "inlet_cells": self.inlet_cells,
            "outlet_cells": self.outlet_cells,
            "inlet": self.inlet,
            "outlet": self.outlet,
            "outlet_not_smaller": self.outlet_not_smaller,
            "note": (
                "Free areas of the cells cut; the temperature estimate credits "
                "no vents."
            ),
        }


# ----------------------------- cell profiles -------------------------------


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    total = 0.0

    for (x0, y0), (x1, y1) in zip(points, [*points[1:], points[0]]):
        total += x0 * y1 - x1 * y0

    return abs(total) / 2


def _circle(radius: float, *, teardrop: bool) -> list[tuple[float, float]]:
    """A circle as a polygon; for a hole through a wall, with its top drawn
    as a 45 degree point so it prints without support."""

    steps = 24

    if not teardrop:
        return [
            (
                radius * math.cos(2 * math.pi * i / steps),
                radius * math.sin(2 * math.pi * i / steps),
            )
            for i in range(steps)
        ]

    points = [(0.0, radius * math.sqrt(2.0))]

    # From the right-hand tangent point round the bottom to the left-hand one.
    for i in range(steps - 5):
        angle = math.radians(45.0 - i * 360.0 / steps)
        points.append((radius * math.cos(angle), radius * math.sin(angle)))

    return points


def _hex(across_flats: float) -> list[tuple[float, float]]:
    """A hexagon with a flat top and bottom and a vertex at each side: a
    pointed top would have a roof only 30 degrees from level."""

    circumradius = across_flats / math.sqrt(3.0)

    return [
        (
            circumradius * math.cos(math.radians(60.0 * i)),
            circumradius * math.sin(math.radians(60.0 * i)),
        )
        for i in range(6)
    ]


def _profile(spec: CellSpec, *, wall: bool) -> list[tuple[float, float]]:
    w, h = spec.width_mm, spec.height_mm

    if spec.kind == "round":
        return _circle(spec.width_mm / 2, teardrop=wall)

    if spec.kind == "hex":
        return _hex(spec.width_mm)

    return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]


def cell_area(spec: CellSpec, *, wall: bool) -> float:
    if spec.kind == "louvers":
        return _COS_45 * spec.width_mm * spec.height_mm

    return _polygon_area(_profile(spec, wall=wall))


# ------------------------------- the grids ---------------------------------


def _gap(a: Sequence[tuple[float, float]], b: Sequence[tuple[float, float]]) -> float:
    """The least distance between two polygons that do not overlap: from each
    one's vertices to the other's edges."""

    def to_segment(
        p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]
    ) -> float:
        dx, dy = r[0] - q[0], r[1] - q[1]
        length = dx * dx + dy * dy
        t = (
            0.0
            if length == 0
            else max(0.0, min(1.0, ((p[0] - q[0]) * dx + (p[1] - q[1]) * dy) / length))
        )

        return math.hypot(p[0] - q[0] - t * dx, p[1] - q[1] - t * dy)

    def one_way(
        c: Sequence[tuple[float, float]], d: Sequence[tuple[float, float]]
    ) -> float:
        return min(
            to_segment(point, d[i], d[(i + 1) % len(d)])
            for point in c
            for i in range(len(d))
        )

    return min(one_way(a, b), one_way(b, a))


@functools.cache
def _teardrop_pitch(width_mm: float) -> float:
    """The least pitch along a row of staggered teardrops that keeps the web to
    every neighbour, the next in its row and the two in the row above, at least
    ``MIN_WEB_MM``: a teardrop's point stands r * sqrt(2) above its centre, so a
    circle's pitch leaves the web from a point to the cells beside it too thin."""

    shape = _circle(width_mm / 2, teardrop=True)
    pitch = width_mm + MIN_WEB_MM

    while True:
        rise = pitch * math.sqrt(3.0) / 2
        neighbours = ((pitch, 0.0), (pitch / 2, rise), (-pitch / 2, rise))

        if all(
            _gap(shape, [(x + du, y + dv) for x, y in shape]) >= MIN_WEB_MM - 1e-9
            for du, dv in neighbours
        ):
            return round(pitch, 3)

        pitch += 0.01


def _pitch(spec: CellSpec, *, wall: bool = False) -> tuple[float, float, bool]:
    """Centre-to-centre spacing along and across a zone, and whether
    alternate rows are offset. A round cell in a wall is a teardrop."""

    if spec.kind == "round":
        pitch = _teardrop_pitch(spec.width_mm) if wall else spec.width_mm + MIN_WEB_MM

        return pitch, pitch * math.sqrt(3.0) / 2, True

    if spec.kind == "louvers":
        return (
            spec.width_mm + MIN_WEB_MM,
            (spec.height_mm + MIN_WEB_MM) / _COS_45,
            False,
        )

    return spec.width_mm + MIN_WEB_MM, spec.height_mm + MIN_WEB_MM, False


def _extent(spec: CellSpec, *, wall: bool = False) -> tuple[float, float]:
    """How far a cell reaches from its centre along and across the zone. A
    teardrop's point reaches r * sqrt(2) up; it is taken that far both ways, so
    the band and the solid ring round it hold the point as well."""

    if spec.kind == "round" and wall:
        return spec.width_mm / 2, spec.width_mm / 2 * math.sqrt(2.0)

    if spec.kind == "hex":
        return spec.width_mm / math.sqrt(3.0), spec.width_mm / 2

    if spec.kind == "louvers":
        return spec.width_mm / 2, spec.height_mm / _COS_45 / 2 + _LOUVER_WALL_MM

    return spec.width_mm / 2, spec.height_mm / 2


def grid(
    spec: CellSpec, region: tuple[float, float, float, float], *, wall: bool = False
) -> list[tuple[float, float]]:
    """Cell centres that fit entirely inside ``region``, as
    ``(u0, u1, v0, v1)``, centred in it."""

    if spec.kind == "hex":
        return _honeycomb(spec, region)

    u0, u1, v0, v1 = region
    pitch_u, pitch_v, stagger = _pitch(spec, wall=wall)
    reach_u, reach_v = _extent(spec, wall=wall)
    span_u = u1 - u0 - 2 * reach_u - (pitch_u / 2 if stagger else 0.0)
    span_v = v1 - v0 - 2 * reach_v

    if span_u < 0 or span_v < 0:
        return []

    columns = int(span_u // pitch_u) + 1
    rows = int(span_v // pitch_v) + 1
    width = (columns - 1) * pitch_u + (pitch_u / 2 if stagger else 0.0)
    start_u = (u0 + u1) / 2 - width / 2
    start_v = (v0 + v1) / 2 - (rows - 1) * pitch_v / 2
    centers = []

    for row in range(rows):
        shift = pitch_u / 2 if stagger and row % 2 else 0.0

        for column in range(columns):
            centers.append(
                (start_u + column * pitch_u + shift, start_v + row * pitch_v)
            )

    return centers


def _honeycomb(
    spec: CellSpec, region: tuple[float, float, float, float]
) -> list[tuple[float, float]]:
    """Flat-top hexagons: columns a bit under a pitch apart along the zone,
    each with its cells a pitch apart, alternate columns shifted by half."""

    u0, u1, v0, v1 = region
    pitch = spec.width_mm + MIN_WEB_MM
    pitch_u = pitch * math.sqrt(3.0) / 2
    reach_u, reach_v = _extent(spec)
    span_u = u1 - u0 - 2 * reach_u
    span_v = v1 - v0 - 2 * reach_v - pitch / 2

    if span_u < 0 or span_v < 0:
        return []

    columns = int(span_u // pitch_u) + 1
    rows = int(span_v // pitch) + 1
    start_u = (u0 + u1) / 2 - (columns - 1) * pitch_u / 2
    start_v = (v0 + v1) / 2 - ((rows - 1) * pitch + pitch / 2) / 2
    centers = []

    for column in range(columns):
        shift = pitch / 2 if column % 2 else 0.0

        for row in range(rows):
            centers.append((start_u + column * pitch_u, start_v + row * pitch + shift))

    return centers


# --------------------------------- zones -----------------------------------


class Zone:
    """A rectangle on a wall or the lid that vents may fill."""

    name: str
    wall: bool
    region: tuple[float, float, float, float]
    thickness_mm: float

    def point(self, u: float, v: float, depth: float) -> cq.Vector:
        """A point at ``(u, v)`` and ``depth`` in from the outer face."""
        raise NotImplementedError

    def cutters(
        self, spec: CellSpec, centers: Sequence[tuple[float, float]]
    ) -> cq.Shape:
        raise NotImplementedError


class WallZone(Zone):
    """A strip of one long wall. ``u`` runs along it from its centre and ``v``
    is the height."""

    def __init__(
        self,
        edge: str,
        cavity: Cavity,
        *,
        v_range: tuple[float, float],
        keepout_mm: float,
    ) -> None:
        self.name = f"the {edge} wall"
        self.wall = True
        self.edge = edge
        self.cavity = cavity
        self.thickness_mm = cavity.wall_mm
        half = cavity.wall_length(edge) / 2 + cavity.wall_mm - keepout_mm
        self.region = (-half, half, v_range[0], v_range[1])
        self._anchor = wall_anchor(edge, cavity)
        self._angle = EDGE_ANGLE[edge]

    def _to_world(self, x: float, y: float, z: float) -> cq.Vector:
        angle = math.radians(self._angle)
        return cq.Vector(
            self._anchor[0] + x * math.cos(angle) - y * math.sin(angle),
            self._anchor[1] + x * math.sin(angle) + y * math.cos(angle),
            z,
        )

    def point(self, u: float, v: float, depth: float) -> cq.Vector:
        return self._to_world(u, -depth, v)

    def _place(self, shape: cq.Shape) -> cq.Shape:
        return shape.rotate((0, 0, 0), (0, 0, 1), self._angle).translate(
            cq.Vector(self._anchor[0], self._anchor[1], 0.0)
        )

    def drill(self, points: Sequence[tuple[float, float]], radius: float) -> cq.Shape:
        wall = self.thickness_mm
        holes = [
            cq.Solid.makeCylinder(
                radius,
                wall + 2.0,
                pnt=cq.Vector(u, -wall - 1.0, v),
                dir=cq.Vector(0, 1, 0),
            )
            for u, v in points
        ]

        return self._place(cq.Compound.makeCompound(holes))

    def body(self, u: float, v: float, size: float, thickness: float) -> cq.Shape:
        wall = self.thickness_mm
        block = cq.Solid.makeBox(
            size,
            thickness,
            size,
            pnt=cq.Vector(u - size / 2, -wall - thickness, v - size / 2),
        )

        return self._place(block)

    def cutters(
        self, spec: CellSpec, centers: Sequence[tuple[float, float]]
    ) -> cq.Shape:
        wall = self.thickness_mm
        solids: list[cq.Shape] = []

        for u, v in centers:
            if spec.kind == "louvers":
                solids.append(_louver(spec, u, v, wall))
                continue

            profile = [(u + x, v + y) for x, y in _profile(spec, wall=True)]
            body = (
                cq.Workplane("XZ")
                .polyline(profile)
                .close()
                .extrude(wall + 2.0)
                .translate((0.0, 1.0, 0.0))
            )
            solids.extend(body.vals())  # type: ignore[arg-type]

        compound = cq.Compound.makeCompound(solids)

        return compound.rotate((0, 0, 0), (0, 0, 1), self._angle).translate(
            (self._anchor[0], self._anchor[1], 0.0)
        )


def _louver(spec: CellSpec, u: float, v: float, wall: float) -> cq.Shape:
    """A slanted slot through a wall, sloping down to the outside at 45
    degrees, so rain cannot blow straight in."""

    h = spec.height_mm / _COS_45 / 2
    points = [
        (-wall - 1.0, v - h + 1.0),
        (1.0, v - h - wall - 1.0),
        (1.0, v + h - wall - 1.0),
        (-wall - 1.0, v + h + 1.0),
    ]
    body = (
        cq.Workplane("YZ")
        .polyline(points)
        .close()
        .extrude(spec.width_mm)
        .translate((u - spec.width_mm / 2, 0.0, 0.0))
    )

    return body.val()  # type: ignore[return-value]


class LidZone(Zone):
    """The lid over the cavity. ``u`` is X and ``v`` is Y."""

    def drill(self, points: Sequence[tuple[float, float]], radius: float) -> cq.Shape:
        height = self.thickness_mm + 1.0
        holes = [
            cq.Solid.makeCylinder(
                radius, height, pnt=cq.Vector(u, v, self.cavity.top_z_mm - 0.5)
            )
            for u, v in points
        ]

        return cq.Compound.makeCompound(holes)

    def body(self, u: float, v: float, size: float, thickness: float) -> cq.Shape:
        return cq.Solid.makeBox(
            size,
            size,
            thickness,
            pnt=cq.Vector(u - size / 2, v - size / 2, self.cavity.top_z_mm - thickness),
        )

    def __init__(self, cavity: Cavity, *, lid_mm: float, inset_mm: float) -> None:
        self.name = "the lid"
        self.wall = False
        self.cavity = cavity
        self.thickness_mm = lid_mm
        half_x = cavity.width_mm / 2 - inset_mm
        half_y = cavity.depth_mm / 2 - inset_mm
        self.region = (
            cavity.center_x_mm - half_x,
            cavity.center_x_mm + half_x,
            cavity.center_y_mm - half_y,
            cavity.center_y_mm + half_y,
        )
        self._top = cavity.top_z_mm + lid_mm

    def point(self, u: float, v: float, depth: float) -> cq.Vector:
        return cq.Vector(u, v, self._top - depth)

    def cutters(
        self, spec: CellSpec, centers: Sequence[tuple[float, float]]
    ) -> cq.Shape:
        height = self.thickness_mm + 1.0
        solids: list[cq.Shape] = []

        for u, v in centers:
            profile = [(u + x, v + y) for x, y in _profile(spec, wall=False)]
            body = (
                cq.Workplane("XY")
                .polyline(profile)
                .close()
                .extrude(height)
                .translate((0.0, 0.0, self.cavity.top_z_mm - 0.5))
            )
            solids.extend(body.vals())  # type: ignore[arg-type]

        return cq.Compound.makeCompound(solids)


# ------------------------------ sizing a fill -------------------------------

_LADDERS: dict[tuple[str, bool], tuple[CellSpec, ...]] = {
    ("slots", True): tuple(CellSpec("slots", w, 10.0) for w in (1.6, 2.0, 2.4, 3.0)),
    ("slots", False): tuple(CellSpec("slots", w, 16.0) for w in (2.4, 3.0, 4.0)),
    ("hex", True): tuple(CellSpec("hex", d, 0.0) for d in (4.0, 5.0, 6.0, 8.0)),
    ("hex", False): tuple(CellSpec("hex", d, 0.0) for d in (4.0, 5.0, 6.0, 8.0)),
    ("round", True): tuple(CellSpec("round", d, d) for d in (4.0, 5.0, 6.0, 8.0)),
    ("round", False): tuple(
        CellSpec("round", d, d) for d in (4.0, 5.0, 6.0, 8.0, 10.0)
    ),
    ("louvers", True): tuple(
        CellSpec("louvers", _LOUVER_LENGTH_MM, h) for h in (2.0, 2.5, 3.0)
    ),
}


def _ring(zone: Zone, u: float, v: float, spec: CellSpec) -> list[tuple[float, float]]:
    """The cell's centre and eight points on an ellipse a web's width outside
    it, which must all lie in solid plate."""

    reach_u, reach_v = _extent(spec, wall=zone.wall)
    points = [(u, v)]

    for step in range(_CHECK_RING):
        angle = 2 * math.pi * step / _CHECK_RING
        points.append(
            (
                u + (reach_u + MIN_WEB_MM / 2) * math.cos(angle),
                v + (reach_v + MIN_WEB_MM / 2) * math.sin(angle),
            )
        )

    return points


def cell_fits(
    zone: Zone,
    spec: CellSpec,
    center: tuple[float, float],
    is_solid: Callable[[cq.Vector], bool],
    behind_solid: Callable[[cq.Vector], bool] | None = None,
) -> bool:
    """Whether a cell can go here: the plate solid all round it, and nothing
    behind it."""

    u, v = center
    thickness = zone.thickness_mm
    # Solid all round, near each face as well as through the middle, so a
    # countersink or a chamfer beside the cell is found too.
    depths = (0.3, thickness / 2, thickness - 0.3)

    for pu, pv in _ring(zone, u, v, spec):
        for depth in depths:
            if not is_solid(zone.point(pu, pv, depth)):
                return False

    # Nothing behind the cell, out to a little past its edge all round.
    reach_u, reach_v = (r + 0.3 for r in _extent(spec, wall=zone.wall))
    behind = [(u, v)]

    for du, dv in (
        (1.0, 0.0),
        (-1.0, 0.0),
        (0.0, 1.0),
        (0.0, -1.0),
        (0.7, 0.7),
        (-0.7, 0.7),
        (0.7, -0.7),
        (-0.7, -0.7),
    ):
        behind.append((u + du * reach_u, v + dv * reach_v))

    in_the_way = behind_solid or is_solid

    for depth in _BEHIND_MM:
        for pu, pv in behind:
            if in_the_way(zone.point(pu, pv, zone.thickness_mm + depth)):
                return False

    return True


def fill_zone(
    zone: Zone,
    kind: str,
    target_mm2: float,
    *,
    is_solid: Callable[[cq.Vector], bool],
    behind_solid: Callable[[cq.Vector], bool] | None = None,
) -> VentFill:
    """The smallest cells of ``kind`` that reach ``target_mm2`` of free area in
    the zone, taken from the middle of it outward, where they fit."""

    ladder = _LADDERS.get((kind, zone.wall))

    if ladder is None:
        raise ValueError(f"{kind} vents are for walls, not {zone.name}")

    u0, u1, v0, v1 = zone.region
    middle = ((u0 + u1) / 2, (v0 + v1) / 2)
    best: VentFill | None = None

    for rung in ladder:
        # A slot is no taller than the band it stands in.
        spec = (
            replace(rung, height_mm=min(rung.height_mm, v1 - v0))
            if rung.kind == "slots"
            else rung
        )

        if spec.kind == "slots" and spec.height_mm < 3.0:
            continue

        area = cell_area(spec, wall=zone.wall)
        candidates = sorted(
            grid(spec, zone.region, wall=zone.wall),
            key=lambda c: (c[0] - middle[0]) ** 2 + (c[1] - middle[1]) ** 2,
        )
        chosen: list[tuple[float, float]] = []

        for center in candidates:
            if cell_fits(zone, spec, center, is_solid, behind_solid):
                chosen.append(center)

                if len(chosen) * area >= target_mm2:
                    break

        fill = VentFill(spec, tuple(chosen), len(chosen) * area)

        if fill.area_mm2 >= target_mm2 and len(chosen) <= MAX_CELLS:
            return fill

        if best is None or fill.area_mm2 > best.area_mm2:
            best = fill

    most = best.area_mm2 if best else 0.0

    if most == 0.0:
        raise ValueError(
            f"No {kind} cell fits in {zone.name}: its band is {v1 - v0:.1f} mm "
            f"high and {u1 - u0:.1f} mm long, and the cells are kept clear of "
            "anything behind or beside them"
        )

    raise ValueError(
        f"{kind} vents in {zone.name} can pass at most {most:.0f} mm2 where they "
        f"fit; {target_mm2:.0f} mm2 was asked"
    )


def cut_fill(model: cq.Workplane, zone: Zone, fill: VentFill) -> cq.Workplane:
    """Cut a fill's cells through a wall or the lid, refusing a cut that would
    split the part."""

    if not fill.centers:
        return model

    before = len(model.solids().vals())
    cut = model.cut(cq.Workplane("XY").add(zone.cutters(fill.spec, fill.centers)))

    if len(cut.solids().vals()) != before:
        raise ValueError(
            f"The {fill.spec.describe()} in {zone.name} would split it in two"
        )

    return cut


def add_wall_inlets(
    base: cq.Workplane,
    cavity: Cavity,
    *,
    kind: str,
    target_mm2: float,
    blocked_edges: Sequence[str],
    top_z_mm: float,
    corner_keepout_mm: float,
    obstruction: cq.Shape | None = None,
    edges: Sequence[str] | None = None,
) -> tuple[cq.Workplane, list[VentFill]]:
    """Inlets low in each wall of ``edges`` (the long walls, by default) that
    carries no opening, sharing the target between them; none opens onto
    ``obstruction``, such as a fan."""

    walls = [
        edge for edge in (edges or cavity.long_edges()) if edge not in blocked_edges
    ]

    if not walls:
        raise ValueError(
            "Every wall that could take the inlets carries an opening; there is "
            "nowhere to vent"
        )

    bottom = cavity.floor_z_mm + WALL_FLOOR_RIM_MM
    top = min(bottom + WALL_BAND_MM, top_z_mm)

    if top - bottom < 3.0:
        raise ValueError(
            "The walls are too low for vent inlets below the lid's features; "
            "raise bottom_clearance_mm or the parts' height"
        )

    is_solid = solid_tester(base)
    fills = []

    for edge in walls:
        zone = WallZone(
            edge, cavity, v_range=(bottom, top), keepout_mm=corner_keepout_mm
        )
        share = target_mm2 / len(walls)

        try:
            fill = fill_zone(
                zone,
                kind,
                share,
                is_solid=is_solid,
                behind_solid=_with(is_solid, obstruction),
            )
        except ValueError as error:
            if len(walls) > 1:
                raise ValueError(
                    f"{error} (the {target_mm2:.0f} mm2 is shared between "
                    f"{len(walls)} walls)"
                ) from error

            raise
        base = cut_fill(base, zone, fill)
        fills.append(fill)

    return base, fills


def add_lid_outlets(
    lid: cq.Workplane,
    cavity: Cavity,
    *,
    lid_mm: float,
    kind: str,
    target_mm2: float,
    obstruction: cq.Shape | None = None,
) -> tuple[cq.Workplane, VentFill]:
    """Outlets through the lid, where it is plain plate and nothing, such as a
    fan's frame, stands behind it."""

    zone = LidZone(cavity, lid_mm=lid_mm, inset_mm=LID_INSET_MM)
    plate = solid_tester(lid)
    fill = fill_zone(
        zone,
        kind,
        target_mm2,
        is_solid=plate,
        behind_solid=_with(plate, obstruction),
    )

    return cut_fill(lid, zone, fill), fill


def _with(
    test: Callable[[cq.Vector], bool], extra: cq.Shape | None
) -> Callable[[cq.Vector], bool] | None:
    """A point test that also counts a shape, or ``None`` to use the plate's."""

    if extra is None:
        return None

    inside = _inside_any([cast(cq.Solid, extra)])

    return lambda point: test(point) or inside(point)


def solid_tester(model: cq.Workplane) -> Callable[[cq.Vector], bool]:
    """A point-in-material test against a model's solids."""

    return _inside_any(
        [
            solid
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for solid in item.Solids()
        ]
    )


# A point this far outside a solid's bounding box is outside the solid; the margin
# is far wider than the classifier's own tolerance, so a point on a face still
# goes to the classifier.
_BOX_MARGIN_MM = 1e-3


def _inside_any(solids: Sequence[cq.Solid]) -> Callable[[cq.Vector], bool]:
    """A point-in-material test against solids, asking each solid's classifier
    only when the point is inside its bounding box: the classifier costs about a
    millisecond and most points are nowhere near most solids."""

    boxes = []

    for solid in solids:
        box = solid.BoundingBox()
        boxes.append(
            (
                solid,
                box.xmin - _BOX_MARGIN_MM,
                box.xmax + _BOX_MARGIN_MM,
                box.ymin - _BOX_MARGIN_MM,
                box.ymax + _BOX_MARGIN_MM,
                box.zmin - _BOX_MARGIN_MM,
                box.zmax + _BOX_MARGIN_MM,
            )
        )

    def inside(point: cq.Vector) -> bool:
        x, y, z = point.x, point.y, point.z

        return any(
            x0 <= x <= x1
            and y0 <= y <= y1
            and z0 <= z <= z1
            and bool(solid.isInside(point))
            for solid, x0, x1, y0, y1, z0, z1 in boxes
        )

    return inside
