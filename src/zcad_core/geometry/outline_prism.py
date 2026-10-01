"""A polygon outline extruded into a solid, grown or shrunk by an offset."""

from __future__ import annotations

from collections.abc import Sequence

import cadquery as cq


def outline_prism(
    points: Sequence[tuple[float, float]],
    z0: float,
    z1: float,
    offset_mm: float = 0.0,
) -> cq.Workplane:
    """The outline from ``z0`` to ``z1``, grown by ``offset_mm`` (shrunk if
    negative); a grown corner is rounded."""

    if z1 <= z0:
        raise ValueError("z1 must be above z0")

    sketch = cq.Workplane("XY").workplane(offset=z0).polyline(list(points)).close()

    if offset_mm:
        sketch = sketch.offset2D(offset_mm, "arc")

    return sketch.extrude(z1 - z0)
