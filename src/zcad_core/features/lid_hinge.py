"""A pin hinge and a snap catch for an enclosure's lid.

The lid hangs from one long wall on a row of knuckles that alternate between
the base and the lid, around a pin the user supplies (an M3 screw and nut, by
default). The opposite long wall carries a catch: a tongue that hangs from the
lid outside the wall and hooks under a bump on it.

The catch is outside the wall, not a skirt inside it, because of how the lid
swings. The axis is behind the hinge wall, so lifting the lid's front edge
also moves everything below the axis toward the front wall. A skirt inside
that wall would dig into it after a degree or two; a tongue outside it moves
away.

The builder works in a local frame for each wall: the wall runs along X, is
centred on it, has its outer face in the ``y == 0`` plane, and ``+y`` points
outward. :func:`_to_world` turns that into the enclosure's frame.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.mounts import (
    FLEXURE_STRAIN_LIMIT,
    Flexure,
    flexure_for,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import FastenerSpec

HINGE_WEB_DEPTH_MM = 2.5
# The lid swings this far; the sweep checks every step of it.
SWING_DEGREES = 100.0
SWING_STEP_DEGREES = 10.0

# Barrel wall around the pin hole, and the gaps that let knuckles turn.
_BARREL_WALL_MM = 1.8
_AXIS_CLEARANCE_MM = 0.4
_KNUCKLE_GAP_MM = 0.4
_END_MARGIN_MM = 5.0
_MINIMUM_KNUCKLE_MM = 5.0
_ROOT_OVERLAP_MM = 0.5
# A nut on the pin's far end, and the slack left beyond it.
_NUT_THICKNESS_MM = 2.4
_PIN_SLACK_MM = 1.0
_PIN_LENGTHS_MM = (8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80)
# Past the longest screw, a pin is a threaded rod cut to length, to the next 5 mm.
_ROD_STEP_MM = 5
_LONGEST_ROD_MM = 250

# The catch: a tongue outside the closure wall, a hook on its end, and a bump
# on the wall that the hook snaps under.
CATCH_WIDTH_MM = 16.0
CATCH_TONGUE_MM = 1.2
CATCH_BUMP_MM = 0.6
CATCH_ENGAGEMENT_MM = 0.5
CATCH_CLEARANCE_MM = 0.3
CATCH_HOOK_HEIGHT_MM = 1.4
CATCH_PULL_LIP_MM = 1.2
_CATCH_END_MARGIN_MM = 6.0
_CATCH_OPENING_MARGIN_MM = 1.0
_CATCH_FLOOR_MARGIN_MM = 1.0

EDGE_ANGLE = {
    "positive_y": 0.0,
    "negative_y": 180.0,
    "positive_x": -90.0,
    "negative_x": 90.0,
}
# A local x is this sign times the world coordinate along the wall, measured
# from the cavity's centre.
EDGE_SIGN = {
    "positive_y": 1.0,
    "negative_y": -1.0,
    "positive_x": -1.0,
    "negative_x": 1.0,
}
_OPPOSITE = {
    "positive_y": "negative_y",
    "negative_y": "positive_y",
    "positive_x": "negative_x",
    "negative_x": "positive_x",
}


@dataclass(frozen=True)
class HingeReport:
    """What the hinge and catch came out as."""

    hinge_edge: str
    closure_edge: str
    knuckles: int
    span_mm: float
    pin: str
    pin_length_mm: int
    swing_degrees: float
    catch_center_mm: float
    catch: Flexure
    wall_needed_mm: float
    # A pin longer than any screw is a threaded rod, cut to ``pin_length_mm``.
    pin_is_rod: bool = False
    # The pin's axis in the enclosure's frame (a point on it and its
    # direction), and the sign of the turn that opens the lid.
    axis_point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    axis_direction: tuple[float, float, float] = (1.0, 0.0, 0.0)
    swing_sign: float = 1.0

    @property
    def pin_description(self) -> str:
        """The pin to buy, as a sentence."""

        if self.pin_is_rod:
            return (
                f"{self.pin} threaded rod cut to {self.pin_length_mm} mm, "
                "with a nut at each end"
            )

        return f"{self.pin} x {self.pin_length_mm} mm screw and nut"


def axis_offset_mm(pin: FastenerSpec) -> float:
    """How far the pin's axis stands off the wall's outer face: the barrel's
    radius and the clearance that lets a knuckle turn."""

    return pin.clearance_hole_mm / 2 + _BARREL_WALL_MM + _AXIS_CLEARANCE_MM


def swung_lid(lid: cq.Shape, hinge: HingeReport, degrees: float) -> cq.Shape:
    """The lid turned open about the pin by ``degrees``, as the sweep turns it."""

    point = cq.Vector(*hinge.axis_point)
    direction = cq.Vector(*hinge.axis_direction)

    return lid.rotate(point, point + direction, hinge.swing_sign * degrees)


def hinge_edges(
    cavity: Cavity, openings: Sequence[ConnectorCutoutParameters]
) -> tuple[str, str]:
    """The hinge wall and the closure wall opposite it: a long wall that
    carries no opening, preferring the back (positive) one."""

    blocked = {opening.edge for opening in openings}
    back = cavity.long_edges()[1]

    for edge in (back, _OPPOSITE[back]):
        if edge not in blocked:
            return edge, _OPPOSITE[edge]

    raise ValueError(
        "Both long walls carry an opening, so neither can take the hinge; use "
        "a screwed lid"
    )


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            x[1] - x[0], y[1] - y[0], z[1] - z[0], pnt=cq.Vector(x[0], y[0], z[0])
        )
    )


def _prism(
    points: Sequence[tuple[float, float]], x: tuple[float, float]
) -> cq.Workplane:
    """A profile in the (y, z) plane, extruded along X."""

    return (
        cq.Workplane("YZ")
        .polyline(list(points))
        .close()
        .extrude(x[1] - x[0])
        .translate((x[0], 0.0, 0.0))
    )


def wall_anchor(edge: str, cavity: Cavity) -> tuple[float, float]:
    """The middle of a wall's outer face, in the enclosure's frame."""

    reach_x = cavity.width_mm / 2 + cavity.wall_mm
    reach_y = cavity.depth_mm / 2 + cavity.wall_mm
    offset = {
        "positive_y": (0.0, reach_y),
        "negative_y": (0.0, -reach_y),
        "positive_x": (reach_x, 0.0),
        "negative_x": (-reach_x, 0.0),
    }[edge]

    return cavity.center_x_mm + offset[0], cavity.center_y_mm + offset[1]


def _to_world(model: cq.Workplane, edge: str, cavity: Cavity) -> cq.Workplane:
    """Move a shape built in a wall's local frame onto that wall."""

    x, y = wall_anchor(edge, cavity)

    return model.rotate((0, 0, 1), (0, 0, 2), EDGE_ANGLE[edge]).translate((x, y, 0.0))


def _outer_length(cavity: Cavity, edge: str) -> float:
    return cavity.wall_length(edge) + 2 * cavity.wall_mm


def _along_center(cavity: Cavity, edge: str) -> float:
    return cavity.center_x_mm if edge.endswith("_y") else cavity.center_y_mm


def _solids(model: cq.Workplane) -> cq.Shape:
    return cq.Compound.makeCompound(
        [
            solid
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for solid in item.Solids()
        ]
    )


def _pin_length(span_mm: float) -> tuple[int, bool]:
    """The pin's length, and whether it is a threaded rod cut to length because
    no screw is long enough."""

    needed = span_mm + _NUT_THICKNESS_MM + _PIN_SLACK_MM
    fitting = [length for length in _PIN_LENGTHS_MM if length >= needed]

    if fitting:
        return fitting[0], False

    # A rod has no head, so it takes a nut at each end.
    rod = math.ceil((needed + _NUT_THICKNESS_MM) / _ROD_STEP_MM) * _ROD_STEP_MM

    if rod > _LONGEST_ROD_MM:
        raise ValueError(
            f"No pin is long enough for a {span_mm:.0f} mm hinge: a rod over "
            f"{_LONGEST_ROD_MM} mm would bend"
        )

    return rod, True


def _knuckle_layout(span_mm: float) -> tuple[int, float]:
    """How many knuckles fit the span, and how long each is."""

    count = 5 if span_mm >= 40.0 else 3
    length = (span_mm - (count - 1) * _KNUCKLE_GAP_MM) / count

    if length < _MINIMUM_KNUCKLE_MM:
        raise ValueError(
            f"The hinge wall is too short: its knuckles would be {length:.1f} mm "
            f"long, and the least is {_MINIMUM_KNUCKLE_MM:.0f} mm"
        )

    return count, length


def _catch_center(
    cavity: Cavity,
    edge: str,
    openings: Sequence[ConnectorCutoutParameters],
) -> float:
    """Where along the closure wall the catch goes: the middle of the widest
    stretch clear of openings."""

    center = _along_center(cavity, edge)
    half = _outer_length(cavity, edge) / 2 - _CATCH_END_MARGIN_MM
    blocked = sorted(
        (
            opening.center_offset_mm
            - opening.opening_width_mm / 2
            - _CATCH_OPENING_MARGIN_MM,
            opening.center_offset_mm
            + opening.opening_width_mm / 2
            + _CATCH_OPENING_MARGIN_MM,
        )
        for opening in openings
        if opening.edge == edge
    )
    free: list[tuple[float, float]] = []
    cursor = center - half

    for low, high in blocked:
        if low > cursor:
            free.append((cursor, min(low, center + half)))

        cursor = max(cursor, high)

    if cursor < center + half:
        free.append((cursor, center + half))

    wide = max(free, key=lambda span: span[1] - span[0], default=(0.0, 0.0))

    if wide[1] - wide[0] < CATCH_WIDTH_MM:
        raise ValueError(
            f"No {CATCH_WIDTH_MM:.0f} mm of the closure wall is clear of "
            "openings for the catch"
        )

    return (wide[0] + wide[1]) / 2


def add_hinge(
    base: cq.Workplane,
    lid: cq.Workplane,
    cavity: Cavity,
    *,
    lid_mm: float,
    pin: FastenerSpec,
    hole_compensation_mm: float,
    openings: Sequence[ConnectorCutoutParameters],
    hardware: Mapping[str, cq.Shape],
    carried: Mapping[str, cq.Shape] | None = None,
    hinge_edge: str | None = None,
) -> tuple[cq.Workplane, cq.Workplane, HingeReport]:
    """Add the hinge and the catch, refusing a lid that cannot swing clear.

    ``hinge_edge`` names the wall that takes the hinge, the catch going on the
    one opposite; left out, a long wall with no opening is chosen. Naming it
    means the walls' openings are the caller's to keep clear of the knuckles.

    ``hardware`` are the parts inside, by name, which the swinging lid must
    not hit. ``carried`` are the parts the lid holds, such as a display
    screwed to its posts: they swing with it, so they are swept too. The lid
    should already carry whatever hangs from it, such as those posts.
    """

    if hinge_edge is None:
        hinge_edge, closure_edge = hinge_edges(cavity, openings)
    else:
        closure_edge = _OPPOSITE[hinge_edge]

    top = cavity.top_z_mm
    hole = pin.clearance_hole_mm + hole_compensation_mm
    radius = pin.clearance_hole_mm / 2 + _BARREL_WALL_MM
    axis_u = axis_offset_mm(pin)
    axis_z = top + lid_mm / 2
    outer = _outer_length(cavity, hinge_edge)
    span = outer - 2 * _END_MARGIN_MM
    count, length = _knuckle_layout(span)
    bottom = _solids(base).BoundingBox().zmin

    # The catch: how long its tongue must be, and so how tall the wall.
    deflection = CATCH_ENGAGEMENT_MM + CATCH_CLEARANCE_MM
    reach = math.ceil(
        math.sqrt(3 * CATCH_TONGUE_MM * deflection / (2 * FLEXURE_STRAIN_LIMIT))
    )
    catch = flexure_for(deflection, reach, CATCH_TONGUE_MM)
    hook_top = top - reach + CATCH_HOOK_HEIGHT_MM / 2
    hook_bottom = hook_top - CATCH_HOOK_HEIGHT_MM
    needed = top - hook_bottom + _CATCH_FLOOR_MARGIN_MM

    if hook_bottom - bottom < _CATCH_FLOOR_MARGIN_MM:
        raise ValueError(
            f"The wall is {top - bottom:.1f} mm tall and the lid's catch needs "
            f"{needed:.1f} mm; raise bottom_clearance_mm or the parts' height"
        )

    x0 = -span / 2
    base_parts: list[cq.Workplane] = []
    lid_parts: list[cq.Workplane] = []

    for index in range(count):
        start = x0 + index * (length + _KNUCKLE_GAP_MM)
        barrel = cq.Workplane("XY").add(
            cq.Solid.makeCylinder(
                radius,
                length,
                pnt=cq.Vector(start, axis_u, axis_z),
                dir=cq.Vector(1, 0, 0),
            )
        )

        if index % 2 == 0:
            web = _box(
                (start, start + length),
                (-_ROOT_OVERLAP_MM, axis_u + radius),
                (axis_z - radius, top),
            )
            base_parts.append(barrel.union(web))
        else:
            web = _box(
                (start, start + length),
                (-_ROOT_OVERLAP_MM, axis_u),
                (top, top + lid_mm),
            )
            lid_parts.append(barrel.union(web))

    pin_hole = cq.Workplane("XY").add(
        cq.Solid.makeCylinder(
            hole / 2,
            span + 2.0,
            pnt=cq.Vector(x0 - 1.0, axis_u, axis_z),
            dir=cq.Vector(1, 0, 0),
        )
    )
    hole_world = _to_world(pin_hole, hinge_edge, cavity)

    for part in base_parts:
        base = base.union(_to_world(part, hinge_edge, cavity))

    for part in lid_parts:
        lid = lid.union(_to_world(part, hinge_edge, cavity))

    base = base.cut(hole_world)
    lid = lid.cut(hole_world)

    point, direction, sign = _swing_axis(lid, cavity, hinge_edge, axis_u, axis_z)
    _require_free_swing(base, lid, (point, direction, sign), hardware, carried or {})

    catch_center = _catch_center(cavity, closure_edge, openings)
    local_center = EDGE_SIGN[closure_edge] * (
        catch_center - _along_center(cavity, closure_edge)
    )
    base, lid = _add_catch(
        base,
        lid,
        cavity,
        closure_edge,
        center=local_center,
        lid_mm=lid_mm,
        hook=(hook_bottom, hook_top),
    )
    pin_length, pin_is_rod = _pin_length(span)
    report = HingeReport(
        hinge_edge=hinge_edge,
        closure_edge=closure_edge,
        knuckles=count,
        span_mm=span,
        pin=pin.identifier,
        pin_length_mm=pin_length,
        swing_degrees=SWING_DEGREES,
        catch_center_mm=catch_center,
        catch=catch,
        wall_needed_mm=needed,
        pin_is_rod=pin_is_rod,
        axis_point=(point.x, point.y, point.z),
        axis_direction=(direction.x, direction.y, direction.z),
        swing_sign=sign,
    )

    return base, lid, report


def _add_catch(
    base: cq.Workplane,
    lid: cq.Workplane,
    cavity: Cavity,
    edge: str,
    *,
    center: float,
    lid_mm: float,
    hook: tuple[float, float],
) -> tuple[cq.Workplane, cq.Workplane]:
    """The tongue and hook on the lid, and the bump on the wall."""

    top = cavity.top_z_mm
    bottom, hook_top = hook
    x = (center - CATCH_WIDTH_MM / 2, center + CATCH_WIDTH_MM / 2)
    tongue_in = CATCH_BUMP_MM + CATCH_CLEARANCE_MM
    tongue_out = tongue_in + CATCH_TONGUE_MM
    hook_in = CATCH_BUMP_MM - CATCH_ENGAGEMENT_MM
    lip = CATCH_HOOK_HEIGHT_MM

    # A tab extends the lid's plate over the tongue; the tongue hangs from it.
    tab = _box(x, (-_ROOT_OVERLAP_MM, tongue_out), (top, top + lid_mm))
    tongue = _box(x, (tongue_in, tongue_out), (bottom, top + lid_mm))
    # The hook's underside slopes, so the lid pushes the tongue out as it shuts.
    hook_body = _prism(
        [
            (tongue_in + 0.1, hook_top),
            (hook_in, hook_top),
            (hook_in, bottom + 0.5),
            (tongue_in + 0.1, bottom),
        ],
        x,
    )
    pull = _box(
        x, (tongue_out - 0.1, tongue_out + CATCH_PULL_LIP_MM), (bottom, bottom + lip)
    )
    catch = tab.union(tongue).union(hook_body).union(pull)
    # The bump's top slopes too, so the hook rides over it.
    bump = _prism(
        [
            (-_ROOT_OVERLAP_MM, hook_top),
            (CATCH_BUMP_MM, hook_top),
            (CATCH_BUMP_MM, hook_top + 0.5),
            (0.0, hook_top + CATCH_HOOK_HEIGHT_MM),
            (-_ROOT_OVERLAP_MM, hook_top + CATCH_HOOK_HEIGHT_MM),
        ],
        x,
    )

    return (
        base.union(_to_world(bump, edge, cavity)),
        lid.union(_to_world(catch, edge, cavity)),
    )


def _swing_axis(
    lid: cq.Workplane, cavity: Cavity, edge: str, axis_u: float, axis_z: float
) -> tuple[cq.Vector, cq.Vector, float]:
    """The pin's axis (a point on it, and its direction) and the sign of the
    turn that lifts the lid's free edge."""

    angle = math.radians(EDGE_ANGLE[edge])
    anchor_x, anchor_y = wall_anchor(edge, cavity)
    point = cq.Vector(
        anchor_x - axis_u * math.sin(angle),
        anchor_y + axis_u * math.cos(angle),
        axis_z,
    )
    direction = cq.Vector(math.cos(angle), math.sin(angle), 0.0)
    lid_shape = _solids(lid)
    sign = 1.0

    if (
        lid_shape.rotate(point, point + direction, 10.0).Center().z
        < lid_shape.Center().z
    ):
        sign = -1.0

    return point, direction, sign


def _require_free_swing(
    base: cq.Workplane,
    lid: cq.Workplane,
    axis: tuple[cq.Vector, cq.Vector, float],
    hardware: Mapping[str, cq.Shape],
    carried: Mapping[str, cq.Shape],
) -> None:
    """Sweep the lid open in steps and refuse one that meets the base or any
    part inside it."""

    point, direction, sign = axis
    lid_shape = _solids(lid)
    moving = {"the lid": lid_shape, **carried}
    obstacles = {"the base": _solids(base), **hardware}
    degrees = SWING_STEP_DEGREES

    while degrees <= SWING_DEGREES + 1e-9:
        for mover_name, mover in moving.items():
            swung = mover.rotate(point, point + direction, sign * degrees)

            for name, obstacle in obstacles.items():
                if intersection_volume(swung, obstacle) > 1e-6:
                    raise ValueError(
                        f"{mover_name[0].upper() + mover_name[1:]} hits {name} at "
                        f"{degrees:.0f} degrees of its swing; widen "
                        "side_clearance_mm, move what hangs from the lid, or "
                        "use a screwed lid"
                    )

        degrees += SWING_STEP_DEGREES
