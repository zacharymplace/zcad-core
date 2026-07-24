"""Reusable slot-cutting features."""

import cadquery as cq


def cut_through_slot(
    model: cq.Workplane,
    *,
    x: float,
    y: float,
    length: float,
    width: float,
    base_height: float,
    angle: float = 90.0,
) -> cq.Workplane:
    """Cut a centered through-slot from a solid."""
    if length <= 0:
        raise ValueError("length must be greater than zero")

    if width <= 0:
        raise ValueError("width must be greater than zero")

    if base_height <= 0:
        raise ValueError("base_height must be greater than zero")

    if width >= length:
        raise ValueError("width must be smaller than length")

    cutter = (
        cq.Workplane("XY")
        .center(
            x,
            y,
        )
        .slot2D(
            length,
            width,
            angle=angle,
        )
        .extrude(base_height * 2)
    )

    return model.cut(cutter)
