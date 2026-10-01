"""A lid that slides into grooves in the long walls, with a detent.

The two long walls are raised above the cavity and thickened outward, and a
groove is cut into each one's inner face. The lid's plate slides along the
grooves and stops against the raised far short wall. The near short wall, the
entry, is cut down to the groove's floor so the lid can pass over it. A
detent holds the lid shut: a tongue cut from each edge of the lid's plate
carries a rounded bump that clicks into a dimple in the groove.

The tongues bend in the lid's plane, so their stress runs along the printed
layers. Nothing may hang from the lid below the entry wall's top, since it
would hit that wall as the lid slides out; the travel check refuses a lid
that carries a display, for that reason.

The builder works in a canonical frame: the lid slides along X, the long walls
are at ``y == +-half_width``, and the entry is at ``+X`` or ``-X``.
:func:`_to_world` turns that into the enclosure's frame.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.mounts import FLEXURE_STRAIN_LIMIT, Flexure, flexure_for
from zcad_core.geometry.intersection import intersection_volume

GROOVE_DEPTH_MM = 1.6
# The wall above the lid's top, which holds the lid in its groove.
RETAINING_STRIP_MM = 1.2
# How far the long walls stand beyond their thickness, and how far below the
# groove that starts; a 45 degree slope under it keeps it printable.
BULGE_MM = GROOVE_DEPTH_MM
BULGE_DROP_MM = 3.0
SLIDE_VENT_DROP_MM = BULGE_DROP_MM + BULGE_MM - 1.1
DEFAULT_CLEARANCE_MM = 0.2
TRAVEL_STEP_MM = 5.0

# The detent: a tongue cut from each edge of the lid, with a rounded bump.
TONGUE_MM = 1.6
_SLIT_MM = 1.4
_END_SLIT_MM = 1.0
_BUMP_RADIUS_MM = 0.6
_BUMP_ENGAGEMENT_MM = 0.5
_DIMPLE_EXTRA_MM = 0.15
_ROOT_MM = 3.0
_BUMP_FROM_END_MM = 1.2
_OPENING_SUPPORT_MM = 1.0

_SHORT_EDGES = {True: ("negative_x", "positive_x"), False: ("negative_y", "positive_y")}


@dataclass(frozen=True)
class SlideReport:
    """What the slide lid came out as."""

    entry_edge: str
    clearance_mm: float
    groove_depth_mm: float
    lid_length_mm: float
    travel_mm: float
    detent: Flexure
    wall_top_above_cavity_mm: float


def slide_clearance_error(clearance_mm: float) -> str | None:
    if not 0.0 < clearance_mm <= 1.0:
        return "slide_clearance_mm must be from 0 to 1 mm"

    return None


def _box(
    a: tuple[float, float], c: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    a0, a1 = sorted(a)
    c0, c1 = sorted(c)
    z0, z1 = sorted(z)

    return cq.Workplane("XY").add(
        cq.Solid.makeBox(a1 - a0, c1 - c0, z1 - z0, pnt=cq.Vector(a0, c0, z0))
    )


def _cylinder(
    a: float, c: float, z: tuple[float, float], radius: float
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeCylinder(radius, z[1] - z[0], pnt=cq.Vector(a, c, z[0]))
    )


def _slope(
    a: tuple[float, float], side: float, z_top: float, inner_y: float
) -> cq.Workplane:
    """The 45 degree slope that carries the bulge down to the wall's outer
    face at ``inner_y``, along the long wall on ``side`` (+1 or -1)."""

    outer_y = inner_y + BULGE_MM
    points = [
        (side * inner_y, z_top - BULGE_MM),
        (side * outer_y, z_top),
        (side * inner_y, z_top),
    ]

    return (
        cq.Workplane("YZ")
        .polyline(points)
        .close()
        .extrude(a[1] - a[0])
        .translate((a[0], 0.0, 0.0))
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


def slide_entry(cavity: Cavity, openings: Sequence[ConnectorCutoutParameters]) -> str:
    """The short wall the lid slides in over: one with no opening, the
    positive one if both are free."""

    blocked = {opening.edge for opening in openings}
    low, high = _SHORT_EDGES[cavity.long_walls_on_y]

    for edge in (high, low):
        if edge not in blocked:
            return edge

    raise ValueError(
        "Both short walls carry an opening, so neither can be the slide's "
        "entry; use a screwed lid"
    )


def _require_openings_under_the_groove(
    cavity: Cavity,
    openings: Sequence[ConnectorCutoutParameters],
    clearance: float,
) -> None:
    """Refuse an opening in a long wall that would cut the groove's floor."""

    limit = cavity.top_z_mm - clearance - _OPENING_SUPPORT_MM
    long_edges = cavity.long_edges()

    for opening in openings:
        top = opening.bottom_z_mm + opening.opening_height_mm

        if opening.edge in long_edges and top > limit:
            raise ValueError(
                f"An opening in the {opening.edge} wall reaches {top:.1f} mm; the "
                f"lid's groove starts at {limit:.1f} mm, so the opening would "
                "cut it"
            )


def add_slide(
    base: cq.Workplane,
    lid: cq.Workplane,
    cavity: Cavity,
    *,
    lid_mm: float,
    clearance_mm: float,
    hole_compensation_mm: float,
    openings: Sequence[ConnectorCutoutParameters],
    hardware: Mapping[str, cq.Shape],
    carried: Mapping[str, cq.Shape] | None = None,
) -> tuple[cq.Workplane, cq.Workplane, SlideReport]:
    """Turn a base and its plate into a sliding lid, refusing a lid that
    cannot slide out clear of the base and the parts inside."""

    error = slide_clearance_error(clearance_mm)

    if error is not None:
        raise ValueError(error)

    _require_openings_under_the_groove(cavity, openings, clearance_mm)
    entry = slide_entry(cavity, openings)
    along_y = not cavity.long_walls_on_y
    sign = 1.0 if entry.startswith("positive") else -1.0
    half_a = (cavity.depth_mm if along_y else cavity.width_mm) / 2
    half_c = (cavity.width_mm if along_y else cavity.depth_mm) / 2
    wall = cavity.wall_mm
    top = cavity.top_z_mm
    cl = clearance_mm
    groove = (top - cl, top + lid_mm + cl)
    wall_top = groove[1] + RETAINING_STRIP_MM
    entry_a = sign * (half_a + wall)

    def world(model: cq.Workplane) -> cq.Workplane:
        return _to_world(model, along_y, cavity)

    # Raise and thicken the long walls, and raise the far short wall.
    blocks = []

    for side in (1.0, -1.0):
        blocks.append(
            _box(
                (-half_a - wall, half_a + wall),
                (side * half_c, side * (half_c + wall + BULGE_MM)),
                (top - BULGE_DROP_MM, wall_top),
            )
        )
        blocks.append(
            _slope(
                (-half_a - wall, half_a + wall),
                side,
                top - BULGE_DROP_MM,
                half_c + wall,
            )
        )

    blocks.append(
        _box(
            (-sign * half_a, -sign * (half_a + wall)),
            (-half_c, half_c),
            (top, wall_top),
        )
    )

    added = blocks[0]

    for block in blocks[1:]:
        added = added.union(block)

    # The entry wall comes down to the groove's floor; the grooves open into
    # the cavity and out of the entry end.
    cuts = _box(
        (sign * half_a, sign * (half_a + wall + 1.0)),
        (-half_c, half_c),
        (groove[0], top + 1.0),
    )

    for side in (1.0, -1.0):
        cuts = cuts.union(
            _box(
                (-sign * half_a, sign * (half_a + wall + 1.0)),
                (side * (half_c - 0.5), side * (half_c + GROOVE_DEPTH_MM)),
                groove,
            )
        )

    base = base.union(world(added)).cut(world(cuts))

    # The lid's plate, cut to sit in the grooves with the clearance all round.
    lid_far = -sign * (half_a - cl)
    outline = _box(
        (lid_far, entry_a),
        (-(half_c + GROOVE_DEPTH_MM - cl), half_c + GROOVE_DEPTH_MM - cl),
        (top - 1.0, top + lid_mm + 1.0),
    )
    lid = lid.intersect(world(outline))
    lid_length = abs(entry_a - lid_far)

    # The detent: the shortest tongue that stays within the strain limit,
    # from its root to the bump.
    deflection = _BUMP_ENGAGEMENT_MM + cl
    reach = math.ceil(
        math.sqrt(3 * TONGUE_MM * deflection / (2 * FLEXURE_STRAIN_LIMIT))
    )
    detent = flexure_for(deflection, reach, TONGUE_MM)
    tongue_length = reach + _BUMP_FROM_END_MM

    if lid_length < tongue_length + _ROOT_MM + _END_SLIT_MM + 4.0:
        raise ValueError(
            f"The lid is {lid_length:.0f} mm long and its detent tongues need "
            f"{tongue_length + _ROOT_MM + _END_SLIT_MM + 4.0:.0f} mm"
        )

    mid = (lid_far + entry_a) / 2
    free = mid + sign * tongue_length / 2
    root = mid - sign * tongue_length / 2
    bump_a = free - sign * _BUMP_FROM_END_MM
    slit = _SLIT_MM + hole_compensation_mm
    end_slit = _END_SLIT_MM + hole_compensation_mm
    strip_inner = half_c + GROOVE_DEPTH_MM - cl - TONGUE_MM
    strip_outer = half_c + GROOVE_DEPTH_MM - cl
    cut_z = (top - 1.0, top + lid_mm + 1.0)
    bump_c = half_c + GROOVE_DEPTH_MM + _BUMP_ENGAGEMENT_MM - _BUMP_RADIUS_MM
    dimple_radius = _BUMP_RADIUS_MM + _DIMPLE_EXTRA_MM
    dimples = cq.Workplane("XY")
    slits = cq.Workplane("XY")
    bumps = cq.Workplane("XY")
    first = True

    for side in (1.0, -1.0):
        parts = [
            _box(
                (free + sign * end_slit, root),
                (side * strip_inner, side * (strip_inner - slit)),
                cut_z,
            ),
            _box(
                (free, free + sign * end_slit),
                (side * strip_inner, side * (strip_outer + 0.5)),
                cut_z,
            ),
        ]
        bump = _cylinder(bump_a, side * bump_c, (top, top + lid_mm), _BUMP_RADIUS_MM)
        dimple = _cylinder(bump_a, side * bump_c, groove, dimple_radius)

        if first:
            slits, bumps, dimples = parts[0].union(parts[1]), bump, dimple
            first = False
        else:
            slits = slits.union(parts[0]).union(parts[1])
            bumps = bumps.union(bump)
            dimples = dimples.union(dimple)

    lid = lid.cut(world(slits))
    base = base.cut(world(dimples))

    _require_free_travel(
        base, lid, along_y, sign, lid_length, cavity, hardware, carried or {}
    )
    lid = lid.union(world(bumps))
    report = SlideReport(
        entry_edge=entry,
        clearance_mm=cl,
        groove_depth_mm=GROOVE_DEPTH_MM,
        lid_length_mm=lid_length,
        travel_mm=lid_length,
        detent=detent,
        wall_top_above_cavity_mm=wall_top - top,
    )

    return base, lid, report


def _to_world(model: cq.Workplane, along_y: bool, cavity: Cavity) -> cq.Workplane:
    """Move a canonical shape onto the cavity: slide along X, or along Y after
    a quarter turn."""

    if along_y:
        model = model.rotate((0, 0, 0), (0, 0, 1), 90.0)

    return model.translate((cavity.center_x_mm, cavity.center_y_mm, 0.0))


def _require_free_travel(
    base: cq.Workplane,
    lid: cq.Workplane,
    along_y: bool,
    sign: float,
    length: float,
    cavity: Cavity,
    hardware: Mapping[str, cq.Shape],
    carried: Mapping[str, cq.Shape],
) -> None:
    """Slide the lid out in steps and refuse one that meets the base or any
    part inside it. The bumps are left off: they are meant to press on the
    groove as they pass."""

    direction = cq.Vector(0.0, sign, 0.0) if along_y else cq.Vector(sign, 0.0, 0.0)
    moving = {"the lid": _solids(lid), **carried}
    obstacles = {"the base": _solids(base), **hardware}
    travelled = TRAVEL_STEP_MM

    while travelled <= length + TRAVEL_STEP_MM:
        offset = direction * travelled

        for mover_name, mover in moving.items():
            moved = mover.translate(offset)

            for name, obstacle in obstacles.items():
                if intersection_volume(moved, obstacle) > 1e-6:
                    raise ValueError(
                        f"{mover_name.capitalize()} hits {name} at "
                        f"{travelled:.0f} mm of its slide; nothing may hang "
                        "from a sliding lid below the entry wall, so a display "
                        "or a fan on the lid needs a hinged or screwed lid"
                    )

        travelled += TRAVEL_STEP_MM
