"""Lid options for the enclosure builder: lips, snaps, countersinks, vents.

A **skirt** hangs from the lid just inside the walls. As a locating lip it
keys the lid onto the base before the screws go in; as a snap-fit lid it
carries a ridge on each long side that clicks into a groove in the wall, and
the skirt is slit beside each ridge so that stretch of it flexes. Either way
it is notched where a boss or a wall opening would be in its way.

**Countersinks** sink a flat-head screw's head flush with the lid.

**Vents** are vertical slots through the long walls that carry no opening,
kept below the skirt and clear of the corner bosses.

Everything here works on the cavity's plain dimensions, so the builder in
:mod:`zcad_core.features.enclosure` decides what applies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.geometry.boxes import box_between

LIP_DEPTH_MM = 2.0
SNAP_SKIRT_DEPTH_MM = 4.5
SKIRT_THICKNESS_MM = 1.2
# The gap between the skirt and the wall's inner face.
SKIRT_FIT_MM = 0.2
RIDGE_PROTRUSION_MM = 0.5
RIDGE_HEIGHT_MM = 1.0
GROOVE_DEPTH_MM = 0.7
GROOVE_HEIGHT_MM = 1.4
# The ridge's centre sits this far below the lid's underside.
RIDGE_DROP_MM = 2.8
# Ridges and grooves run along this share of each long wall.
SNAP_SPAN_FRACTION = 0.6
RELIEF_SLIT_MM = 1.0
# The 45° lead-in along each long wall's inner top edge.
RIM_CHAMFER_MM = 0.5
# Skirt notches clear bosses and openings by this much.
NOTCH_CLEARANCE_MM = 0.4
# Solid lid left under a countersink.
COUNTERSINK_FLOOR_MM = 0.6
VENT_WIDTH_MM = 1.6
VENT_PITCH_MM = 4.0
VENT_MAXIMUM_HEIGHT_MM = 10.0
VENT_MINIMUM_HEIGHT_MM = 3.0
VENT_RIM_MM = 1.5


@dataclass(frozen=True)
class Cavity:
    """The cavity an enclosure's walls surround."""

    center_x_mm: float
    center_y_mm: float
    width_mm: float
    depth_mm: float
    floor_z_mm: float
    top_z_mm: float
    wall_mm: float

    @property
    def long_walls_on_y(self) -> bool:
        """Whether the long walls face ±Y (they run along X)."""
        return self.width_mm >= self.depth_mm

    def long_edges(self) -> tuple[str, str]:
        return (
            ("negative_y", "positive_y")
            if self.long_walls_on_y
            else ("negative_x", "positive_x")
        )

    def wall_length(self, edge: str) -> float:
        return self.width_mm if edge.endswith("_y") else self.depth_mm


def _band(
    cavity: Cavity,
    edge: str,
    *,
    along: tuple[float, float],
    inward: tuple[float, float],
    z: tuple[float, float],
) -> cq.Workplane:
    """A box against one wall: ``along`` it from the cavity centre, and from
    ``inward[0]`` to ``inward[1]`` measured into the cavity from the wall's
    inner face (negative values run into the wall)."""

    sign = 1 if edge.startswith("positive") else -1

    if edge.endswith("_y"):
        face = cavity.center_y_mm + sign * cavity.depth_mm / 2
        return box_between(
            (cavity.center_x_mm + along[0], cavity.center_x_mm + along[1]),
            (face - sign * inward[0], face - sign * inward[1]),
            z,
        )

    face = cavity.center_x_mm + sign * cavity.width_mm / 2
    return box_between(
        (face - sign * inward[0], face - sign * inward[1]),
        (cavity.center_y_mm + along[0], cavity.center_y_mm + along[1]),
        z,
    )


def skirt(cavity: Cavity, depth_mm: float) -> cq.Workplane:
    """A ring hanging from the lid just inside the walls."""

    outer_w = cavity.width_mm - 2 * SKIRT_FIT_MM
    outer_d = cavity.depth_mm - 2 * SKIRT_FIT_MM
    inner_w = outer_w - 2 * SKIRT_THICKNESS_MM
    inner_d = outer_d - 2 * SKIRT_THICKNESS_MM
    z = (cavity.top_z_mm - depth_mm, cavity.top_z_mm + 0.01)
    x, y = cavity.center_x_mm, cavity.center_y_mm

    return box_between(
        (x - outer_w / 2, x + outer_w / 2), (y - outer_d / 2, y + outer_d / 2), z
    ).cut(
        box_between(
            (x - inner_w / 2, x + inner_w / 2),
            (y - inner_d / 2, y + inner_d / 2),
            (z[0] - 1, z[1] + 1),
        )
    )


def notch_skirt(
    skirt_body: cq.Workplane,
    *,
    boss_positions: Sequence[tuple[float, float]],
    boss_radius_mm: float,
    openings: Sequence[ConnectorCutoutParameters],
    cavity: Cavity,
    depth_mm: float,
) -> cq.Workplane:
    """Cut the skirt clear of each boss and each wall opening."""

    z = (cavity.top_z_mm - depth_mm - 1, cavity.top_z_mm + 1)

    reach = boss_radius_mm + NOTCH_CLEARANCE_MM

    for x, y in boss_positions:
        # Clear the whole corner: the boss and the fill behind it.
        corner_x = cavity.center_x_mm + (
            cavity.width_mm / 2 if x > cavity.center_x_mm else -cavity.width_mm / 2
        )
        corner_y = cavity.center_y_mm + (
            cavity.depth_mm / 2 if y > cavity.center_y_mm else -cavity.depth_mm / 2
        )
        # From the corner, past the boss's far side.
        inward_x = -reach if x < corner_x else reach
        inward_y = -reach if y < corner_y else reach
        skirt_body = skirt_body.cut(
            box_between((corner_x, x + inward_x), (corner_y, y + inward_y), z)
        )

    for opening in openings:
        along_y = opening.edge in ("negative_y", "positive_y")
        center = opening.center_offset_mm - (
            cavity.center_x_mm if along_y else cavity.center_y_mm
        )
        half = opening.opening_width_mm / 2 + NOTCH_CLEARANCE_MM
        skirt_body = skirt_body.cut(
            _band(
                cavity,
                opening.edge,
                along=(center - half, center + half),
                inward=(-1.0, SKIRT_FIT_MM + SKIRT_THICKNESS_MM + 1.0),
                z=z,
            )
        )

    return skirt_body


def snap_ridges(cavity: Cavity) -> cq.Workplane:
    """A ridge on the outside of the skirt facing each long wall, with a
    relief slit through the skirt beside each end so the stretch flexes."""

    ridges = cq.Workplane("XY")
    ridge_z = cavity.top_z_mm - RIDGE_DROP_MM

    for edge in cavity.long_edges():
        half = cavity.wall_length(edge) * SNAP_SPAN_FRACTION / 2
        # Flat on top to hold; a 45° lead-in underneath, so the ridge cams
        # past the wall's rim instead of catching on it.
        tip = SKIRT_FIT_MM - RIDGE_PROTRUSION_MM
        top = ridge_z + RIDGE_HEIGHT_MM / 2
        ridges = ridges.union(
            _wall_prism(
                cavity,
                edge,
                half,
                [
                    (SKIRT_FIT_MM + 0.01, top),
                    (tip, top),
                    (tip, top - RIDGE_HEIGHT_MM + RIDGE_PROTRUSION_MM),
                    (SKIRT_FIT_MM + 0.01, top - RIDGE_HEIGHT_MM - 0.01),
                ],
            )
        )

    return ridges


def relief_slits(cavity: Cavity) -> cq.Workplane:
    """The slits that free each ridged stretch of skirt from its ends."""

    slits = cq.Workplane("XY")
    z = (cavity.top_z_mm - SNAP_SKIRT_DEPTH_MM - 1, cavity.top_z_mm - 0.01)

    for edge in cavity.long_edges():
        half = cavity.wall_length(edge) * SNAP_SPAN_FRACTION / 2

        for end in (-1, 1):
            at = end * (half + RELIEF_SLIT_MM / 2)
            slits = slits.union(
                _band(
                    cavity,
                    edge,
                    along=(at - RELIEF_SLIT_MM / 2, at + RELIEF_SLIT_MM / 2),
                    inward=(0.0, SKIRT_FIT_MM + SKIRT_THICKNESS_MM + 0.5),
                    z=z,
                )
            )

    return slits


def snap_grooves(cavity: Cavity) -> cq.Workplane:
    """The grooves in the long walls the ridges click into."""

    grooves = cq.Workplane("XY")
    ridge_z = cavity.top_z_mm - RIDGE_DROP_MM

    for edge in cavity.long_edges():
        # Slightly longer than the ridge, so the ridge's ends clear it.
        half = cavity.wall_length(edge) * SNAP_SPAN_FRACTION / 2 + 0.5
        grooves = grooves.union(
            _band(
                cavity,
                edge,
                along=(-half, half),
                inward=(-GROOVE_DEPTH_MM, 0.01),
                z=(ridge_z - GROOVE_HEIGHT_MM / 2, ridge_z + GROOVE_HEIGHT_MM / 2),
            )
        )
        # A lead-in along the rim's inner edge, for the ridge to ride down.
        top = cavity.top_z_mm + 0.01
        grooves = grooves.union(
            _wall_prism(
                cavity,
                edge,
                cavity.wall_length(edge) / 2,
                [
                    (0.01, top),
                    (-RIM_CHAMFER_MM, top),
                    (0.01, top - RIM_CHAMFER_MM - 0.01),
                ],
            )
        )

    return grooves


_EDGE_TURN_DEG = {
    "positive_y": 0.0,
    "negative_y": 180.0,
    "positive_x": -90.0,
    "negative_x": 90.0,
}


def _wall_prism(
    cavity: Cavity,
    edge: str,
    half_length: float,
    profile: Sequence[tuple[float, float]],
) -> cq.Workplane:
    """A 2D profile swept along one wall: each point is (distance into the
    cavity from the wall's inner face, height)."""

    # Build against a +Y wall at the origin, then turn it to face ``edge``.
    face = cavity.depth_mm / 2 if edge.endswith("_y") else cavity.width_mm / 2
    prism = (
        cq.Workplane("YZ")
        .polyline([(face - inward, z) for inward, z in profile])
        .close()
        .extrude(2 * half_length)
        .translate((-half_length, 0, 0))
    )

    return prism.rotate((0, 0, 0), (0, 0, 1), _EDGE_TURN_DEG[edge]).translate(
        (cavity.center_x_mm, cavity.center_y_mm, 0)
    )


def countersinks(
    positions: Sequence[tuple[float, float]],
    *,
    hole_diameter_mm: float,
    head_diameter_mm: float,
    lid_top_z_mm: float,
    lid_thickness_mm: float,
) -> cq.Workplane:
    """90° cones that sink a flat-head screw flush with the lid's top."""

    depth = (head_diameter_mm - hole_diameter_mm) / 2

    if depth > lid_thickness_mm - COUNTERSINK_FLOOR_MM:
        raise ValueError(
            f"A {head_diameter_mm} mm countersunk head needs a lid at least "
            f"{depth + COUNTERSINK_FLOOR_MM:.1f} mm thick"
        )

    cones = cq.Workplane("XY")

    for x, y in positions:
        cones = cones.add(
            cq.Solid.makeCone(
                hole_diameter_mm / 2,
                head_diameter_mm / 2 + 0.01,
                depth + 0.01,
                pnt=cq.Vector(x, y, lid_top_z_mm - depth),
            )
        )

    return cones.combine()


def vents(
    cavity: Cavity,
    *,
    slots_per_wall: int,
    blocked_edges: Sequence[str],
    top_z_mm: float,
    corner_keepout_mm: float,
) -> cq.Workplane:
    """Vertical slots through each long wall that carries no opening."""

    bottom = max(cavity.floor_z_mm + VENT_RIM_MM, top_z_mm - VENT_MAXIMUM_HEIGHT_MM)

    if top_z_mm - bottom < VENT_MINIMUM_HEIGHT_MM:
        raise ValueError(
            "The walls are too low for vents below the lid's skirt; raise "
            "top_clearance_mm or use a lid without a skirt"
        )

    walls = [edge for edge in cavity.long_edges() if edge not in blocked_edges]

    if not walls:
        raise ValueError("Both long walls carry an opening; there is nowhere to vent")

    span = (slots_per_wall - 1) * VENT_PITCH_MM + VENT_WIDTH_MM
    cutters = cq.Workplane("XY")

    for edge in walls:
        if span > cavity.wall_length(edge) - 2 * corner_keepout_mm:
            raise ValueError(
                f"{slots_per_wall} vent slots do not fit between the corners of "
                f"the {edge} wall"
            )

        for index in range(slots_per_wall):
            at = -span / 2 + index * VENT_PITCH_MM
            cutters = cutters.union(
                _band(
                    cavity,
                    edge,
                    along=(at, at + VENT_WIDTH_MM),
                    inward=(-cavity.wall_mm - 1.0, 0.3),
                    z=(bottom, top_z_mm),
                )
            )

    return cutters
