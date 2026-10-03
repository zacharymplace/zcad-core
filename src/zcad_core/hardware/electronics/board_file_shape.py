"""The checks of a board's own shape: its size and thickness, its outline, its mounting
holes and its standoffs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_file_findings import (
    _Findings,
    _number,
    _pair,
    _section,
)
from zcad_core.hardware.electronics.board_file_model import (
    BOARD_SIZE_RANGE_MM,
    BOARD_SIZE_WARNING_MM,
    HOLE_DIAMETER_RANGE_MM,
    STANDOFF_WALL_MM,
    THICKNESS_RANGE_MM,
    TYPICAL_THICKNESS_RANGE_MM,
)
from zcad_core.hardware.electronics.board_outline import Point


def _check_board(
    data: Mapping[str, Any], findings: _Findings
) -> tuple[float, float, float] | None:
    board = _section(data, "board", findings)

    if board is None:
        return None

    low, high = BOARD_SIZE_RANGE_MM
    width = _number(board, "width_mm", "board", findings, low=low, high=high)
    length = _number(board, "length_mm", "board", findings, low=low, high=high)
    thickness = _number(
        board,
        "thickness_mm",
        "board",
        findings,
        low=THICKNESS_RANGE_MM[0],
        high=THICKNESS_RANGE_MM[1],
    )

    if width is None or length is None or thickness is None:
        return None

    if max(width, length) > BOARD_SIZE_WARNING_MM:
        findings.warn(
            f"The board is {width:g} x {length:g} mm; check the numbers are "
            "millimetres, not centimetres or inches"
        )

    typical_low, typical_high = TYPICAL_THICKNESS_RANGE_MM

    if not typical_low <= thickness <= typical_high:
        findings.warn(
            f"A thickness of {thickness:g} mm is outside the usual "
            f"{typical_low:g} to {typical_high:g} mm for a PCB"
        )

    return width, length, thickness


def _outline(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
) -> tuple[Point, ...] | None:
    """The outline as polygon points, or ``None`` for the plain rectangle.

    A rounded rectangle becomes its points; a polygon's bounding box must be the
    board's stated size, centred on the origin."""

    outline = data.get("outline", "rectangle")

    if outline == "rectangle":
        return None

    advice = (
        "outline must be 'rectangle', or an object with type 'rounded_rectangle' "
        "(radius_mm) or 'polygon' (points_mm)"
    )

    if not isinstance(outline, Mapping):
        findings.error(advice)

        return None

    kind = outline.get("type")

    if kind == "rounded_rectangle":
        return _rounded_outline(outline, size, findings)

    if kind == "polygon":
        return _polygon_outline(outline, size, findings)

    findings.error(advice)

    return None


def _rounded_outline(
    outline: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
) -> tuple[Point, ...] | None:
    radius = _number(outline, "radius_mm", "outline", findings, low=0.1, high=200.0)

    if radius is None or size is None:
        return None

    if radius > min(size[0], size[1]) / 2:
        findings.error(
            f"outline.radius_mm is {radius:g}, more than half the board's "
            f"{min(size[0], size[1]):g} mm width"
        )

        return None

    return board_outline.rounded_rectangle_points(size[0], size[1], radius)


def _polygon_outline(
    outline: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
) -> tuple[Point, ...] | None:
    listed = outline.get("points_mm")

    if (
        not isinstance(listed, Sequence)
        or isinstance(listed, str)
        or not 3 <= len(listed) <= board_outline.MAXIMUM_POINTS
    ):
        findings.error(
            f"outline.points_mm must be a list of 3 to {board_outline.MAXIMUM_POINTS} "
            "points [x, y]"
        )

        return None

    points = [
        _pair(item, f"outline.points_mm[{index}]", findings)
        for index, item in enumerate(listed)
    ]
    ready = [point for point in points if point is not None]

    if len(ready) != len(points):
        return None

    if not board_outline.is_simple(ready):
        findings.error("outline.points_mm cross themselves: it must be one loop")

        return None

    area = board_outline.signed_area(ready)

    if abs(area) < 1.0:
        findings.error("outline.points_mm enclose no area")

        return None

    if size is None:
        return None

    x0, x1, y0, y1 = board_outline.bounding_box(ready)
    tolerance = board_outline.SIZE_TOLERANCE_MM

    if (
        abs((x1 - x0) - size[0]) > tolerance
        or abs((y1 - y0) - size[1]) > tolerance
        or abs((x0 + x1) / 2) > tolerance
        or abs((y0 + y1) / 2) > tolerance
    ):
        findings.error(
            f"outline.points_mm span {x1 - x0:g} x {y1 - y0:g} mm, centred "
            f"({(x0 + x1) / 2:g}, {(y0 + y1) / 2:g}); the board is "
            f"{size[0]:g} x {size[1]:g} mm, so the points must fill that "
            "rectangle about the origin"
        )

        return None

    if abs(area) < 0.3 * size[0] * size[1]:
        findings.warn(
            f"The outline fills only {abs(area) / (size[0] * size[1]):.0%} of "
            "its bounding rectangle, which the enclosure still encloses whole"
        )

    return board_outline.counter_clockwise(ready)


def _hole_positions(
    holes: Mapping[str, Any], findings: _Findings
) -> tuple[tuple[tuple[float, float], ...] | None, tuple[float, float] | None]:
    """The positions a file lists, or the spacing it gives, but not both."""

    positions = holes.get("positions_mm")
    spacing = holes.get("spacing_mm")

    if (positions is None) == (spacing is None):
        findings.error(
            "mounting_holes needs exactly one of positions_mm and spacing_mm"
        )

        return None, None

    if spacing is not None:
        pair = _pair(spacing, "mounting_holes.spacing_mm", findings)

        if pair is not None and min(pair) <= 0:
            findings.error("mounting_holes.spacing_mm must be positive")

            return None, None

        return None, pair

    if (
        not isinstance(positions, Sequence)
        or isinstance(positions, str)
        or not positions
    ):
        findings.error("mounting_holes.positions_mm must be a non-empty list")

        return None, None

    listed = []

    for index, item in enumerate(positions):
        pair = _pair(item, f"mounting_holes.positions_mm[{index}]", findings)

        if pair is not None:
            listed.append(pair)

    return (tuple(listed) if len(listed) == len(positions) else None), None


def _check_holes(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
    outline: tuple[Point, ...] | None = None,
) -> None:
    holes = _section(data, "mounting_holes", findings, required=False)

    if holes is None:
        if data.get("mounting_holes") is None:
            findings.warn(
                "No mounting holes: the board will sit in a snap-in cradle, "
                "which is held by its edges"
            )

        return

    low, high = HOLE_DIAMETER_RANGE_MM
    diameter = _number(
        holes, "diameter_mm", "mounting_holes", findings, low=low, high=high
    )
    positions, spacing = _hole_positions(holes, findings)

    if diameter is None or size is None:
        return

    width, length, _ = size
    points = positions
    radius = diameter / 2

    if spacing is not None:
        half_x, half_y = spacing[0] / 2, spacing[1] / 2
        points = (
            (-half_x, -half_y),
            (half_x, -half_y),
            (-half_x, half_y),
            (half_x, half_y),
        )

    for x, y in points or ():
        if outline is not None:
            depth = board_outline.depth_inside(outline, (x, y))
            outside, near = depth < radius, depth < radius + 1.5
        else:
            outside = abs(x) > width / 2 - radius or abs(y) > length / 2 - radius
            near = (
                abs(x) > width / 2 - radius - 1.5 or abs(y) > length / 2 - radius - 1.5
            )

        if outside:
            findings.error(
                f"A mounting hole at ({x:g}, {y:g}) is not inside the "
                f"{width:g} x {length:g} mm board"
                + (" outline" if outline is not None else "")
            )
        elif near:
            findings.warn(
                f"A mounting hole at ({x:g}, {y:g}) is near the edge: its "
                "standoff will stand out past the board"
            )

    needed = diameter + STANDOFF_WALL_MM

    for i, a in enumerate(points or ()):
        for b in (points or ())[i + 1 :]:
            if ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 < needed:
                findings.error(
                    f"Mounting holes at {a} and {b} are closer than a standoff's "
                    f"{needed:g} mm diameter"
                )


def _check_standoff(data: Mapping[str, Any], findings: _Findings) -> None:
    standoff = _section(data, "standoff", findings, required=False)

    if standoff is None:
        return

    _number(
        standoff, "height_mm", "standoff", findings, low=0.5, high=30.0, required=False
    )
    _number(
        standoff,
        "clearance_mm",
        "standoff",
        findings,
        low=0.0,
        high=1.5,
        required=False,
    )
