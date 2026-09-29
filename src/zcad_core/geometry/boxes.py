"""Axis-aligned boxes given by their coordinate spans."""

from __future__ import annotations

import cadquery as cq


def box_between(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    """A box spanning each pair of coordinates, in either order."""
    (x0, x1), (y0, y1), (z0, z1) = sorted(x), sorted(y), sorted(z)

    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )
