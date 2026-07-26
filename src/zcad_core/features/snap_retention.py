"""Reusable printed snap-retention clip geometry."""

from dataclasses import dataclass

import cadquery as cq


@dataclass(frozen=True)
class SnapRetentionClipParameters:
    """Geometry parameters for one printed snap-retention clip."""

    x: float
    y: float

    base_height_mm: float
    compliant_span_mm: float
    board_thickness_mm: float

    width_mm: float
    wall_mm: float
    height_mm: float
    overhang_mm: float
    clearance_mm: float

    base_z_mm: float = 0.0
    rotation_degrees: float = 0.0

    def validate(self) -> None:
        """Validate snap-retention clip geometry."""
        positive_values = {
            "base_height_mm": self.base_height_mm,
            "compliant_span_mm": self.compliant_span_mm,
            "board_thickness_mm": self.board_thickness_mm,
            "width_mm": self.width_mm,
            "wall_mm": self.wall_mm,
            "height_mm": self.height_mm,
            "overhang_mm": self.overhang_mm,
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.clearance_mm < 0:
            raise ValueError("clearance_mm must not be negative")

        if self.overhang_mm >= self.compliant_span_mm:
            raise ValueError("overhang_mm must be less than compliant_span_mm")


def add_snap_retention_clip(
    model: cq.Workplane,
    *,
    parameters: SnapRetentionClipParameters,
) -> cq.Workplane:
    """Add one upright snap-retention clip to a model."""
    parameters.validate()

    stem_height_mm = parameters.compliant_span_mm + parameters.height_mm

    stem = (
        cq.Workplane("XY")
        .box(
            parameters.wall_mm,
            parameters.width_mm,
            stem_height_mm,
            centered=(False, True, False),
        )
        .translate(
            (
                parameters.x,
                parameters.y,
                (parameters.base_z_mm + parameters.base_height_mm),
            )
        )
    )

    lip_bottom_z_mm = (
        parameters.base_z_mm
        + parameters.base_height_mm
        + parameters.compliant_span_mm
        - parameters.clearance_mm
    )

    lip = (
        cq.Workplane("XY")
        .box(
            parameters.wall_mm + parameters.overhang_mm,
            parameters.width_mm,
            parameters.height_mm,
            centered=(False, True, False),
        )
        .translate(
            (
                parameters.x,
                parameters.y,
                lip_bottom_z_mm,
            )
        )
    )

    clip = stem.union(lip)

    if parameters.rotation_degrees:
        clip = clip.rotate(
            (
                parameters.x,
                parameters.y,
                0.0,
            ),
            (
                parameters.x,
                parameters.y,
                1.0,
            ),
            parameters.rotation_degrees,
        )

    return model.union(clip)
