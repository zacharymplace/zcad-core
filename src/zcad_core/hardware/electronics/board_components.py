"""The parts on a board, as boxes an enclosure must clear.

A catalogued board's components are extracted from its vendor STEP model by
``scripts/extract-board-components.py`` into
``hardware/data/board-components/<target>.json``. Each is a box in the
board's own frame: centred on the board, its width along X and length along
Y, heights measured from the board's top face. A box lies wholly above the
board or wholly below it, never through it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import cast

from zcad_core.hardware.electronics.connectors import BoardEdge

_EDGES = ("negative_x", "positive_x", "negative_y", "positive_y")


@dataclass(frozen=True)
class BoardComponentSpec:
    """One part on a board, and the edge it is reached through, if any."""

    identifier: str
    center_x_mm: float
    center_y_mm: float
    width_mm: float
    depth_mm: float
    bottom_offset_from_board_top_mm: float
    height_mm: float
    # A part that overhangs this edge, such as a barrel jack, needs an
    # opening in the enclosure wall there.
    access_edge: BoardEdge | None = None

    def validate(self) -> None:
        if not self.identifier.strip():
            raise ValueError("identifier must not be empty")

        for name in ("width_mm", "depth_mm", "height_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.access_edge is not None and self.access_edge not in _EDGES:
            raise ValueError(f"unsupported access edge: {self.access_edge}")

    def validate_against_board(self, board_thickness_mm: float) -> None:
        """Refuse a box that passes through the board itself."""
        self.validate()
        top = self.bottom_offset_from_board_top_mm + self.height_mm

        if self.bottom_offset_from_board_top_mm < 0 and top > -board_thickness_mm:
            raise ValueError(
                f"component {self.identifier} must lie wholly above or below the board"
            )


def load_board_components(target: str) -> tuple[BoardComponentSpec, ...]:
    """The extracted components of one catalogued board."""

    data = (
        resources.files("zcad_core.hardware")
        .joinpath("data", "board-components", f"{target}.json")
        .read_text(encoding="utf-8")
    )

    return tuple(
        BoardComponentSpec(
            identifier=str(row["identifier"]),
            center_x_mm=float(row["center_x_mm"]),
            center_y_mm=float(row["center_y_mm"]),
            width_mm=float(row["width_mm"]),
            depth_mm=float(row["depth_mm"]),
            bottom_offset_from_board_top_mm=float(
                row["bottom_offset_from_board_top_mm"]
            ),
            height_mm=float(row["height_mm"]),
            access_edge=cast(BoardEdge | None, row["access_edge"]),
        )
        for row in json.loads(data)["components"]
    )
