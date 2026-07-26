from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BoardEdge(str, Enum):
    """Axis-aligned side of a board bounding envelope."""

    NEGATIVE_X = "negative_x"
    POSITIVE_X = "positive_x"
    NEGATIVE_Y = "negative_y"
    POSITIVE_Y = "positive_y"


@dataclass(frozen=True)
class EdgeSegment:
    """One coordinate interval along a board edge."""

    edge: BoardEdge
    start_mm: float
    end_mm: float

    def __post_init__(self) -> None:
        if self.end_mm <= self.start_mm:
            raise ValueError("end_mm must be greater than start_mm")

    @property
    def length_mm(self) -> float:
        return self.end_mm - self.start_mm

    @property
    def center_mm(self) -> float:
        return (self.start_mm + self.end_mm) / 2.0


@dataclass(frozen=True)
class EdgeValidationResult:
    """Geometric evidence for a proposed edge segment."""

    segment: EdgeSegment
    engagement_depth_mm: float
    sample_resolution_mm: float
    sample_count: int
    passing_sample_count: int
    minimum_material_ratio: float
    continuous: bool
    usable: bool
    blocked_spans: tuple[EdgeSegment, ...]
    reason: str | None
