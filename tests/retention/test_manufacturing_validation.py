from __future__ import annotations

from dataclasses import replace

import pytest

from zcad_core.retention import (
    BoardCorner,
    CornerCaptureLocation,
    CornerCaptureParameters,
    ManufacturingCheck,
    ManufacturingPolicy,
    PrintOrientation,
    validate_corner_capture_manufacturing,
)


def valid_parameters() -> CornerCaptureParameters:
    return CornerCaptureParameters(
        board_thickness_mm=1.6,
        locations=(
            CornerCaptureLocation(
                BoardCorner.NEGATIVE_X_NEGATIVE_Y,
                -20.0,
                -15.0,
            ),
            CornerCaptureLocation(
                BoardCorner.POSITIVE_X_POSITIVE_Y,
                20.0,
                15.0,
            ),
        ),
        arm_width_mm=3.0,
        engagement_depth_mm=2.0,
        board_clearance_mm=0.25,
        vertical_overlap_mm=0.6,
        minimum_wall_mm=1.2,
    )


def test_default_policy_is_valid() -> None:
    policy = ManufacturingPolicy()

    assert policy.minimum_wall_mm == pytest.approx(1.2)
    assert policy.print_orientation is (PrintOrientation.BASE_DOWN)


@pytest.mark.parametrize(
    "field",
    (
        "minimum_wall_mm",
        "minimum_board_clearance_mm",
        "minimum_vertical_overlap_mm",
        "minimum_capture_spacing_mm",
        "maximum_unsupported_overhang_mm",
    ),
)
def test_policy_dimensions_must_be_positive(
    field: str,
) -> None:
    values = {
        "minimum_wall_mm": 1.2,
        "minimum_board_clearance_mm": 0.2,
        "minimum_vertical_overlap_mm": 0.4,
        "minimum_capture_spacing_mm": 10.0,
        "maximum_unsupported_overhang_mm": 3.0,
    }
    values[field] = 0.0

    with pytest.raises(
        ValueError,
        match=field,
    ):
        ManufacturingPolicy(**values)


def test_valid_parameters_pass_all_checks() -> None:
    report = validate_corner_capture_manufacturing(
        valid_parameters(),
        policy=ManufacturingPolicy(),
    )

    assert report.passed is True
    assert report.failures == ()
    assert {result.check for result in report.results} == set(ManufacturingCheck)


def test_low_wall_fails_closed() -> None:
    parameters = replace(
        valid_parameters(),
        minimum_wall_mm=0.8,
    )

    report = validate_corner_capture_manufacturing(
        parameters,
        policy=ManufacturingPolicy(),
    )

    assert report.passed is False
    assert ManufacturingCheck.MINIMUM_WALL in {
        result.check for result in report.failures
    }


def test_low_clearance_fails_closed() -> None:
    parameters = replace(
        valid_parameters(),
        board_clearance_mm=0.1,
    )

    report = validate_corner_capture_manufacturing(
        parameters,
        policy=ManufacturingPolicy(),
    )

    assert report.passed is False
    assert ManufacturingCheck.BOARD_CLEARANCE in {
        result.check for result in report.failures
    }


def test_excessive_overhang_fails_closed() -> None:
    parameters = replace(
        valid_parameters(),
        vertical_overlap_mm=3.5,
    )

    report = validate_corner_capture_manufacturing(
        parameters,
        policy=ManufacturingPolicy(),
    )

    assert report.passed is False
    assert ManufacturingCheck.OVERHANG in {result.check for result in report.failures}


def test_capture_spacing_is_measured() -> None:
    report = validate_corner_capture_manufacturing(
        valid_parameters(),
        policy=ManufacturingPolicy(),
    )

    spacing_result = next(
        result
        for result in report.results
        if result.check is ManufacturingCheck.CAPTURE_SPACING
    )

    assert spacing_result.measured_value == pytest.approx(50.0)


def test_incomplete_report_cannot_pass() -> None:
    report = validate_corner_capture_manufacturing(
        valid_parameters(),
        policy=ManufacturingPolicy(),
    )

    incomplete = type(report)(results=report.results[:-1])

    assert incomplete.passed is False
