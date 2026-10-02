"""A board and its parts as solids, in the board's own frame.

The board's top face is ``z == 0``, its centre is the origin, its outline (a
rectangle or a polygon) runs down to ``-thickness`` with its mounting holes
cut through, and each part is a box above or below it. Shared by the PCB test
fixture and the group enclosure's board bays, which both need a board to clear.
"""

from __future__ import annotations

import cadquery as cq

from zcad_core.features.pcb_fixture_plan import mounting_holes, outline_points
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.hardware.electronics.board_file import (
    ENVELOPE_IDENTIFIER,
    BoardFileSpec,
)


def cylinder(x: float, y: float, z0: float, z1: float, diameter: float) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeCylinder(
            diameter / 2, z1 - z0, pnt=cq.Vector(x, y, z0), dir=cq.Vector(0, 0, 1)
        )
    )


def box(
    cx: float, cy: float, width: float, depth: float, z0: float, z1: float
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            width, depth, z1 - z0, pnt=cq.Vector(cx - width / 2, cy - depth / 2, z0)
        )
    )


def board_assembly(board: BoardFileSpec, *, with_envelope: bool = True) -> cq.Shape:
    """The board and its parts as solids: its outline with its mounting holes,
    and each part's box."""

    points = outline_points(board)
    body = outline_prism(points, -board.board_thickness_mm, 0.0)

    if board.mounting_hole_diameter_mm is not None:
        for x, y in mounting_holes(board):
            body = body.cut(
                cylinder(
                    x,
                    y,
                    -board.board_thickness_mm - 1.0,
                    1.0,
                    board.mounting_hole_diameter_mm,
                )
            )

    shapes: list[cq.Shape] = [shape_of(body)]

    for part in board.components:
        if part.identifier == ENVELOPE_IDENTIFIER and not with_envelope:
            continue

        z0 = part.bottom_offset_from_board_top_mm
        shapes.append(
            shape_of(
                box(
                    part.center_x_mm,
                    part.center_y_mm,
                    part.width_mm,
                    part.depth_mm,
                    z0,
                    z0 + part.height_mm,
                )
            )
        )

    return cq.Compound.makeCompound(shapes)


def shape_of(model: cq.Workplane) -> cq.Shape:
    value = model.val()

    if not isinstance(value, cq.Shape):
        raise TypeError("Expected a shape")

    return value
