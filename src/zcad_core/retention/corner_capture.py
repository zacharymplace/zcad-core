from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BoardCorner(str, Enum):
    """Axis-aligned corner of a board envelope."""

    NEGATIVE_X_NEGATIVE_Y = "negative_x_negative_y"
    NEGATIVE_X_POSITIVE_Y = "negative_x_positive_y"
    POSITIVE_X_NEGATIVE_Y = "positive_x_negative_y"
    POSITIVE_X_POSITIVE_Y = "positive_x_positive_y"


@dataclass(frozen=True)
class CornerCapturePolicy:
    """Manufacturing and engagement policy for corner capture."""

    arm_width_mm: float = 3.0
    engagement_depth_mm: float = 2.0
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
class CornerCaptureLocation:
    """One verified board-corner capture location."""

    corner: BoardCorner
    x_mm: float
    y_mm: float
    local_radius_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.local_radius_mm < 0:
            raise ValueError("local_radius_mm cannot be negative")


@dataclass(frozen=True)
class CornerCaptureParameters:
    """Derived geometry artifact for one board layout."""

    board_thickness_mm: float
    locations: tuple[CornerCaptureLocation, ...]
    arm_width_mm: float
    engagement_depth_mm: float
    board_clearance_mm: float
    vertical_overlap_mm: float
    minimum_wall_mm: float

    def __post_init__(self) -> None:
        if self.board_thickness_mm <= 0:
            raise ValueError("board_thickness_mm must be positive")

        if len(self.locations) < 2:
            raise ValueError("Corner capture requires at least two locations")

        corners = tuple(location.corner for location in self.locations)

        if len(set(corners)) != len(corners):
            raise ValueError("Corner capture locations must be unique")

        if not _resists_translation_in_both_axes(set(corners)):
            raise ValueError(
                "Corner layout must resist translation in both board-plane axes"
            )


def as_corner_capture_parameters(
    value: object,
) -> CornerCaptureParameters:
    """Narrow a generic retention-execution value to corner-capture parameters."""

    if not isinstance(value, CornerCaptureParameters):
        raise TypeError("Expected CornerCaptureParameters from the retention execution")

    return value


def derive_corner_capture_parameters(
    *,
    board_thickness_mm: float,
    locations: tuple[CornerCaptureLocation, ...],
    policy: CornerCapturePolicy,
) -> CornerCaptureParameters:
    """Derive a validated corner-capture geometry artifact."""

    return CornerCaptureParameters(
        board_thickness_mm=board_thickness_mm,
        locations=locations,
        arm_width_mm=policy.arm_width_mm,
        engagement_depth_mm=(policy.engagement_depth_mm),
        board_clearance_mm=policy.board_clearance_mm,
        vertical_overlap_mm=policy.vertical_overlap_mm,
        minimum_wall_mm=policy.minimum_wall_mm,
    )


def _resists_translation_in_both_axes(
    corners: set[BoardCorner],
) -> bool:
    has_negative_x = any(
        corner
        in {
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
        }
        for corner in corners
    )
    has_positive_x = any(
        corner
        in {
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
            BoardCorner.POSITIVE_X_POSITIVE_Y,
        }
        for corner in corners
    )
    has_negative_y = any(
        corner
        in {
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
        }
        for corner in corners
    )
    has_positive_y = any(
        corner
        in {
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
            BoardCorner.POSITIVE_X_POSITIVE_Y,
        }
        for corner in corners
    )

    return has_negative_x and has_positive_x and has_negative_y and has_positive_y
