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
    """Cut a Z-directed slot through an origin-centered or Z=0-based plate.

    The cutter spans -2*base_height to +2*base_height. Arbitrarily translated
    models outside that range must be positioned by the caller first.
    """
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
        .extrude(base_height * 2, both=True)
    )

    return model.cut(cutter)
