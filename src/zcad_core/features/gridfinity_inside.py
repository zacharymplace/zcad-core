"""The inside of a Gridfinity bin: dividers into compartments, and label tabs.

Dividers split the bin's inside into equal compartments, ``x`` across and ``y`` front to back.
They stand from the floor to just under where a stacked bin's base comes down into the lip, so a
bin still stacks; without a lip, to the wall's top. A label tab is a shelf along the back wall of
each compartment in the back row, its top level with the dividers', carried on a 45-degree
underside so it prints with nothing under it.

Neither Gridfinity source fixes these; the figures here are the engine's own and are registered
as design values. Gridfinity Rebuilt's tab rests on a 36-degree support, which would overhang past
the 45 degrees the engine prints to, so the tab here is its own shape.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.gridfinity_shapes import box
from zcad_core.features.gridfinity_standard import BASE_HEIGHT_MM

# A divider is this thick, or the printer's minimum wall if that is more. (Gridfinity Rebuilt's
# own d_div is 1.2 mm.)
DIVIDER_MM = 1.2
# Dividers stop this far under where a stacked base comes down into the lip.
STACK_CLEARANCE_MM = 0.5
# The narrowest compartment the engine makes.
MINIMUM_COMPARTMENT_MM = 10.0
# A label tab reaches this far out from the back wall, and is this thick at its front edge.
LABEL_TAB_DEPTH_MM = 12.0
LABEL_TAB_FACE_MM = 1.2


@dataclass(frozen=True)
class Inside:
    """The bin's inside as the dividers split it: the cavity's size, the dividers' thickness and
    top, and each compartment's extent (x0, x1, y0, y1)."""

    width_mm: float
    depth_mm: float
    divider_mm: float
    top_mm: float
    compartments: tuple[tuple[float, float, float, float], ...]


def _spans(length: float, count: int, divider: float) -> list[tuple[float, float]]:
    each = (length - (count - 1) * divider) / count
    start = -length / 2

    return [
        (start + i * (each + divider), start + i * (each + divider) + each)
        for i in range(count)
    ]


def plan_inside(
    width: float,
    depth: float,
    divisions: tuple[int, int],
    top: float,
    least_wall: float,
) -> Inside:
    """Split a cavity ``width`` by ``depth`` into compartments; refused if one would be narrower
    than the least the engine makes."""

    divider = max(DIVIDER_MM, least_wall)
    across, along = divisions

    for name, length, count in (
        ("across", width, across),
        ("front to back", depth, along),
    ):
        if count < 1:
            raise ValueError(f"A bin is divided into at least 1 compartment {name}")

        each = (length - (count - 1) * divider) / count

        if each < MINIMUM_COMPARTMENT_MM:
            raise ValueError(
                f"{count} compartments {name} would each be {each:.1f} mm, under the "
                f"{MINIMUM_COMPARTMENT_MM:g} mm least"
            )

    return Inside(
        width_mm=width,
        depth_mm=depth,
        divider_mm=divider,
        top_mm=top,
        compartments=tuple(
            (x0, x1, y0, y1)
            for y0, y1 in _spans(depth, along, divider)
            for x0, x1 in _spans(width, across, divider)
        ),
    )


def divider_walls(inside: Inside) -> list[cq.Workplane]:
    """The walls between compartments, reaching into the bin's walls at their ends."""

    walls = []
    xs = sorted(
        {x1 for x0, x1, _, _ in inside.compartments if x1 < inside.width_mm / 2 - 1e-6}
    )
    ys = sorted(
        {y1 for _, _, y0, y1 in inside.compartments if y1 < inside.depth_mm / 2 - 1e-6}
    )
    reach_x, reach_y = inside.width_mm / 2 + 1.0, inside.depth_mm / 2 + 1.0
    z0 = BASE_HEIGHT_MM - 0.01

    for x in xs:
        walls.append(
            box(x, x + inside.divider_mm, -reach_y, reach_y, z0, inside.top_mm)
        )

    for y in ys:
        walls.append(
            box(-reach_x, reach_x, y, y + inside.divider_mm, z0, inside.top_mm)
        )

    return walls


def label_tabs(inside: Inside) -> list[cq.Workplane]:
    """A shelf along the back wall of each compartment in the back row, refused for a compartment
    too shallow to take one and still be reached into."""

    back = max(y1 for _, _, _, y1 in inside.compartments)
    row = [c for c in inside.compartments if abs(c[3] - back) <= 1e-6]
    tabs = []

    for x0, x1, y0, y1 in row:
        if y1 - y0 < 2 * LABEL_TAB_DEPTH_MM:
            raise ValueError(
                f"A label tab reaches {LABEL_TAB_DEPTH_MM:g} mm from the back wall, and the "
                f"back compartments are {y1 - y0:.1f} mm deep: they need twice that"
            )

        top = inside.top_mm
        d, face = LABEL_TAB_DEPTH_MM, LABEL_TAB_FACE_MM
        # Seen from the side: the shelf's top, its front face, and a 45-degree underside back
        # to the wall.
        profile = [
            (y1 + 1.0, top),
            (y1 - d, top),
            (y1 - d, top - face),
            (y1, top - face - d),
            (y1 + 1.0, top - face - d),
        ]
        shelf = (
            cq.Workplane("YZ")
            .workplane(offset=x0)
            .polyline(profile)
            .close()
            .extrude(x1 - x0)
        )
        tabs.append(shelf)

    return tabs


def compartment_points(inside: Inside) -> list[tuple[float, float, float]]:
    """A point in each compartment, halfway up and toward its front, clear of a label tab, which
    must be empty."""

    z = (BASE_HEIGHT_MM + inside.top_mm) / 2

    return [
        ((x0 + x1) / 2, y0 + 0.4 * (y1 - y0), z)
        for x0, x1, y0, y1 in inside.compartments
    ]
