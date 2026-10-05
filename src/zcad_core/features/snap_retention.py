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
    # A tab: a beam this long, its underside this far above base_z_mm.
    tab_length_mm: float | None = None
    tab_underside_mm: float = 0.0

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

        if self.tab_length_mm is not None:
            if self.tab_length_mm <= self.width_mm:
                raise ValueError("tab_length_mm must be longer than width_mm")

            lip_above_base = (
                self.base_height_mm + self.compliant_span_mm + self.clearance_mm
            )

            if not 0 < self.tab_underside_mm < lip_above_base:
                raise ValueError(
                    "tab_underside_mm must be above base_z_mm and below the lip"
                )


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

    Without ``tab_length_mm`` the clip is a post ``width_mm`` wide, centred
    on ``(x, y)``, bending up its height. With it, the clip is a tab centred
    there: a post at its -Y end and a beam ``tab_length_mm`` long running
    along the edge from it, its underside ``tab_underside_mm`` above
    ``base_z_mm``, free of everything but the post. The lip is at the beam's
    free end, so the beam bends along the edge.
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
    width = parameters.width_mm
    half_span = (width + (parameters.tab_length_mm or 0.0)) / 2

    stem = cq.Workplane("XY").add(
        cq.Solid.makeBox(
            inner - outer,
            width,
            top - parameters.base_z_mm,
            pnt=cq.Vector(outer, -half_span, parameters.base_z_mm),
        )
    )

    if parameters.tab_length_mm is not None:
        underside = parameters.base_z_mm + parameters.tab_underside_mm
        stem = stem.union(
            cq.Workplane("XY").add(
                cq.Solid.makeBox(
                    inner - outer,
                    parameters.tab_length_mm,
                    top - underside,
                    pnt=cq.Vector(outer, -half_span + width, underside),
                )
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
        .extrude(width / 2, both=True)
        .translate((0.0, half_span - width / 2, 0.0))
    )
    clip = stem.union(lip)

    if parameters.rotation_degrees:
        clip = clip.rotate((0, 0, 0), (0, 0, 1), parameters.rotation_degrees)

    return model.union(clip.translate((parameters.x, parameters.y, 0.0)))
