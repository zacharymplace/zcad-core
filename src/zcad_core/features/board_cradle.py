"""A snap-in cradle for boards without mounting holes.

The board rests on a ledge under its edges, a snap clip on each side edge
hooks over its top, and a stop behind the edge opposite its connector keeps
a cable push from shoving it back. The connector edge stays open.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.geometry.boxes import box_between
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
