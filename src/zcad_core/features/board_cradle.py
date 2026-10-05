"""A snap-in cradle for boards without mounting holes.

The board rests on a ledge under its edges, a snap clip on each side edge
hooks over its top, and a stop behind the edge opposite its connector keeps
a cable push from shoving it back. The connector edge stays open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import cadquery as cq

from zcad_core.geometry.boxes import box_between
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.connectors import BoardEdge

# Rotation that turns the cradle's local frame (connector on negative Y)
# to face each edge.
_EDGE_ROTATION_DEG: dict[str, float] = {
    "negative_y": 0.0,
    "positive_x": 90.0,
    "positive_y": 180.0,
    "negative_x": -90.0,
}


@dataclass(frozen=True)
class BoardCradleParameters:
    """Geometry of one board cradle, in assembly coordinates."""

    center_x_mm: float
    center_y_mm: float
    board_width_mm: float
    board_depth_mm: float
    board_bottom_z_mm: float
    board_thickness_mm: float
    base_z_mm: float
    connector_edge: BoardEdge

    ledge_mm: float = 1.0
    wall_mm: float = 1.2
    clearance_mm: float = 0.3
    clip_width_mm: float = 6.0
    clip_overhang_mm: float = 0.8
    clip_lip_height_mm: float = 1.0
    clip_slot_mm: float = 1.0
    # Gap under the clip lip, so the board snaps in without preload.
    clip_gap_mm: float = 0.1
    # The board's outline about its centre, in the same orientation as
    # ``connector_edge`` is given, when it is not a plain rectangle: the
    # ledge and the stop then follow it and the clips stand at its sides.
    outline_points_mm: tuple[tuple[float, float], ...] | None = None
    # How far along the far edge, from its extreme, the stop wall reaches.
    stop_band_mm: float = 3.0

    def validate(self) -> None:
        positive = (
            "board_width_mm",
            "board_depth_mm",
            "board_thickness_mm",
            "ledge_mm",
            "wall_mm",
            "clip_width_mm",
            "clip_overhang_mm",
            "clip_lip_height_mm",
            "clip_slot_mm",
        )

        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        for name in ("clearance_mm", "clip_gap_mm"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

        if self.board_bottom_z_mm <= self.base_z_mm:
            raise ValueError("the board must sit above the cradle base")

        if self.connector_edge not in _EDGE_ROTATION_DEG:
            raise ValueError(f"unsupported connector edge: {self.connector_edge}")

        if self.clip_overhang_mm <= self.clearance_mm:
            raise ValueError("clip_overhang_mm must exceed clearance_mm")

        width, depth = self._local_footprint()

        if 2 * self.ledge_mm >= min(width, depth):
            raise ValueError("ledge_mm is too wide for the board")

        if self.clip_width_mm + 2 * self.clip_slot_mm >= depth:
            raise ValueError("clip_width_mm is too wide for the board edge")

        self._validate_outline(depth)

    def _validate_outline(self, depth: float) -> None:
        if self.outline_points_mm is None:
            return

        if len(self.outline_points_mm) < 3:
            raise ValueError("an outline needs at least three points")

        if depth / 2 - self.stop_band_mm <= (
            self.clip_width_mm / 2 + self.clip_slot_mm
        ):
            raise ValueError(
                "the board is too short for a cradle that follows its outline"
            )

    def _local_footprint(self) -> tuple[float, float]:
        """Board width across the clips and depth toward the connector."""
        if self.connector_edge in ("negative_y", "positive_y"):
            return self.board_width_mm, self.board_depth_mm

        return self.board_depth_mm, self.board_width_mm


def add_board_cradle(
    model: cq.Workplane,
    *,
    parameters: BoardCradleParameters,
) -> cq.Workplane:
    """Add a ledge, two side snap clips, and a back stop for one board."""
    parameters.validate()

    cradle = _local_cradle(parameters).rotate(
        (0, 0, 0), (0, 0, 1), _EDGE_ROTATION_DEG[parameters.connector_edge]
    )

    return model.union(
        cradle.translate((parameters.center_x_mm, parameters.center_y_mm, 0))
    )


def _local_cradle(p: BoardCradleParameters) -> cq.Workplane:
    """The cradle about the origin, connector edge toward negative Y."""
    if p.outline_points_mm is not None:
        return _local_outline_cradle(p, p.outline_points_mm)

    width, depth = p._local_footprint()
    half_w, half_d = width / 2, depth / 2
    outer_w = half_w + p.clearance_mm + p.wall_mm
    outer_d = half_d + p.clearance_mm + p.wall_mm
    board_top = p.board_bottom_z_mm + p.board_thickness_mm
    under_board = (p.base_z_mm - 1, p.board_bottom_z_mm + 1)
    inner_w, inner_d = half_w - p.ledge_mm, half_d - p.ledge_mm

    ledge = box_between(
        (-outer_w, outer_w), (-outer_d, outer_d), (p.base_z_mm, p.board_bottom_z_mm)
    ).cut(box_between((-inner_w, inner_w), (-inner_d, inner_d), under_board))

    # Free each clip from the ledge so it can flex.
    slot = p.clip_width_mm / 2 + p.clip_slot_mm

    for side in (-1, 1):
        ledge = ledge.cut(
            box_between(
                (side * (inner_w - 0.01), side * (outer_w + 1)),
                (-slot, slot),
                under_board,
            )
        )

    stop = box_between(
        (-outer_w, outer_w),
        (half_d + p.clearance_mm, outer_d),
        (p.board_bottom_z_mm - 0.01, board_top),
    )
    cradle = ledge.union(stop)

    for side in (-1, 1):
        cradle = cradle.union(_clip(p, side=side, half_w=half_w, board_top=board_top))

    return cradle


def _prism(
    points: tuple[tuple[float, float], ...],
    z0: float,
    z1: float,
    offset_mm: float = 0.0,
) -> cq.Workplane:
    """The outline, grown by ``offset_mm`` (shrunk if negative), from ``z0`` to ``z1``."""
    sketch = cq.Workplane("XY").workplane(offset=z0).polyline(list(points)).close()

    if offset_mm:
        sketch = sketch.offset2D(offset_mm, "arc")

    return sketch.extrude(z1 - z0)


def _local_outline_cradle(
    p: BoardCradleParameters, board_frame: tuple[tuple[float, float], ...]
) -> cq.Workplane:
    """A cradle that follows a polygon outline, connector edge toward negative Y.

    ``board_frame`` is in the orientation the cradle is finally rotated into, so
    it is turned back to the local one. The ledge is a ring under the edge, the
    stop a wall round the far end, and each clip stands where the outline
    crosses the middle of the board, so the outline must be roughly straight
    there."""
    points = board_outline.rotated(board_frame, -_EDGE_ROTATION_DEG[p.connector_edge])
    board_top = p.board_bottom_z_mm + p.board_thickness_mm
    under_board = (p.base_z_mm - 1, p.board_bottom_z_mm + 1)
    grow = p.clearance_mm + p.wall_mm
    ymax = max(y for _, y in points)
    reach = max(abs(x) for x, _ in points) + grow + 1

    ledge = _prism(points, p.base_z_mm, p.board_bottom_z_mm, grow).cut(
        _prism(points, under_board[0], under_board[1], -p.ledge_mm)
    )

    # Each clip stands outside the outermost edge across its width, so a
    # castellated or notched edge does not put the stem inside the board.
    half_clip = p.clip_width_mm / 2
    chords = [
        c
        for step in range(13)
        if (c := board_outline.chord(points, -half_clip + p.clip_width_mm * step / 12))
    ]

    if not chords:
        raise ValueError("the outline does not cross the middle of the board")

    slot = half_clip + p.clip_slot_mm
    edges = {-1: min(c[0] for c in chords), 1: max(c[1] for c in chords)}
    # The lip reaches this far in from the outermost edge; where the edge falls
    # back that far anywhere across the clip, the lip holds nothing there, as on
    # a hexagon's corner or a small round board.
    lip_reach = p.clip_overhang_mm - p.clearance_mm
    recess = {
        -1: max(c[0] for c in chords) - edges[-1],
        1: edges[1] - min(c[1] for c in chords),
    }

    for side, moved in recess.items():
        if moved >= lip_reach - 1e-9:
            raise ValueError(
                f"the board's edge under the {'left' if side < 0 else 'right'} clip "
                f"falls back {moved:.2f} mm across the clip's "
                f"{p.clip_width_mm:g} mm width, and the lip reaches only "
                f"{lip_reach:.2f} mm over it: the clip would barely hold the board "
                "there; use standoffs, or a board edge straight where the clips stand"
            )

    for side, edge in edges.items():
        # Free each clip from the ledge so it can flex; start well inside the
        # ledge's inner edge, which is void, in case the outline slopes here.
        ledge = ledge.cut(
            box_between(
                (
                    side * (abs(edge) - p.ledge_mm - 3.0),
                    side * reach,
                ),
                (-slot, slot),
                under_board,
            )
        )

    # The wall stops short of the board's top face: a part resting there may
    # overhang a rounded corner, and the board is held at three quarters of
    # its thickness all the same.
    wall_top = p.board_bottom_z_mm + 0.75 * p.board_thickness_mm
    wall = _prism(points, p.board_bottom_z_mm - 0.01, wall_top, grow).cut(
        _prism(points, p.board_bottom_z_mm - 1, board_top + 1, p.clearance_mm)
    )
    stop = wall.intersect(
        box_between(
            (-reach, reach),
            (ymax - p.stop_band_mm, ymax + grow + 1),
            (p.board_bottom_z_mm - 1, board_top + 1),
        )
    )
    cradle = ledge.union(stop)

    for side, edge in edges.items():
        cradle = cradle.union(
            _clip(p, side=side, half_w=abs(edge), board_top=board_top)
        )

    board = _prism(points, p.board_bottom_z_mm, board_top)
    clash = cast(cq.Shape, cradle.intersect(board).val())

    if not clash.isNull() and clash.Volume() > 0.01:
        raise ValueError(
            "the cradle would overlap the board's outline: its edge is not "
            "straight enough where the clips stand"
        )

    return cradle


def _clip(
    p: BoardCradleParameters, *, side: int, half_w: float, board_top: float
) -> cq.Workplane:
    """One upright clip beside the board edge at ``side * half_w``."""
    inner = half_w + p.clearance_mm
    outer = inner + p.wall_mm
    reach = half_w - (p.clip_overhang_mm - p.clearance_mm)
    lip_bottom = board_top + p.clip_gap_mm
    lip_top = lip_bottom + p.clip_lip_height_mm
    width = (-p.clip_width_mm / 2, p.clip_width_mm / 2)

    stem = box_between((side * inner, side * outer), width, (p.base_z_mm, lip_top))
    lip = box_between((side * reach, side * outer), width, (lip_bottom, lip_top))

    return stem.union(lip)
