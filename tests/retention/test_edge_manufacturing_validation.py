from __future__ import annotations

from dataclasses import replace

import pytest

from zcad_core.geometry.types import BoardEdge
from zcad_core.retention import (
    EdgeCaptureLocation,
    EdgeCaptureParameters,
    ManufacturingCheck,
    ManufacturingPolicy,
    PrintOrientation,
)
from zcad_core.retention.manufacturing import validate_edge_capture_manufacturing


def valid_parameters() -> EdgeCaptureParameters:
    return EdgeCaptureParameters(
        board_thickness_mm=1.6,
        locations=(
            EdgeCaptureLocation(
                edge=BoardEdge.NEGATIVE_Y,
                position_mm=4.0,
                edge_coordinate_mm=0.0,
            ),
            EdgeCaptureLocation(
                edge=BoardEdge.NEGATIVE_Y,
                position_mm=36.0,
                edge_coordinate_mm=0.0,
            ),
        ),
        arm_width_mm=5.0,
        engagement_depth_mm=2.5,
        board_clearance_mm=0.25,
        vertical_overlap_mm=0.6,
        minimum_wall_mm=1.2,
    )


def test_valid_parameters_pass_all_checks() -> None:
    report = validate_edge_capture_manufacturing(
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

    report = validate_edge_capture_manufacturing(
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

    report = validate_edge_capture_manufacturing(
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

    report = validate_edge_capture_manufacturing(
        parameters,
        policy=ManufacturingPolicy(),
    )

    assert report.passed is False
    assert ManufacturingCheck.OVERHANG in {result.check for result in report.failures}


def test_capture_spacing_is_measured_across_absolute_coordinates() -> None:
    report = validate_edge_capture_manufacturing(
        valid_parameters(),
        policy=ManufacturingPolicy(),
    )

    spacing_result = next(
        result
        for result in report.results
        if result.check is ManufacturingCheck.CAPTURE_SPACING
    )

    assert spacing_result.measured_value == pytest.approx(32.0)


def test_close_locations_fail_spacing_check() -> None:
    parameters = replace(
        valid_parameters(),
        locations=(
            EdgeCaptureLocation(
                edge=BoardEdge.NEGATIVE_Y,
                position_mm=4.0,
                edge_coordinate_mm=0.0,
            ),
            EdgeCaptureLocation(
                edge=BoardEdge.NEGATIVE_Y,
                position_mm=9.0,
                edge_coordinate_mm=0.0,
            ),
        ),
    )

    report = validate_edge_capture_manufacturing(
        parameters,
        policy=ManufacturingPolicy(),
    )

    assert report.passed is False
    assert ManufacturingCheck.CAPTURE_SPACING in {
        result.check for result in report.failures
    }


def test_spacing_uses_absolute_geometry_across_different_edges() -> None:
    """Locations on perpendicular edges must be measured as real 2D distance."""

    parameters = replace(
        valid_parameters(),
        locations=(
            EdgeCaptureLocation(
                edge=BoardEdge.NEGATIVE_Y,
                position_mm=0.0,
                edge_coordinate_mm=0.0,
            ),
            EdgeCaptureLocation(
                edge=BoardEdge.POSITIVE_X,
                position_mm=0.0,
                edge_coordinate_mm=40.0,
            ),
        ),
    )

    report = validate_edge_capture_manufacturing(
        parameters,
        policy=ManufacturingPolicy(),
    )

    spacing_result = next(
        result
        for result in report.results
        if result.check is ManufacturingCheck.CAPTURE_SPACING
    )

    assert spacing_result.measured_value == pytest.approx((40.0**2 + 0.0**2) ** 0.5)


def test_incomplete_report_cannot_pass() -> None:
    report = validate_edge_capture_manufacturing(
        valid_parameters(),
        policy=ManufacturingPolicy(),
    )

    incomplete = type(report)(results=report.results[:-1])

    assert incomplete.passed is False


def test_default_orientation_is_base_down() -> None:
    policy = ManufacturingPolicy()

    assert policy.print_orientation is PrintOrientation.BASE_DOWN
