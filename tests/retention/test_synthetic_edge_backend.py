from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.types import BoardEdge
from zcad_core.retention import (
    EdgeCaptureBackend,
    EdgeCaptureFitCheck,
    EdgeCaptureLocation,
    EdgeCaptureParameters,
    EdgeCapturePolicy,
    EdgeCaptureRequest,
    SyntheticEdgeCaptureBackend,
)


def spaced_locations() -> tuple[EdgeCaptureLocation, ...]:
    return (
        EdgeCaptureLocation(
            edge=BoardEdge.NEGATIVE_Y,
            position_mm=4.0,
            edge_coordinate_mm=0.0,
        ),
        EdgeCaptureLocation(
            edge=BoardEdge.NEGATIVE_Y,
            position_mm=16.0,
            edge_coordinate_mm=0.0,
        ),
    )


def valid_request() -> EdgeCaptureRequest:
    return EdgeCaptureRequest(
        board_thickness_mm=1.6,
        locations=spaced_locations(),
        policy=EdgeCapturePolicy(),
    )


def test_backend_satisfies_protocol() -> None:
    backend = SyntheticEdgeCaptureBackend()

    assert isinstance(
        backend,
        EdgeCaptureBackend,
    )


def test_derive_reuses_validated_parameters() -> None:
    backend = SyntheticEdgeCaptureBackend()

    parameters = backend.derive(valid_request())

    assert parameters.board_thickness_mm == pytest.approx(1.6)
    assert parameters.locations == spaced_locations()
    assert parameters.arm_width_mm == pytest.approx(5.0)


def test_apply_requires_cadquery_workplane() -> None:
    backend = SyntheticEdgeCaptureBackend()
    parameters = backend.derive(valid_request())

    with pytest.raises(
        TypeError,
        match="cadquery.Workplane",
    ):
        backend.apply(
            object(),
            parameters,
        )


def test_apply_adds_edge_capture_geometry() -> None:
    backend = SyntheticEdgeCaptureBackend()
    parameters = backend.derive(valid_request())

    base = (
        cq.Workplane("XY")
        .box(
            20.0,
            30.0,
            1.6,
        )
        .translate(
            (
                10.0,
                15.0,
                0.8,
            )
        )
    )

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
    backend = SyntheticEdgeCaptureBackend()
    parameters = backend.derive(valid_request())
    base = cq.Workplane("XY").box(
        20.0,
        30.0,
        1.6,
    )

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
    backend = SyntheticEdgeCaptureBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    assert report.passed is True
    assert report.failures == ()
    assert {result.check for result in report.results} == set(EdgeCaptureFitCheck)


def test_component_clearance_detail_is_explicitly_synthetic() -> None:
    backend = SyntheticEdgeCaptureBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    component_result = next(
        result
        for result in report.results
        if result.check is EdgeCaptureFitCheck.COMPONENT_CLEARANCE
    )

    assert component_result.passed is True
    assert "production clearance remains unverified" in (component_result.detail)


def test_edge_material_continuity_detail_is_explicitly_synthetic() -> None:
    backend = SyntheticEdgeCaptureBackend()
    parameters = backend.derive(valid_request())

    report = backend.analyze_fit(parameters)

    material_result = next(
        result
        for result in report.results
        if result.check is EdgeCaptureFitCheck.EDGE_MATERIAL_CONTINUITY
    )

    assert material_result.passed is True
    assert "production evidence is required" in (material_result.detail)


def test_anchor_separation_fails_when_locations_are_too_close() -> None:
    backend = SyntheticEdgeCaptureBackend()
    parameters = EdgeCaptureParameters(
        board_thickness_mm=1.6,
        locations=(
            EdgeCaptureLocation(
                edge=BoardEdge.NEGATIVE_Y,
                position_mm=4.0,
                edge_coordinate_mm=0.0,
            ),
            EdgeCaptureLocation(
                edge=BoardEdge.NEGATIVE_Y,
                position_mm=5.0,
                edge_coordinate_mm=0.0,
            ),
        ),
        arm_width_mm=6.0,
        engagement_depth_mm=2.5,
        board_clearance_mm=0.25,
        vertical_overlap_mm=0.6,
        minimum_wall_mm=1.2,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert {result.check for result in report.failures} == {
        EdgeCaptureFitCheck.ANCHOR_SEPARATION
    }


def test_manufacturing_gate_fails_closed() -> None:
    backend = SyntheticEdgeCaptureBackend()
    parameters = EdgeCaptureParameters(
        board_thickness_mm=1.6,
        locations=spaced_locations(),
        arm_width_mm=0.15,
        engagement_depth_mm=2.5,
        board_clearance_mm=0.10,
        vertical_overlap_mm=0.6,
        minimum_wall_mm=0.50,
    )

    report = backend.analyze_fit(parameters)

    assert report.passed is False
    assert EdgeCaptureFitCheck.MANUFACTURING_CLEARANCE in {
        result.check for result in report.failures
    }


@pytest.mark.parametrize(
    "edge",
    tuple(BoardEdge),
)
def test_capture_geometry_does_not_intersect_board(
    edge: BoardEdge,
) -> None:
    backend = SyntheticEdgeCaptureBackend()

    board = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8))
    pcb = workplane_shape(board)
    bounds = pcb.BoundingBox()

    edge_coordinate = {
        BoardEdge.NEGATIVE_X: bounds.xmin,
        BoardEdge.POSITIVE_X: bounds.xmax,
        BoardEdge.NEGATIVE_Y: bounds.ymin,
        BoardEdge.POSITIVE_Y: bounds.ymax,
    }[edge]
    along_range = (
        (bounds.ymin, bounds.ymax)
        if edge in (BoardEdge.NEGATIVE_X, BoardEdge.POSITIVE_X)
        else (bounds.xmin, bounds.xmax)
    )
    quarter = (along_range[1] - along_range[0]) / 4.0

    locations = (
        EdgeCaptureLocation(
            edge=edge,
            position_mm=along_range[0] + quarter,
            edge_coordinate_mm=edge_coordinate,
        ),
        EdgeCaptureLocation(
            edge=edge,
            position_mm=along_range[1] - quarter,
            edge_coordinate_mm=edge_coordinate,
        ),
    )

    parameters = backend.derive(
        EdgeCaptureRequest(
            board_thickness_mm=1.6,
            locations=locations,
            policy=EdgeCapturePolicy(),
        )
    )

    capture = workplane_shape(backend.build_geometry(parameters))
    intersection = capture.intersect(pcb)
    volume = 0.0 if intersection.isNull() else float(intersection.Volume())

    assert volume == pytest.approx(
        0.0,
        abs=1e-6,
    )
