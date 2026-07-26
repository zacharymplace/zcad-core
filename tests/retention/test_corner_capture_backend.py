from __future__ import annotations

from dataclasses import replace

import pytest

from zcad_core.retention.backend import (
    CornerCaptureBackend,
    CornerCaptureFitCheck,
    CornerCaptureFitReport,
    CornerCaptureFitResult,
    CornerCaptureRequest,
)
from zcad_core.retention.corner_capture import (
    BoardCorner,
    CornerCaptureLocation,
    CornerCaptureParameters,
    CornerCapturePolicy,
    derive_corner_capture_parameters,
)


def valid_locations() -> tuple[CornerCaptureLocation, ...]:
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


def passing_results() -> tuple[CornerCaptureFitResult, ...]:
    return tuple(
        CornerCaptureFitResult(
            check=check,
            passed=True,
            detail=f"{check.value} passed",
        )
        for check in CornerCaptureFitCheck
    )


class FakeCornerCaptureBackend:
    def derive(
        self,
        request: CornerCaptureRequest,
    ) -> CornerCaptureParameters:
        return derive_corner_capture_parameters(
            board_thickness_mm=(request.board_thickness_mm),
            locations=request.locations,
            policy=request.policy,
        )

    def apply(
        self,
        model: object,
        parameters: CornerCaptureParameters,
    ) -> object:
        return {
            "source": model,
            "parameters": parameters,
        }

    def analyze_fit(
        self,
        parameters: CornerCaptureParameters,
    ) -> CornerCaptureFitReport:
        del parameters

        return CornerCaptureFitReport(results=passing_results())


class IncompleteBackend:
    def derive(
        self,
        request: CornerCaptureRequest,
    ) -> CornerCaptureParameters:
        return derive_corner_capture_parameters(
            board_thickness_mm=(request.board_thickness_mm),
            locations=request.locations,
            policy=request.policy,
        )


def test_request_requires_positive_board_thickness() -> None:
    with pytest.raises(
        ValueError,
        match="board_thickness_mm",
    ):
        CornerCaptureRequest(
            board_thickness_mm=0.0,
            locations=valid_locations(),
            policy=CornerCapturePolicy(),
        )


def test_request_requires_two_locations() -> None:
    with pytest.raises(
        ValueError,
        match="at least two",
    ):
        CornerCaptureRequest(
            board_thickness_mm=1.6,
            locations=(valid_locations()[0],),
            policy=CornerCapturePolicy(),
        )


def test_fit_result_requires_detail() -> None:
    with pytest.raises(
        ValueError,
        match="detail",
    ):
        CornerCaptureFitResult(
            check=(CornerCaptureFitCheck.PLANAR_RESTRAINT),
            passed=True,
            detail=" ",
        )


def test_complete_passing_report_passes() -> None:
    report = CornerCaptureFitReport(results=passing_results())

    assert report.passed is True
    assert report.failures == ()


def test_incomplete_report_fails_closed() -> None:
    report = CornerCaptureFitReport(results=passing_results()[:-1])

    assert report.passed is False


def test_failed_check_fails_report() -> None:
    results = list(passing_results())
    results[2] = replace(
        results[2],
        passed=False,
        detail="Component interference detected",
    )

    report = CornerCaptureFitReport(results=tuple(results))

    assert report.passed is False
    assert report.failures == (results[2],)


def test_duplicate_checks_are_rejected() -> None:
    result = CornerCaptureFitResult(
        check=(CornerCaptureFitCheck.PLANAR_RESTRAINT),
        passed=True,
        detail="Planar restraint passed",
    )

    with pytest.raises(
        ValueError,
        match="duplicate",
    ):
        CornerCaptureFitReport(results=(result, result))


def test_fake_backend_satisfies_protocol() -> None:
    backend = FakeCornerCaptureBackend()

    assert isinstance(
        backend,
        CornerCaptureBackend,
    )


def test_incomplete_backend_fails_protocol() -> None:
    backend = IncompleteBackend()

    assert not isinstance(
        backend,
        CornerCaptureBackend,
    )


def test_backend_lifecycle_is_deterministic() -> None:
    backend = FakeCornerCaptureBackend()
    request = CornerCaptureRequest(
        board_thickness_mm=1.6,
        locations=valid_locations(),
        policy=CornerCapturePolicy(),
    )

    parameters = backend.derive(request)
    applied = backend.apply(
        "synthetic-model",
        parameters,
    )
    report = backend.analyze_fit(parameters)

    assert parameters.board_thickness_mm == pytest.approx(1.6)
    assert applied == {
        "source": "synthetic-model",
        "parameters": parameters,
    }
    assert report.passed is True
