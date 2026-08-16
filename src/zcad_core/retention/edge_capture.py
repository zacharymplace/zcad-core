from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from zcad_core.geometry.types import BoardEdge

_MINIMUM_LOCATION_SEPARATION_MM = 1e-6


@dataclass(frozen=True)
class EdgeCapturePolicy:
    """Manufacturing and engagement policy for edge capture."""

    arm_width_mm: float = 6.0
    engagement_depth_mm: float = 2.5
    board_clearance_mm: float = 0.25
    vertical_overlap_mm: float = 0.6
    minimum_wall_mm: float = 1.2

    def __post_init__(self) -> None:
        positive_fields = {
            "arm_width_mm": self.arm_width_mm,
            "engagement_depth_mm": self.engagement_depth_mm,
            "vertical_overlap_mm": self.vertical_overlap_mm,
            "minimum_wall_mm": self.minimum_wall_mm,
        }

        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")

        if self.board_clearance_mm < 0:
            raise ValueError("board_clearance_mm cannot be negative")


@dataclass(frozen=True)
class EdgeCaptureLocation:
    """One verified board-edge capture location, in absolute board coordinates.

    ``position_mm`` is the coordinate along the edge (x for a Y-edge, y for
    an X-edge). ``edge_coordinate_mm`` is the edge's own fixed coordinate -
    the board's boundary value on that side (e.g. ``pcb.BoundingBox().ymin``
    for :attr:`BoardEdge.NEGATIVE_Y`).
    """

    edge: BoardEdge
    position_mm: float
    edge_coordinate_mm: float


@dataclass(frozen=True)
class EdgeCaptureParameters:
    """Derived geometry artifact for one board layout.

    Each location produces a single wall-and-ledge capture feature (see
    :mod:`zcad_core.retention.synthetic_edge_backend`), not the two
    perpendicular walls corner capture builds at a corner. A wall
    hugging the true board edge (via ``board_clearance_mm``) gives a hard
    contact stop against motion toward the wall, and the ledge overhang
    (``engagement_depth_mm`` / ``vertical_overlap_mm``) resists lift-off
    while the board is captured under it. Unlike corner capture's diagonal
    pair - whose two corners face opposite directions in both axes and so
    give true bilateral planar restraint - two edge-capture locations on
    the same straight edge cannot themselves stop the board sliding away
    from the wall (parallel-facing walls can't oppose each other). This
    strategy relies on the same close-tolerance fit already used
    throughout this codebase (``board_clearance_mm``) for that direction,
    the same way real snap-fit clips do; it does not claim corner
    capture's stronger geometric guarantee.
    """

    board_thickness_mm: float
    locations: tuple[EdgeCaptureLocation, ...]
    arm_width_mm: float
    engagement_depth_mm: float
    board_clearance_mm: float
    vertical_overlap_mm: float
    minimum_wall_mm: float

    def __post_init__(self) -> None:
        if self.board_thickness_mm <= 0:
            raise ValueError("board_thickness_mm must be positive")

        if len(self.locations) < 2:
            raise ValueError("Edge capture requires at least two locations")

        seen: set[tuple[BoardEdge, float]] = set()

        for location in self.locations:
            key = (location.edge, location.position_mm)

            if key in seen:
                raise ValueError("Edge capture locations must be unique")

            seen.add(key)

        same_edge_positions: dict[BoardEdge, list[float]] = {}

        for location in self.locations:
            same_edge_positions.setdefault(location.edge, []).append(
                location.position_mm
            )

        for edge, positions in same_edge_positions.items():
            if len(positions) < 2:
                continue

            ordered = sorted(positions)
            gaps = tuple(later - earlier for earlier, later in pairwise(ordered))

            if min(gaps) < _MINIMUM_LOCATION_SEPARATION_MM:
                raise ValueError(
                    f"Edge capture locations on {edge.value} must not overlap"
                )


def as_edge_capture_parameters(
    value: object,
) -> EdgeCaptureParameters:
    """Narrow a generic retention-execution value to edge-capture parameters."""

    if not isinstance(value, EdgeCaptureParameters):
        raise TypeError("Expected EdgeCaptureParameters from the retention execution")

    return value


def derive_edge_capture_parameters(
    *,
    board_thickness_mm: float,
    locations: tuple[EdgeCaptureLocation, ...],
    policy: EdgeCapturePolicy,
) -> EdgeCaptureParameters:
    """Derive a validated edge-capture geometry artifact."""

    return EdgeCaptureParameters(
        board_thickness_mm=board_thickness_mm,
        locations=locations,
        arm_width_mm=policy.arm_width_mm,
        engagement_depth_mm=policy.engagement_depth_mm,
        board_clearance_mm=policy.board_clearance_mm,
        vertical_overlap_mm=policy.vertical_overlap_mm,
        minimum_wall_mm=policy.minimum_wall_mm,
    )
