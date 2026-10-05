"""Rack ears for a group enclosure: front-wall pads and a pair of flanges.

Each ear is a flat flange in front of the enclosure that reaches out to the
rack's rail, with EIA-310 holes at 15.875 / 12.7 / 15.875 mm down a 1U
panel. It bolts to two pads on the front wall, as the underside mounts bolt
to pads under the floor, so an ear never touches the inside of the
enclosure. The pads stand out of the front, not the sides, so the base is no
wider than before and still fits the bed it fitted. The enclosure sits
centred in the rack, and only 1U is supported.

Frame: the group's, with the outer bottom-left-front corner at the origin,
+X along the row, +Y front to back, +Z up. The ears lie in front of it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.mounts import (
    HEAD_DIAMETER_FACTOR,
    MINIMUM_PAD_HEIGHT_MM,
    PAD_EMBED_MM,
    POCKET_ROOF_MM,
    MountPlate,
    countersink_depth,
    cut_all,
    insert_dimensions,
    standard_screw_length,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import FastenerSpec

RACK = "rack"

# EIA-310 19 inch rack: a panel 482.6 mm wide, its mounting holes 465.1 mm
# apart, and 1U = 44.45 mm with holes 15.875, 12.7, and 15.875 mm apart,
# centred. A 1U panel is 0.79 mm shorter than its unit, so it clears its
# neighbours.
RACK_PANEL_WIDTH_MM = 482.6
RACK_HOLE_SPACING_MM = 465.1
RACK_OPENING_MM = 450.85
RACK_UNIT_MM = 44.45
RACK_PANEL_HEIGHT_MM = 43.66
RACK_HOLE_PITCH_MM = 15.875
RACK_HOLE_DIAMETER_MM = 7.0

# The two pads at each end of the front wall sit this far above and below
# mid-height, so they resist the enclosure's weight pitching about its front
# edge.
PAD_HEIGHT_OFFSET_MM = 6.0
_PAD_WALL_MARGIN_MM = 1.0
_FLANGE_MARGIN_MM = 2.0
_FLANGE_MARGIN_STEP_MM = 0.25
_HEIGHT_MARGIN_MM = 1.0
_MINIMUM_REACH_MM = 10.0
# A pad's footprint on the wall must be solid to within this fraction.
_COVERED_OPENING_TOLERANCE = 0.01


@dataclass(frozen=True)
class FrontPads:
    """Two pads at the left end of the front wall and two at the right."""

    left: tuple[tuple[float, float], ...]
    right: tuple[tuple[float, float], ...]
    diameter_mm: float
    height_mm: float
    pocket_diameter_mm: float
    pocket_depth_mm: float
    outer_width_mm: float
    # How far each ear's flange runs past its pads' inner edge: the full margin,
    # or less where an opening in the wall would otherwise be covered.
    flange_margin_mm: float = 2.0

    @property
    def positions(self) -> tuple[tuple[float, float], ...]:
        """One ear's pads, as ``(x, z)``."""
        return self.left


def is_rack(kind: str | None) -> bool:
    return kind == RACK


def front_pads(
    base: cq.Workplane,
    *,
    outer_size_mm: tuple[float, float, float],
    enclosure_height_mm: float,
    wall_mm: float,
    fastener: FastenerSpec,
    hole_compensation_mm: float = 0.0,
) -> FrontPads:
    """Two pads stacked at each end of the front wall, about mid-height.

    The stack is at the corner, where the wall is solid, and its height
    resists the enclosure pitching forward off the ears. It is refused if an
    opening in the wall lies under a pad. ``outer_size_mm`` is the base's outer size;
    ``enclosure_height_mm`` is the height with the lid, which is what has to
    fit in 1U.
    """

    width, _, base_height = outer_size_mm
    insert_diameter, pocket_depth = insert_dimensions(fastener)
    diameter = insert_diameter + 2 * 1.8
    radius = diameter / 2
    # The pocket ends POCKET_ROOF_MM short of the wall's inner face.
    height = max(pocket_depth + POCKET_ROOF_MM - wall_mm, MINIMUM_PAD_HEIGHT_MM)
    zc = enclosure_height_mm / 2
    low = zc - PAD_HEIGHT_OFFSET_MM
    high = zc + PAD_HEIGHT_OFFSET_MM

    if low - radius < _PAD_WALL_MARGIN_MM or high + radius > (
        base_height - _PAD_WALL_MARGIN_MM
    ):
        raise ValueError(
            f"The {base_height:.1f} mm wall is too low for front pads at mid-height"
        )

    x0 = wall_mm + radius

    if x0 + radius > width / 2:
        raise ValueError("The enclosure is too narrow for rack-ear pads")

    shape = _solids(base)
    left = ((x0, high), (x0, low))
    right = tuple((width - x, z) for x, z in left)

    for end, positions in (("left", left), ("right", right)):
        if not all(_on_solid_wall(shape, x, z, radius, wall_mm) for x, z in positions):
            raise ValueError(
                f"Rack-ear pads at the {end} end of the front wall would cover "
                "an opening in it"
            )

    margin = _flange_margin(shape, x0 + radius, width, base_height, wall_mm)

    if margin is None:
        raise ValueError(
            "A rack ear's flange, even flush with its pads, would cover an opening "
            f"within {x0 + radius:.1f} mm of an end of the front wall: move the "
            "opening in, or use another mount"
        )

    return FrontPads(
        left=left,
        right=right,
        diameter_mm=diameter,
        height_mm=height,
        pocket_diameter_mm=insert_diameter + hole_compensation_mm,
        pocket_depth_mm=pocket_depth,
        outer_width_mm=width,
        flange_margin_mm=margin,
    )


def _along_y(
    radius: float, length: float, *, x: float, y: float, z: float, forward: bool
) -> cq.Solid:
    """A cylinder from ``y``, toward the front (-Y) or the back (+Y)."""

    return cq.Solid.makeCylinder(
        radius,
        length,
        pnt=cq.Vector(x, y, z),
        dir=cq.Vector(0, -1 if forward else 1, 0),
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


def _flange_margin(
    shape: cq.Shape, pad_edge: float, width: float, height: float, wall_mm: float
) -> float | None:
    """How far past the pads' inner edge both ears' flanges may run: each stands
    the full panel height in front of the wall, so the wall behind it must be
    whole, or a port there would be closed off. The full margin if the wall
    allows, less if an opening is near, ``None`` if even a flange flush with the
    pads would cover one."""

    margin = _FLANGE_MARGIN_MM

    while margin >= -1e-9:
        reach = pad_edge + margin

        if _strip_solid(shape, 0.0, reach, height, wall_mm) and _strip_solid(
            shape, width - reach, width, height, wall_mm
        ):
            return round(max(margin, 0.0), 3)

        margin -= _FLANGE_MARGIN_STEP_MM

    return None


def _strip_solid(
    shape: cq.Shape, x_lo: float, x_hi: float, height: float, wall_mm: float
) -> bool:
    """Whether the front wall between ``x_lo`` and ``x_hi`` is whole, below its top
    margin: no opening through it where a rack ear's flange would stand."""

    z_lo, z_hi = _PAD_WALL_MARGIN_MM, height - _PAD_WALL_MARGIN_MM
    slab = cq.Solid.makeBox(
        x_hi - x_lo, wall_mm, z_hi - z_lo, pnt=cq.Vector(x_lo, 0.0, z_lo)
    )
    covered = intersection_volume(shape, slab) / slab.Volume()

    return covered >= 1.0 - _COVERED_OPENING_TOLERANCE


def _on_solid_wall(
    shape: cq.Shape, x: float, z: float, radius: float, wall_mm: float
) -> bool:
    """Whether a pad's footprint on the front wall is all wall, with no
    opening under it."""

    slab = _along_y(radius, wall_mm, x=x, y=0.0, z=z, forward=False)
    covered = intersection_volume(shape, slab) / slab.Volume()

    return covered >= 1.0 - _COVERED_OPENING_TOLERANCE


def add_front_pads(base: cq.Workplane, pads: FrontPads) -> cq.Workplane:
    """Fuse the pads to the front wall and cut their insert pockets, which
    open on each pad's front face."""

    everywhere = (*pads.left, *pads.right)

    for x, z in everywhere:
        pad = _along_y(
            pads.diameter_mm / 2,
            pads.height_mm + PAD_EMBED_MM,
            x=x,
            y=PAD_EMBED_MM,
            z=z,
            forward=True,
        )
        base = base.union(cq.Workplane("XY").add(pad))

    for x, z in everywhere:
        # Start in front of the pad so the pocket's mouth is cut clean.
        pocket = _along_y(
            pads.pocket_diameter_mm / 2,
            pads.pocket_depth_mm + 1.0,
            x=x,
            y=-(pads.height_mm + 1.0),
            z=z,
            forward=False,
        )
        base = base.cut(cq.Workplane("XY").add(pocket))

    return base


def build_rack_ears(
    pads: FrontPads,
    *,
    enclosure_height_mm: float,
    fastener: FastenerSpec,
    plate_mm: float,
    compensation: float = 0.0,
) -> MountPlate:
    """The left and right ears, each seated on its end's pads."""

    width = pads.outer_width_mm

    if width > RACK_OPENING_MM:
        raise ValueError(
            f"The enclosure is {width:.0f} mm wide; a 19 inch rack opens "
            f"{RACK_OPENING_MM:.0f} mm"
        )

    if enclosure_height_mm + 2 * _HEIGHT_MARGIN_MM > RACK_PANEL_HEIGHT_MM:
        raise ValueError(
            f"The enclosure is {enclosure_height_mm:.1f} mm tall; 1U holds "
            f"{RACK_PANEL_HEIGHT_MM - 2 * _HEIGHT_MARGIN_MM:.1f} mm, and only "
            "1U is supported"
        )

    head = fastener.nominal_diameter_mm * HEAD_DIAMETER_FACTOR
    cone_depth = countersink_depth(fastener, plate_mm)
    reach = (RACK_PANEL_WIDTH_MM - width) / 2
    margin = pads.diameter_mm / 2 + pads.flange_margin_mm
    rail = (RACK_PANEL_WIDTH_MM - RACK_HOLE_SPACING_MM) / 2

    if reach < _MINIMUM_REACH_MM:
        raise ValueError(
            f"The enclosure is {width:.0f} mm wide, nearly as wide as the "
            "rack; there is no room for an ear's rail holes"
        )

    zc = enclosure_height_mm / 2
    back = -pads.height_mm
    front = back - plate_mm
    screw_hole = fastener.clearance_hole_mm + compensation
    rack_hole = RACK_HOLE_DIAMETER_MM + compensation

    def ear(mirror: bool) -> tuple[cq.Workplane, float]:
        positions = pads.right if mirror else pads.left
        xs = [x for x, _ in positions]
        x_lo = min(xs) - margin if mirror else -reach
        x_hi = width + reach if mirror else max(xs) + margin
        rack_hole_x = width + reach - rail if mirror else -reach + rail
        flange = cq.Workplane("XY").add(
            cq.Solid.makeBox(
                x_hi - x_lo,
                plate_mm,
                RACK_PANEL_HEIGHT_MM,
                pnt=cq.Vector(x_lo, front, zc - RACK_PANEL_HEIGHT_MM / 2),
            )
        )
        cutters: list[cq.Shape] = []

        for x, z in positions:
            cutters.append(
                _along_y(
                    screw_hole / 2,
                    plate_mm + 2.0,
                    x=x,
                    y=back + 1.0,
                    z=z,
                    forward=True,
                )
            )
            # The cone opens on the flange's front face, sinking a flat head.
            cutters.append(
                cq.Solid.makeCone(
                    screw_hole / 2,
                    head / 2 + 0.01,
                    cone_depth + 0.01,
                    pnt=cq.Vector(x, front + cone_depth, z),
                    dir=cq.Vector(0, -1, 0),
                )
            )

        for k in (-1, 0, 1):
            cutters.append(
                _along_y(
                    rack_hole / 2,
                    plate_mm + 2.0,
                    x=rack_hole_x,
                    y=back + 1.0,
                    z=zc + k * RACK_HOLE_PITCH_MM,
                    forward=True,
                )
            )

        return cut_all(flange, *cutters), x_hi - x_lo

    left, left_length = ear(False)
    right, right_length = ear(True)

    return MountPlate(
        plate=left,
        thickness_mm=plate_mm,
        recommended_screw_mm=standard_screw_length(plate_mm + pads.pocket_depth_mm),
        size_mm=(max(left_length, right_length), RACK_PANEL_HEIGHT_MM),
        attachment=(
            "19 inch rack, 1U (EIA-310): two flat ears, each screwed to two "
            "pads on the front wall and held to the rack by three rail holes; "
            "the enclosure sits centred, "
            f"{pads.height_mm + plate_mm:.0f} mm behind the rack face"
        ),
        pieces={"mount-left": left, "mount-right": right},
    )
