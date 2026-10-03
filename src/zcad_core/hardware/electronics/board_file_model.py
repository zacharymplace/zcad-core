"""The types and limits of a board file: what a check returns, where a file came from,
and the board it loads into.

Everything here is data; the reading and checking are in
:mod:`zcad_core.hardware.electronics.board_file`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from zcad_core.hardware.electronics.board_components import BoardComponentSpec
from zcad_core.hardware.electronics.board_outline import Point
from zcad_core.hardware.electronics.board_test_points import BoardTestPoint
from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
    WallOpeningSpec,
)
from zcad_core.hardware.thermal import PowerFigure

BOARD_SCHEMA_VERSION = "1.0.0"


EDGES = ("negative_x", "positive_x", "negative_y", "positive_y")


ENVELOPE_IDENTIFIER = "envelope-top"


# Sizes outside these are refused as a likely mistake in units; sizes above the
# warning limit are probably a large board or a unit mistake.
BOARD_SIZE_RANGE_MM = (5.0, 400.0)


BOARD_SIZE_WARNING_MM = 150.0


THICKNESS_RANGE_MM = (0.2, 6.0)


TYPICAL_THICKNESS_RANGE_MM = (0.4, 3.2)


HOLE_DIAMETER_RANGE_MM = (0.8, 8.0)


# A standoff is this much wider than its hole, round it.
STANDOFF_WALL_MM = 3.0


# An envelope stands this far in from the edges of a board held in a cradle.
CRADLE_ENVELOPE_INSET_MM = 1.0


MAXIMUM_ENVELOPE_INSET_MM = 8.0


# A part may stand this far outside a polygon outline (a sliver at a corner).
OUTLINE_TOLERANCE_MM = 0.3


# A part overhanging an edge by more than this is almost certainly a mistake.
MAXIMUM_OVERHANG_MM = 20.0


# A part reaching past an edge by more than this needs an access edge.
OVERHANG_MM = 0.3


_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]+")


_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "identifier",
        "name",
        "units",
        "outline",
        "board",
        "mounting_holes",
        "standoff",
        "cable_connector",
        "envelope",
        "components",
        "wall_openings",
        "power",
        "source",
        "notes",
        "needs_review",
        "verified_by",
        "test_points",
    }
)


@dataclass(frozen=True)
class BoardCheck:
    """What a check found: errors make a board unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class BoardOrigin:
    """Where a board came from, and how to tell it from the one that was built."""

    path: str
    sha256: str


@dataclass(frozen=True)
class BoardFileSpec:
    """A board loaded from a file, satisfying the builder's board protocols."""

    identifier: str
    board_width_mm: float
    board_length_mm: float
    board_thickness_mm: float
    usb_connector: RectangularConnectorSpec
    components: tuple[BoardComponentSpec, ...]
    wall_openings: tuple[WallOpeningSpec, ...]
    mounting_hole_diameter_mm: float | None
    mounting_hole_positions_mm: tuple[tuple[float, float], ...] | None
    mounting_hole_spacing_x_mm: float | None
    mounting_hole_spacing_y_mm: float | None
    recommended_standoff_height_mm: float
    recommended_clearance_mm: float
    name: str
    source: str
    notes: str
    power_figure: PowerFigure | None
    origin: BoardOrigin
    warnings: tuple[str, ...]
    # The PCB's outline about its centre, when it is not a plain rectangle.
    # The cavity still encloses the bounding rectangle; the PCB solid and a
    # snap-in cradle follow the outline.
    outline_points_mm: tuple[Point, ...] | None = None
    # A file's numbers are the user's until a trial has fitted the board; only
    # a board in the catalog's data directory, promoted on its trials, is
    # verified. A ``verified_by`` in a user's own file is a claim, not a check.
    verified: bool = False
    verified_by: str = ""
    # Loaded from the catalog's data directory rather than a user's file.
    catalog: bool = False
    # The pads a test fixture's probes land on; none unless the file lists them.
    test_points: tuple[BoardTestPoint, ...] = ()

    def provenance(self) -> dict[str, Any]:
        """What a build records about where the board came from."""

        record: dict[str, Any] = {
            "kind": "catalog" if self.catalog else "file",
            "identifier": self.identifier,
            "sha256": self.origin.sha256,
            "source": self.source,
            "verified": self.verified,
            "warnings": list(self.warnings),
        }

        if self.catalog:
            record["verified_by"] = self.verified_by
        else:
            record["path"] = self.origin.path

        return record
