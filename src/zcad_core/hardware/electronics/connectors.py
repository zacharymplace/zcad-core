"""Reusable electronics connector specifications."""

from dataclasses import dataclass
from typing import Literal

BoardEdge = Literal[
    "negative_x",
    "positive_x",
    "negative_y",
    "positive_y",
]


@dataclass(frozen=True)
class RectangularConnectorSpec:
    """Mechanical placement metadata for a rectangular connector."""

    identifier: str
    width_mm: float
    height_mm: float
    depth_mm: float
    board_edge: BoardEdge
    center_offset_mm: float = 0.0
    bottom_offset_from_board_top_mm: float = 0.0

    def validate(self) -> None:
        """Validate connector dimensions and placement."""
        if not self.identifier.strip():
            raise ValueError("identifier must not be empty")

        if self.width_mm <= 0:
            raise ValueError("width_mm must be greater than zero")

        if self.height_mm <= 0:
            raise ValueError("height_mm must be greater than zero")

        if self.depth_mm <= 0:
            raise ValueError("depth_mm must be greater than zero")
