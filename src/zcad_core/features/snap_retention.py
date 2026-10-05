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
    """Add one upright snap-retention clip to a model.

    ``(x, y)`` is a point on the held part's edge, and the clip faces +X
    (before ``rotation_degrees`` turns it about that point), so the part
    lies at +X. The stem stands ``clearance_mm`` out from the edge, from
    ``base_z_mm`` up, so it joins whatever base holds the part. The part's
    underside is ``base_height_mm`` above ``base_z_mm`` and its top face
    ``compliant_span_mm`` above that. The lip hooks ``overhang_mm`` in over
    the part's top edge, measured from the edge so the clearance never eats
    into it, with a flat underside ``clearance_mm`` above the top face and
    a sloped top that lets the part push the clip aside as it is pressed in.
    """
    parameters.validate()

    clearance = parameters.clearance_mm
    inner = -clearance
    outer = inner - parameters.wall_mm
    lip_bottom = (
        parameters.base_z_mm
        + parameters.base_height_mm
        + parameters.compliant_span_mm
        + clearance
    )
    top = lip_bottom + parameters.height_mm

    stem = cq.Workplane("XY").add(
        cq.Solid.makeBox(
            inner - outer,
            parameters.width_mm,
            top - parameters.base_z_mm,
            pnt=cq.Vector(outer, -parameters.width_mm / 2, parameters.base_z_mm),
        )
    )
    lip = (
        cq.Workplane("XZ")
        .polyline(
            [
                (inner, lip_bottom),
                (parameters.overhang_mm, lip_bottom),
                (inner, top),
            ]
        )
        .close()
        .extrude(parameters.width_mm / 2, both=True)
    )
    clip = stem.union(lip)

    if parameters.rotation_degrees:
        clip = clip.rotate((0, 0, 0), (0, 0, 1), parameters.rotation_degrees)

    return model.union(clip.translate((parameters.x, parameters.y, 0.0)))
