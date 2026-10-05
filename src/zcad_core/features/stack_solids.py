"""The solids of a stackable item: a bin on its foot with a lip, a baseplate of pockets.

Every item is centred on the origin in ``x`` and ``y``, and rests on ``z == 0``: a bin on
the bottom of its feet, a baseplate on its underside. A cell is one pitch square; a bin's
walls stand on the outline a cell's foot is widest at (the pitch less the profile's gap).

A section is laid out by **lofting** a rounded rectangle from one height to the next, so a
foot, a lip and a pocket are true ruled surfaces and arcs, not faceted.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from itertools import pairwise

import cadquery as cq

from zcad_core.features.stack_profile import StackProfile, inset_at
from zcad_core.geometry.cadquery_support import workplane_shape

# A corner never turns tighter than this, however far in a section reaches.
MINIMUM_RADIUS_MM = 0.2
# A lip is cut off where it comes to a point, leaving a flat this wide: the engine's own
# design choice, a nozzle's width.
LIP_TIP_MM = 0.4
# A baseplate's ridge between two pockets is this wide at the pocket's mouth: also the
# engine's own design choice.
RIDGE_TOP_MM = 0.8
# A divider's thickness, the engine's own design choice.
DIVIDER_MM = 1.2
TAB_ANGLE_RATIO = 1.0
_OPEN_MM = 1.0


def rounded_wire(width: float, depth: float, radius: float, z: float) -> cq.Wire:
    """A rounded rectangle centred on the axis at height ``z``."""

    a, b = width / 2, depth / 2
    r = max(min(radius, a - 1e-6, b - 1e-6), 1e-6)
    corners = (
        ((a - r, -(b - r)), -90.0),
        ((a - r, b - r), 0.0),
        ((-(a - r), b - r), 90.0),
        ((-(a - r), -(b - r)), 180.0),
    )
    edges: list[cq.Edge] = []
    previous: cq.Vector | None = None

    for (cx, cy), start in corners:

        def at(degrees: float, cx: float = cx, cy: float = cy) -> cq.Vector:
            angle = math.radians(degrees)

            return cq.Vector(cx + r * math.cos(angle), cy + r * math.sin(angle), z)

        begin, middle, end = at(start), at(start + 45.0), at(start + 90.0)

        if previous is not None:
            edges.append(cq.Edge.makeLine(previous, begin))

        edges.append(cq.Edge.makeThreePointArc(begin, middle, end))
        previous = end

    if previous is not None:
        edges.append(cq.Edge.makeLine(previous, edges[0].startPoint()))

    return cq.Wire.assembleEdges(edges)


def _loft(low: cq.Wire, high: cq.Wire) -> cq.Solid:
    return cq.Solid.makeLoft([low, high], True)


def chain(
    width: float,
    depth: float,
    radius: float,
    points: Sequence[tuple[float, float]],
    z0: float = 0.0,
) -> cq.Workplane:
    """The solid whose outline, at each point ``(inset, height)``, is the rounded
    rectangle drawn in by ``inset``, lofted from point to point."""

    wires = [
        rounded_wire(
            width - 2 * inset,
            depth - 2 * inset,
            max(radius - inset, MINIMUM_RADIUS_MM),
            z0 + z,
        )
        for inset, z in points
    ]
    solid = cq.Workplane("XY").add(_loft(wires[0], wires[1]))

    for low, high in pairwise(wires[1:]):
        solid = solid.union(cq.Workplane("XY").add(_loft(low, high)))

    return solid


def prism(
    width: float, depth: float, radius: float, z0: float, z1: float
) -> cq.Workplane:
    """A rounded box from ``z0`` to ``z1``."""

    return (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .rect(width, depth)
        .extrude(z1 - z0)
        .edges("|Z")
        .fillet(max(min(radius, width / 2 - 1e-3, depth / 2 - 1e-3), 1e-3))
    )


def cell_centres(cells: tuple[int, int], pitch: float) -> list[tuple[float, float]]:
    nx, ny = cells

    return [
        ((i + 0.5 - nx / 2) * pitch, (j + 0.5 - ny / 2) * pitch)
        for i in range(nx)
        for j in range(ny)
    ]


def truncated_lip(
    lip: Sequence[tuple[float, float]], tip: float = LIP_TIP_MM
) -> list[tuple[float, float]]:
    """The lip cut off where its reach in from the wall falls to ``tip``."""

    kept = [lip[0]]

    for (inset_a, z_a), (inset_b, z_b) in pairwise(lip):
        if inset_b <= tip < inset_a:
            z = z_a + (inset_a - tip) * (z_b - z_a) / (inset_a - inset_b)
            kept.append((tip, z))

            return kept

        kept.append((inset_b, z_b))

    return kept


def foot_solid(profile: StackProfile, centre: tuple[float, float]) -> cq.Workplane:
    """One cell's foot, its bottom on ``z == 0``."""

    top = profile.cell_top_mm

    return chain(top, top, profile.corner_radius_mm, profile.foot).translate(
        (centre[0], centre[1], 0.0)
    )


def bin_solid(
    profile: StackProfile,
    cells: tuple[int, int],
    units: int,
    wall_mm: float,
    floor_mm: float,
) -> tuple[cq.Workplane, float]:
    """A bin, and the height of its walls' tops: ``units`` of the profile's unit, from
    the bottom of the feet."""

    width = cells[0] * profile.pitch_mm - profile.gap_mm
    depth = cells[1] * profile.pitch_mm - profile.gap_mm
    radius = profile.corner_radius_mm
    foot_top = profile.foot_height_mm
    wall_top = units * profile.height_unit_mm
    lip = truncated_lip(profile.lip)
    reach = profile.lip[0][0]
    support = max(reach - wall_mm, 0.0)
    outer = prism(width, depth, radius, foot_top, wall_top + lip[-1][1])

    for centre in cell_centres(cells, profile.pitch_mm):
        outer = outer.union(foot_solid(profile, centre))

    points = [(wall_mm, foot_top + floor_mm), (wall_mm, wall_top - support)]
    points += [(reach, wall_top)] if support else []
    points += [(inset, wall_top + z) for inset, z in lip[1:]]
    points.append((lip[-1][0], wall_top + lip[-1][1] + _OPEN_MM))

    return outer.cut(chain(width, depth, radius, points)), wall_top


def baseplate_solid(
    profile: StackProfile,
    cells: tuple[int, int],
    floor_mm: float,
    rim_mm: float,
    skip: Collection[int] = frozenset(),
) -> tuple[cq.Workplane, float]:
    """A baseplate, and the height of its pocket floor: a plate with a pocket for
    each cell that the profile's foot, with the nest clearance, sits in. A cell whose index is in
    ``skip`` gets no pocket and stays solid, as a stack top's vent cell does."""

    clearance = profile.min_nest_clearance_mm
    ridge_inset = (RIDGE_TOP_MM + 2 * clearance - profile.gap_mm) / 2
    depth_z = _height_at_inset(profile.foot, ridge_inset)
    top = profile.cell_top_mm
    width = cells[0] * profile.pitch_mm + 2 * rim_mm
    length = cells[1] * profile.pitch_mm + 2 * rim_mm
    plate = prism(
        width,
        length,
        profile.corner_radius_mm + clearance + rim_mm,
        0.0,
        floor_mm + depth_z,
    )
    points = [
        (inset_at(profile.foot, z) - clearance, floor_mm + z)
        for z in sorted({z for _, z in profile.foot if z < depth_z} | {0.0, depth_z})
    ]
    points.append((points[-1][0], floor_mm + depth_z + _OPEN_MM))

    for index, centre in enumerate(cell_centres(cells, profile.pitch_mm)):
        if index in skip:
            continue

        pocket = chain(top, top, profile.corner_radius_mm, points).translate(
            (centre[0], centre[1], 0.0)
        )
        plate = plate.cut(pocket)

    return plate, floor_mm


def _height_at_inset(section: Sequence[tuple[float, float]], inset: float) -> float:
    """The height at which a section, on its way out to the wall, reaches ``inset``."""

    for (inset_a, z_a), (inset_b, z_b) in pairwise(section):
        if inset_b <= inset <= inset_a and inset_a > inset_b:
            return z_a + (inset_a - inset) * (z_b - z_a) / (inset_a - inset_b)

    raise ValueError(f"The profile's foot never comes within {inset:g} mm of the wall")


def add_dividers(
    model: cq.Workplane,
    inner: tuple[float, float],
    floor_z: float,
    top_z: float,
    counts: tuple[int, int],
    thickness: float = DIVIDER_MM,
) -> cq.Workplane:
    """``counts[0]`` dividers across the inside along X, and ``counts[1]`` along Y,
    each spanning the inside and sunk into the walls."""

    length, depth = inner
    height = top_z - floor_z

    for index in range(counts[0]):
        x = -length / 2 + (index + 1) * length / (counts[0] + 1)
        model = model.union(
            cq.Workplane("XY")
            .box(thickness, depth + 1.0, height, centered=(True, True, False))
            .translate((x, 0.0, floor_z))
        )

    for index in range(counts[1]):
        y = -depth / 2 + (index + 1) * depth / (counts[1] + 1)
        model = model.union(
            cq.Workplane("XY")
            .box(length + 1.0, thickness, height, centered=(True, True, False))
            .translate((0.0, y, floor_z))
        )

    return model


def add_label_tab(
    model: cq.Workplane, inner: tuple[float, float], top_z: float, tab_mm: float
) -> cq.Workplane:
    """A ledge along the back wall's inside, flush with the walls' tops, held up by
    a 45 degree gusset under it."""

    length, depth = inner
    y = depth / 2
    wedge = (
        cq.Workplane("YZ")
        .polyline(
            [(y + 0.5, top_z), (y - tab_mm, top_z), (y + 0.5, top_z - tab_mm - 0.5)]
        )
        .close()
        .extrude(length / 2 + 0.5, both=True)
    )

    return model.union(wedge)


def add_scoop(
    model: cq.Workplane, inner: tuple[float, float], floor_z: float, radius: float
) -> cq.Workplane:
    """A quarter-round filling the front edge of the floor."""

    length, depth = inner
    y = -depth / 2
    block = (
        cq.Workplane("XY")
        .box(length + 1.0, radius, radius, centered=(True, False, False))
        .translate((0.0, y, floor_z))
    )
    cylinder = (
        cq.Workplane("YZ")
        .center(y + radius, floor_z + radius)
        .circle(radius)
        .extrude(length / 2 + 1.0, both=True)
    )

    return model.union(block.cut(cylinder))


def holding_centres(
    profile: StackProfile, cells: tuple[int, int]
) -> list[tuple[float, float]]:
    """Every holding point of every cell, from the item's centre."""

    return [
        (cx + x, cy + y)
        for cx, cy in cell_centres(cells, profile.pitch_mm)
        for x, y in profile.holding_points
    ]


def _drill(
    model: cq.Workplane,
    centres: list[tuple[float, float]],
    diameter: float,
    z0: float,
    z1: float,
) -> cq.Workplane:
    """``model`` with a round hole at each centre from ``z0`` to ``z1``."""

    cutters = (
        cq.Workplane("XY")
        .workplane(offset=z0)
        .pushPoints(centres)
        .circle(diameter / 2)
        .extrude(z1 - z0)
    )

    return model.cut(cutters)


def cut_foot_pockets(
    model: cq.Workplane,
    profile: StackProfile,
    cells: tuple[int, int],
    diameter: float,
    depth: float,
) -> cq.Workplane:
    """A pocket in the bottom of each cell's foot at each holding point."""

    return _drill(model, holding_centres(profile, cells), diameter, -0.5, depth)


def cut_plate_holding(
    model: cq.Workplane,
    profile: StackProfile,
    cells: tuple[int, int],
    holding_kind: str,
    diameter: float,
    depth: float,
    floor_mm: float,
    head_diameter: float = 0.0,
    head_depth: float = 0.0,
) -> cq.Workplane:
    """A baseplate's holding under each cell's pocket floor: a magnet pocket sunk into
    the floor from above, or a clearance hole through it with a recess for the screw's
    head in the underside."""

    centres = holding_centres(profile, cells)

    if holding_kind == "magnet":
        return _drill(model, centres, diameter, floor_mm - depth, floor_mm + 0.5)

    model = _drill(model, centres, diameter, -0.5, floor_mm + 0.5)

    if head_depth > 0:
        model = _drill(model, centres, head_diameter, -0.5, head_depth)

    return model


def solid_count(model: cq.Workplane) -> int:
    return len(workplane_shape(model).Solids())
