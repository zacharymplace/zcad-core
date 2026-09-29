from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention import (
    SnapShellBackend,
    SnapShellFitCheck,
    SnapShellLocation,
    SnapShellParameters,
    SnapShellPolicy,
    SnapShellRequest,
    SyntheticSnapShellBackend,
)


def spaced_locations() -> tuple[SnapShellLocation, ...]:
    return (
        SnapShellLocation(label="north", x_mm=0.0, y_mm=12.0, rotation_degrees=180.0),
        SnapShellLocation(label="south", x_mm=0.0, y_mm=-12.0, rotation_degrees=0.0),
        SnapShellLocation(label="east", x_mm=13.0, y_mm=0.0, rotation_degrees=270.0),
    )


def valid_request() -> SnapShellRequest:
    return SnapShellRequest(
        device_thickness_mm=4.7,
        locations=spaced_locations(),
        policy=SnapShellPolicy(),
    )


def test_backend_satisfies_protocol() -> None:
    backend = SyntheticSnapShellBackend()

    assert isinstance(
        backend,
        SnapShellBackend,
    )


def test_derive_reuses_validated_parameters() -> None:
    backend = SyntheticSnapShellBackend()

    parameters = backend.derive(valid_request())

    assert parameters.device_thickness_mm == pytest.approx(4.7)
    assert parameters.locations == spaced_locations()
    assert parameters.clip_width_mm == pytest.approx(3.0)


def test_apply_requires_cadquery_workplane() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    with pytest.raises(
        TypeError,
        match="cadquery.Workplane",
    ):
        backend.apply(
            object(),
            parameters,
        )


def test_apply_adds_snap_shell_geometry() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    base = cq.Workplane("XY").box(27.4, 24.1, 4.7).translate((0.0, 0.0, 2.35))

    base_volume = workplane_shape(base).Volume()

    result = backend.apply(
        base,
        parameters,
    )

    assert isinstance(
        result,
        cq.Workplane,
    )
    assert workplane_shape(result).Volume() > base_volume


def test_apply_is_deterministic() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())
    base = cq.Workplane("XY").box(27.4, 24.1, 4.7)

    first = backend.apply(
        base,
        parameters,
    )
    second = backend.apply(
        base,
        parameters,
    )

    assert workplane_shape(first).Volume() == pytest.approx(
        workplane_shape(second).Volume()
    )


def test_default_synthetic_fit_report_passes() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    assert report.passed is True
    assert report.failures == ()
    assert {result.check for result in report.results} == set(SnapShellFitCheck)


def test_device_clearance_detail_is_explicitly_synthetic() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    device_result = next(
        result
        for result in report.results
        if result.check is SnapShellFitCheck.DEVICE_CLEARANCE
    )

    assert device_result.passed is True
    assert "production clearance remains unverified" in (device_result.detail)


def test_shell_material_continuity_detail_is_explicitly_synthetic() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    material_result = next(
        result
        for result in report.results
        if result.check is SnapShellFitCheck.SHELL_MATERIAL_CONTINUITY
    )

    assert material_result.passed is True
    assert "production evidence is required" in (material_result.detail)


def test_anchor_separation_fails_when_locations_are_collinear() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = SnapShellParameters(
        device_thickness_mm=4.7,
        locations=(
            SnapShellLocation(label="a", x_mm=0.0, y_mm=0.0),
            SnapShellLocation(label="b", x_mm=5.0, y_mm=0.0),
            SnapShellLocation(label="c", x_mm=10.0, y_mm=0.0),
        ),
        clip_width_mm=3.0,
        wall_mm=1.0,
        clip_height_mm=1.5,
        overhang_mm=0.6,
        clearance_mm=0.15,
        compliant_span_mm=2.0,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert SnapShellFitCheck.ANCHOR_SEPARATION in {
        result.check for result in report.failures
    }


def test_anchor_separation_fails_when_locations_are_too_close() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = SnapShellParameters(
        device_thickness_mm=4.7,
        locations=(
            SnapShellLocation(label="a", x_mm=0.0, y_mm=0.0),
            SnapShellLocation(label="b", x_mm=1.0, y_mm=0.0),
            SnapShellLocation(label="c", x_mm=0.0, y_mm=1.0),
        ),
        clip_width_mm=3.0,
        wall_mm=1.0,
        clip_height_mm=1.5,
        overhang_mm=0.6,
        clearance_mm=0.15,
        compliant_span_mm=2.0,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert SnapShellFitCheck.ANCHOR_SEPARATION in {
        result.check for result in report.failures
    }


def test_manufacturing_gate_fails_closed() -> None:
    backend = SyntheticSnapShellBackend()
    parameters = SnapShellParameters(
        device_thickness_mm=4.7,
        locations=spaced_locations(),
        clip_width_mm=0.15,
        wall_mm=0.30,
        clip_height_mm=1.5,
        overhang_mm=0.6,
        clearance_mm=0.05,
        compliant_span_mm=2.0,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert SnapShellFitCheck.MANUFACTURING_CLEARANCE in {
        result.check for result in report.failures
    }
