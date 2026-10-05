"""Tests for reusable snap-retention clip geometry."""

import cadquery as cq
import pytest

from zcad_core.features import (
    SnapRetentionClipParameters,
    add_snap_retention_clip,
)
from zcad_core.geometry.cadquery_support import workplane_shape


def _parameters(
    **overrides: float,
) -> SnapRetentionClipParameters:
    values = {
        "x": 4.0,
        "y": -3.0,
        "base_height_mm": 3.0,
        "compliant_span_mm": 7.85,
        "board_thickness_mm": 1.6,
        "width_mm": 6.0,
        "wall_mm": 1.2,
        "height_mm": 4.0,
        "overhang_mm": 0.6,
        "clearance_mm": 0.25,
        "base_z_mm": -9.0,
        "rotation_degrees": 0.0,
    }
    values.update(overrides)

    return SnapRetentionClipParameters(**values)


def test_snap_retention_parameters_validate() -> None:
    _parameters().validate()


@pytest.mark.parametrize(
    "field",
    [
        "base_height_mm",
        "compliant_span_mm",
        "board_thickness_mm",
        "width_mm",
        "wall_mm",
        "height_mm",
        "overhang_mm",
    ],
)
def test_snap_retention_rejects_nonpositive_dimensions(
    field: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=f"{field} must be greater than zero",
    ):
        _parameters(**{field: 0.0}).validate()


def test_snap_retention_rejects_negative_clearance() -> None:
    with pytest.raises(
        ValueError,
        match="clearance_mm must not be negative",
    ):
        _parameters(clearance_mm=-0.01).validate()


def test_snap_retention_rejects_excessive_overhang() -> None:
    with pytest.raises(
        ValueError,
        match="overhang_mm must be less than",
    ):
        _parameters(overhang_mm=8.0).validate()


def test_snap_retention_clip_adds_geometry() -> None:
    base = (
        cq.Workplane("XY")
        .box(
            30.0,
            30.0,
            3.0,
            centered=(True, True, False),
        )
        .translate((0.0, 0.0, -9.0))
    )

    result = add_snap_retention_clip(
        base,
        parameters=_parameters(),
    )

    assert workplane_shape(result).isValid()
    assert workplane_shape(result).Volume() > workplane_shape(base).Volume()


def test_snap_retention_clip_supports_rotation() -> None:
    base = (
        cq.Workplane("XY")
        .box(
            30.0,
            30.0,
            3.0,
            centered=(True, True, False),
        )
        .translate((0.0, 0.0, -9.0))
    )

    result = add_snap_retention_clip(
        base,
        parameters=_parameters(
            rotation_degrees=90.0,
        ),
    )

    assert workplane_shape(result).isValid()
    assert workplane_shape(result).Volume() > workplane_shape(base).Volume()


def test_the_clip_stands_outside_the_edge_and_hooks_over_the_top() -> None:
    # The part's edge is at x = 4 and the part lies at +X; its underside is
    # base_height above base_z (-6), its top face compliant_span above that.
    parameters = _parameters()
    clip = workplane_shape(
        add_snap_retention_clip(cq.Workplane("XY"), parameters=parameters)
    )
    box = clip.BoundingBox()
    part_top = -9.0 + 3.0 + 7.85
    part = cq.Solid.makeBox(20.0, 20.0, part_top + 9.0, pnt=cq.Vector(4.0, -13.0, -9.0))

    assert box.xmin == pytest.approx(4.0 - 0.25 - 1.2)
    assert box.xmax == pytest.approx(4.0 + 0.6)
    assert box.zmin == pytest.approx(-9.0)
    assert box.zmax == pytest.approx(part_top + 0.25 + 4.0)
    assert clip.intersect(part).Volume() == pytest.approx(0.0, abs=1e-9)
    # The lip's flat underside, the clearance above the part's top face.
    over = cq.Solid.makeBox(0.6, 6.0, 4.0 + 0.25, pnt=cq.Vector(4.0, -6.0, part_top))
    assert clip.intersect(over).BoundingBox().zmin == pytest.approx(part_top + 0.25)
