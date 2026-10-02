"""A board turned over, so a fixture can probe its bottom side from above.

A fixture presses its pins down onto the board's top face, so probing the bottom side means
holding the board **turned over**: bottom face up, its parts hanging below in the nest's
cavity. The nest already holds a board by its edge over a cavity for the parts under it, so
the bottom-side fixture is the top-side fixture for the board turned over, and everything it
checks (the pins' reach, their pitch, the clearance over parts, the release) is checked on
that board.

The board is turned **left to right**, about its Y axis, as a page is: a point at ``(x, y)``
is at ``(-x, y)`` and a part's height above the face becomes its depth below it. Seen from
above, the turned board is the bottom side as it looks when you pick the board up and look at
it. A fixture's records and its plate are in this frame.
"""

from __future__ import annotations

from dataclasses import replace

from zcad_core.hardware.electronics.board_file import BoardFileSpec
from zcad_core.hardware.electronics.board_test_points import BoardTestPoint
from zcad_core.hardware.electronics.connectors import BoardEdge

_MIRRORED_EDGES: dict[BoardEdge, BoardEdge] = {
    "negative_x": "positive_x",
    "positive_x": "negative_x",
}


def _edge(edge: BoardEdge) -> BoardEdge:
    """An edge after the board is turned left to right."""

    return _MIRRORED_EDGES.get(edge, edge)


def _flipped_offset(bottom: float, height: float, thickness: float) -> float:
    """Where a part's bottom is, from the board's top face, once the board is turned: a part
    that stood above the face hangs below it, and one that hung below stands above."""

    return -thickness - bottom - height


def turn_over(board: BoardFileSpec) -> BoardFileSpec:
    """The board as the fixture holds it when probing its bottom side."""

    thickness = board.board_thickness_mm
    outline = (
        None
        if board.outline_points_mm is None
        else tuple((-x, y) for x, y in reversed(board.outline_points_mm))
    )
    holes = (
        None
        if board.mounting_hole_positions_mm is None
        else tuple((-x, y) for x, y in board.mounting_hole_positions_mm)
    )
    components = tuple(
        replace(
            part,
            center_x_mm=-part.center_x_mm,
            bottom_offset_from_board_top_mm=_flipped_offset(
                part.bottom_offset_from_board_top_mm, part.height_mm, thickness
            ),
            access_edge=None if part.access_edge is None else _edge(part.access_edge),
        )
        for part in board.components
    )
    usb = board.usb_connector
    along_x = str(usb.board_edge).endswith("y")
    connector = replace(
        usb,
        board_edge=_edge(usb.board_edge),
        center_offset_mm=-usb.center_offset_mm if along_x else usb.center_offset_mm,
        bottom_offset_from_board_top_mm=_flipped_offset(
            usb.bottom_offset_from_board_top_mm, usb.height_mm, thickness
        ),
    )
    openings = tuple(
        replace(
            opening,
            edge=_edge(opening.edge),
            center_offset_mm=(
                -opening.center_offset_mm
                if str(opening.edge).endswith("y")
                else opening.center_offset_mm
            ),
            bottom_offset_from_board_top_mm=_flipped_offset(
                opening.bottom_offset_from_board_top_mm,
                opening.height_mm,
                thickness,
            ),
        )
        for opening in board.wall_openings
    )
    points = tuple(
        BoardTestPoint(
            identifier=p.identifier,
            x_mm=-p.x_mm,
            y_mm=p.y_mm,
            pad_diameter_mm=p.pad_diameter_mm,
            side="top" if p.side == "bottom" else "bottom",
            net=p.net,
        )
        for p in board.test_points
    )

    return replace(
        board,
        outline_points_mm=outline,
        mounting_hole_positions_mm=holes,
        components=components,
        usb_connector=connector,
        wall_openings=openings,
        test_points=points,
    )
