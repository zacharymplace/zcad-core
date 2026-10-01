"""The footprint of a part seen from above: the outline of its shadow.

A fixture's nest is a pocket that follows this outline, so a part always
drops straight out of it: the pocket is the part's shadow and nothing under or
over the part's edge can catch. The shadow is the union of every face seen
along Z, undercuts and overhangs included, which is why it is read from the
whole part and not from its top face.

It is found by raster: the part is tessellated, every triangle is drawn onto a
grid of square pixels, and the outer boundary of the filled picture is traced.
The grid is dilated by a pixel so the result is never smaller than the part,
and the traced polygon is thinned to within a pixel of itself. The raster
costs a little accuracy, a pixel or so, and buys independence from the CAD
kernel's boolean operations, which are slow and fragile on a real model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cadquery as cq
import numpy as np
from scipy import ndimage  # type: ignore[import-untyped]

from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_outline import Point

TESSELLATION_TOLERANCE_MM = 0.1
# The grid is at most this many pixels across the part's longer side.
MAXIMUM_PIXELS = 1500
MINIMUM_RESOLUTION_MM = 0.05

# Moore neighbourhood as (row, column) steps, clockwise starting west.
_RING = (
    (0, -1),
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
)


@dataclass(frozen=True)
class Silhouette:
    """A part's shadow: a counter-clockwise polygon in the part's own frame."""

    points: tuple[Point, ...]
    area_mm2: float
    resolution_mm: float
    # How much of the shadow is flat material at the part's top, 0 to 1.
    top_share: float


def _rasterise(
    vertices: np.ndarray,
    triangles: np.ndarray,
    origin: Point,
    resolution: float,
    shape: tuple[int, int],
) -> np.ndarray:
    """Mark every pixel whose centre a triangle covers."""

    mask = np.zeros(shape, dtype=bool)
    slack = resolution * 0.5

    for a, b, c in triangles:
        p = vertices[[a, b, c], :2]
        low = np.floor((p.min(axis=0) - slack - origin) / resolution).astype(int)
        high = np.ceil((p.max(axis=0) + slack - origin) / resolution).astype(int)
        columns = np.arange(max(low[0], 0), min(high[0], shape[1] - 1) + 1)
        rows = np.arange(max(low[1], 0), min(high[1], shape[0] - 1) + 1)

        if not len(columns) or not len(rows):
            continue

        px = origin[0] + (columns + 0.5) * resolution
        py = origin[1] + (rows + 0.5) * resolution
        gx, gy = np.meshgrid(px, py)
        (x0, y0), (x1, y1), (x2, y2) = p
        denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)

        if abs(denominator) < 1e-12:
            # A wall seen edge-on: it draws a line, which the dilation widens.
            _draw_line(mask, p, origin, resolution)

            continue

        w0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / denominator
        w1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / denominator
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        mask[np.ix_(rows, columns)] |= inside

    return mask


def _draw_line(
    mask: np.ndarray, points: np.ndarray, origin: Point, resolution: float
) -> None:
    """Mark the pixels along a degenerate triangle's longest edge."""

    best = max(
        ((points[i], points[(i + 1) % 3]) for i in range(3)),
        key=lambda edge: float(np.linalg.norm(edge[1] - edge[0])),
    )
    start, end = best
    steps = max(2, int(np.linalg.norm(end - start) / resolution * 2))

    for t in np.linspace(0.0, 1.0, steps):
        x, y = start + (end - start) * t
        column = int((x - origin[0]) / resolution)
        row = int((y - origin[1]) / resolution)

        if 0 <= row < mask.shape[0] and 0 <= column < mask.shape[1]:
            mask[row, column] = True


def _draw_solid(
    mask: np.ndarray, solid: cq.Shape, origin: Point, resolution: float
) -> None:
    raw_vertices, raw_triangles = solid.tessellate(TESSELLATION_TOLERANCE_MM, 0.3)

    if not raw_triangles:
        return

    vertices = np.array([[v.x, v.y, v.z] for v in raw_vertices])
    mask |= _rasterise(
        vertices,
        np.array(raw_triangles),
        origin,
        resolution,
        mask.shape,
    )


def _shadow_mask(
    shape: cq.Shape, origin: Point, resolution: float, size: tuple[int, int]
) -> np.ndarray:
    """The shadow of every solid drawn on one grid, largest first. A solid whose
    whole bounding box already lies inside the shadow cannot widen it, so it is
    never tessellated: that is nearly every component on a board, and
    tessellating them is most of the time."""

    pieces = []

    for solid in shape.Solids():
        box = solid.BoundingBox()
        pieces.append((box.xlen * box.ylen, box, solid))

    pieces.sort(key=lambda item: -item[0])
    mask = np.zeros(size, dtype=bool)

    for _, box, solid in pieces:
        if mask.any():
            low_c = max(int((box.xmin - origin[0]) / resolution) - 1, 0)
            high_c = min(int((box.xmax - origin[0]) / resolution) + 2, size[1])
            low_r = max(int((box.ymin - origin[1]) / resolution) - 1, 0)
            high_r = min(int((box.ymax - origin[1]) / resolution) + 2, size[0])

            if mask[low_r:high_r, low_c:high_c].all():
                continue

        _draw_solid(mask, solid, origin, resolution)

    return mask


def _trace(mask: np.ndarray) -> list[tuple[int, int]]:
    """The outer boundary of the one filled region, as pixels in order
    (Moore-neighbour tracing, stopped by Jacob's criterion)."""

    rows, columns = np.nonzero(mask)
    order = np.lexsort((columns, rows))
    start = (int(rows[order[0]]), int(columns[order[0]]))
    height, width = mask.shape

    def filled(row: int, column: int) -> bool:
        return 0 <= row < height and 0 <= column < width and bool(mask[row, column])

    contour = [start]
    current = start
    backtrack = 0
    first: tuple[int, int] | None = None

    for _ in range(4 * mask.size):
        found = None

        for step in range(1, 9):
            index = (backtrack + step) % 8
            row = current[0] + _RING[index][0]
            column = current[1] + _RING[index][1]

            if filled(row, column):
                found = (index, row, column)

                break

        if found is None:
            break

        index, row, column = found

        if current == start and first is not None and (row, column) == first:
            break

        if first is None:
            first = (row, column)

        before = (index - 1) % 8
        pr, pc = current[0] + _RING[before][0], current[1] + _RING[before][1]
        backtrack = _RING.index((pr - row, pc - column))
        current = (row, column)
        contour.append(current)

    if contour[-1] == start and len(contour) > 1:
        contour.pop()

    return contour


def silhouette(shape: cq.Shape, *, resolution_mm: float | None = None) -> Silhouette:
    """The shadow of a shape along Z, about the centre of its bounding box.

    Raises ``ValueError`` if the shadow is more than one piece (the shape is
    several parts apart from each other, so no one pocket holds them) or has no
    area. A shadow with holes is filled: a pocket has no island.
    """

    bounds = shape.BoundingBox()
    centre = ((bounds.xmin + bounds.xmax) / 2, (bounds.ymin + bounds.ymax) / 2)
    longest = max(bounds.xlen, bounds.ylen)

    if longest <= 0:
        raise ValueError("The part has no extent to cast a shadow")

    resolution = resolution_mm or max(MINIMUM_RESOLUTION_MM, longest / MAXIMUM_PIXELS)
    margin = 3 * resolution
    origin = (bounds.xmin - margin, bounds.ymin - margin)
    size = (
        math.ceil((bounds.ylen + 2 * margin) / resolution),
        math.ceil((bounds.xlen + 2 * margin) / resolution),
    )
    mask = _shadow_mask(shape, origin, resolution, size)
    mask = ndimage.binary_dilation(mask, iterations=1)
    mask = ndimage.binary_fill_holes(mask)
    _, pieces = ndimage.label(mask)

    if pieces == 0:
        raise ValueError("The part has no extent to cast a shadow")

    if pieces > 1:
        raise ValueError(
            f"The part's shadow is {pieces} separate pieces, so no one pocket "
            "holds it; name the one solid that is the part"
        )

    contour = _trace(mask)
    points = [
        (
            origin[0] + (column + 0.5) * resolution - centre[0],
            origin[1] + (row + 0.5) * resolution - centre[1],
        )
        for row, column in contour
    ]
    thinned = board_outline.simplified(points, resolution)
    polygon = board_outline.counter_clockwise(thinned)

    if len(polygon) < 3 or not board_outline.is_simple(polygon):
        raise ValueError("The part's shadow could not be traced to a clean outline")

    area = abs(board_outline.signed_area(polygon))

    return Silhouette(
        points=polygon,
        area_mm2=area,
        resolution_mm=resolution,
        top_share=_top_share(shape, bounds.zmax, area),
    )


def _top_share(shape: cq.Shape, top: float, area: float) -> float:
    """The area of flat faces at the part's top, as a share of its shadow."""

    flat = 0.0

    for face in shape.Faces():
        if face.geomType() != "PLANE":
            continue

        box = face.BoundingBox()

        if box.zlen < 1e-3 and abs(box.zmax - top) < 1e-3:
            flat += face.Area()

    return min(1.0, flat / area) if area > 0 else 0.0
