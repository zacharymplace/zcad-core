"""Fail-closed solid intersection.

OCC can return an empty intersection for defective vendor solids (for
example, multi-shell PCBs) while a clipped formulation finds the overlap:
the XIAO ESP32-S3's PCB read 0 mm3 of overlap with a fixture base it
actually overlapped by 88.7 mm3. Every interference measurement uses this
module so that finding cannot be fixed in one place and missed in another.
"""

from __future__ import annotations

import cadquery as cq


def _overlap_box(first: cq.Shape, second: cq.Shape) -> cq.Shape | None:
    a, b = first.BoundingBox(), second.BoundingBox()
    low = (max(a.xmin, b.xmin), max(a.ymin, b.ymin), max(a.zmin, b.zmin))
    high = (min(a.xmax, b.xmax), min(a.ymax, b.ymax), min(a.zmax, b.zmax))

    if any(h <= lo for lo, h in zip(low, high, strict=True)):
        return None

    return cq.Solid.makeBox(
        high[0] - low[0],
        high[1] - low[1],
        high[2] - low[2],
        pnt=cq.Vector(*low),
    )


def solid_intersection(first: cq.Shape, second: cq.Shape) -> cq.Shape | None:
    """Largest of several boolean formulations, so a silent failure cannot pass.

    Returns None when the shapes do not overlap by any positive volume.
    Interference must fail closed, so the largest result wins.
    """

    box = _overlap_box(first, second)

    if box is None:
        return None

    candidates = []

    for chain in (
        (first, second),
        (second, first),
        (first, box, second),
        (second, box, first),
    ):
        shape: cq.Shape | None = chain[0]

        for other in chain[1:]:
            try:
                shape = shape.intersect(other) if shape is not None else None
            except ValueError:
                # cadquery raises on a null boolean result: no overlap here.
                shape = None

            if shape is None or shape.isNull():
                shape = None
                break

        if shape is not None and shape.Volume() > 0:
            candidates.append(shape)

    return max(candidates, key=lambda shape: shape.Volume(), default=None)


def intersection_volume(first: cq.Shape, second: cq.Shape) -> float:
    """Overlap volume in mm3, measured fail-closed."""

    intersection = solid_intersection(first, second)

    return 0.0 if intersection is None else float(intersection.Volume())
