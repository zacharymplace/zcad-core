"""Tests for reusable snap-retention clip geometry."""

import cadquery as cq
import pytest

from zcad_core.features import (
    SnapRetentionClipParameters,
    add_snap_retention_clip,
)


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

    assert result.val().isValid()
    assert result.val().Volume() > base.val().Volume()


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

    assert result.val().isValid()
    assert result.val().Volume() > base.val().Volume()
