from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.retention import (
    BoardCorner,
    CornerCaptureBackend,
    CornerCaptureFitCheck,
    CornerCaptureLocation,
    CornerCaptureParameters,
    CornerCapturePolicy,
    CornerCaptureRequest,
    SyntheticCornerCaptureBackend,
)


def opposite_locations() -> tuple[CornerCaptureLocation, ...]:
    return (
        CornerCaptureLocation(
            corner=(BoardCorner.NEGATIVE_X_NEGATIVE_Y),
            x_mm=-20.0,
            y_mm=-15.0,
        ),
        CornerCaptureLocation(
            corner=(BoardCorner.POSITIVE_X_POSITIVE_Y),
            x_mm=20.0,
            y_mm=15.0,
        ),
    )


def all_corner_locations() -> tuple[CornerCaptureLocation, ...]:
    return (
        CornerCaptureLocation(
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            -20.0,
            -15.0,
        ),
        CornerCaptureLocation(
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
            -20.0,
            15.0,
        ),
        CornerCaptureLocation(
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
            20.0,
            -15.0,
        ),
        CornerCaptureLocation(
            BoardCorner.POSITIVE_X_POSITIVE_Y,
            20.0,
            15.0,
        ),
    )


def valid_request() -> CornerCaptureRequest:
    return CornerCaptureRequest(
        board_thickness_mm=1.6,
        locations=opposite_locations(),
        policy=CornerCapturePolicy(),
    )


def test_backend_satisfies_protocol() -> None:
    backend = SyntheticCornerCaptureBackend()

    assert isinstance(
        backend,
        CornerCaptureBackend,
    )


def test_derive_reuses_validated_parameters() -> None:
    backend = SyntheticCornerCaptureBackend()

    parameters = backend.derive(valid_request())

    assert parameters.board_thickness_mm == pytest.approx(1.6)
    assert parameters.locations == opposite_locations()
    assert parameters.arm_width_mm == pytest.approx(3.0)


def test_apply_requires_cadquery_workplane() -> None:
    backend = SyntheticCornerCaptureBackend()
    parameters = backend.derive(valid_request())

    with pytest.raises(
        TypeError,
        match="cadquery.Workplane",
    ):
        backend.apply(
            object(),
            parameters,
        )


def test_apply_adds_corner_capture_geometry() -> None:
    backend = SyntheticCornerCaptureBackend()
    parameters = backend.derive(valid_request())

    base = (
        cq.Workplane("XY")
        .box(
            50.0,
            40.0,
            2.0,
        )
        .translate(
            (
                0.0,
                0.0,
                -1.0,
            )
        )
    )

    base_volume = base.val().Volume()

    result = backend.apply(
        base,
        parameters,
    )

    assert isinstance(
        result,
        cq.Workplane,
    )
    assert result.val().Volume() > base_volume


def test_apply_is_deterministic() -> None:
    backend = SyntheticCornerCaptureBackend()
    parameters = backend.derive(valid_request())
    base = cq.Workplane("XY").box(
        50.0,
        40.0,
        2.0,
    )

    first = backend.apply(
        base,
        parameters,
    )
    second = backend.apply(
        base,
        parameters,
    )

    assert first.val().Volume() == pytest.approx(second.val().Volume())
    assert first.val().BoundingBox().xlen == pytest.approx(
        second.val().BoundingBox().xlen
    )
    assert first.val().BoundingBox().ylen == pytest.approx(
        second.val().BoundingBox().ylen
    )
    assert first.val().BoundingBox().zlen == pytest.approx(
        second.val().BoundingBox().zlen
    )


def test_default_synthetic_fit_report_passes() -> None:
    backend = SyntheticCornerCaptureBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    assert report.passed is True
    assert report.failures == ()
    assert {result.check for result in report.results} == set(CornerCaptureFitCheck)


def test_component_clearance_detail_is_explicitly_synthetic() -> None:
    backend = SyntheticCornerCaptureBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    component_result = next(
        result
        for result in report.results
        if result.check is CornerCaptureFitCheck.COMPONENT_CLEARANCE
    )

    assert component_result.passed is True
    assert "production clearance remains unverified" in (component_result.detail)


def test_all_four_corners_fail_installation_path() -> None:
    backend = SyntheticCornerCaptureBackend()
    parameters = CornerCaptureParameters(
        board_thickness_mm=1.6,
        locations=all_corner_locations(),
        arm_width_mm=3.0,
        engagement_depth_mm=2.0,
        board_clearance_mm=0.25,
        vertical_overlap_mm=0.6,
        minimum_wall_mm=1.2,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False

    assert {result.check for result in report.failures} == {
        CornerCaptureFitCheck.INSTALLATION_PATH
    }


def test_manufacturing_gate_fails_closed() -> None:
    backend = SyntheticCornerCaptureBackend()
    parameters = CornerCaptureParameters(
        board_thickness_mm=1.6,
        locations=opposite_locations(),
        arm_width_mm=0.15,
        engagement_depth_mm=2.0,
        board_clearance_mm=0.10,
        vertical_overlap_mm=0.6,
        minimum_wall_mm=0.50,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False

    assert CornerCaptureFitCheck.MANUFACTURING_CLEARANCE in {
        result.check for result in report.failures
    }


@pytest.mark.parametrize(
    (
        "corner",
        "expected",
    ),
    (
        (
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            (-1, -1),
        ),
        (
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
            (-1, 1),
        ),
        (
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
            (1, -1),
        ),
        (
            BoardCorner.POSITIVE_X_POSITIVE_Y,
            (1, 1),
        ),
    ),
)
def test_corner_sign_mapping(
    corner: BoardCorner,
    expected: tuple[int, int],
) -> None:
    backend = SyntheticCornerCaptureBackend()

    assert backend._corner_signs(corner) == expected
