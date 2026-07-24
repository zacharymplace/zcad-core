"""Tests for reusable enclosure-boundary primitives."""

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    AssemblyComponent,
    ClearanceEnvelope,
    EnclosureBoundary,
    Placement,
    analyze_boundary_clearance,
)


def _boundary() -> EnclosureBoundary:
    return EnclosureBoundary(
        inner_width_mm=40.0,
        inner_depth_mm=60.0,
        wall_height_mm=12.0,
        wall_thickness_mm=2.0,
        center_x_mm=3.0,
        center_y_mm=-4.0,
        bottom_z_mm=1.5,
    )


@pytest.mark.parametrize(
    (
        "edge",
        "expected_center_x_mm",
        "expected_center_y_mm",
        "expected_xlen_mm",
        "expected_ylen_mm",
    ),
    (
        (
            "negative_x",
            -18.0,
            -4.0,
            2.0,
            60.0,
        ),
        (
            "positive_x",
            24.0,
            -4.0,
            2.0,
            60.0,
        ),
        (
            "negative_y",
            3.0,
            -35.0,
            40.0,
            2.0,
        ),
        (
            "positive_y",
            3.0,
            27.0,
            40.0,
            2.0,
        ),
    ),
)
def test_wall_component_supports_all_lateral_edges(
    edge: str,
    expected_center_x_mm: float,
    expected_center_y_mm: float,
    expected_xlen_mm: float,
    expected_ylen_mm: float,
) -> None:
    wall = _boundary().wall_component(
        edge=edge,
    )

    bounds = wall.transformed_geometry().val().BoundingBox()

    assert wall.identifier == f"{edge}_wall"
    assert wall.metadata["kind"] == ("enclosure_wall")
    assert wall.metadata["edge"] == edge

    assert bounds.center.x == pytest.approx(expected_center_x_mm)
    assert bounds.center.y == pytest.approx(expected_center_y_mm)
    assert bounds.zmin == pytest.approx(1.5)
    assert bounds.zmax == pytest.approx(13.5)

    assert bounds.xlen == pytest.approx(expected_xlen_mm)
    assert bounds.ylen == pytest.approx(expected_ylen_mm)


def test_exact_directional_boundary_clearance_passes() -> None:
    component = AssemblyComponent(
        identifier="connector",
        geometry=cq.Workplane("XY").box(
            8.0,
            6.0,
            4.0,
            centered=(True, True, False),
        ),
        placement=Placement(
            y_mm=-25.0,
            z_mm=3.0,
        ),
        clearance_envelope=ClearanceEnvelope(
            negative_y_mm=2.0,
        ),
    )

    boundary = EnclosureBoundary(
        inner_width_mm=30.0,
        inner_depth_mm=60.0,
        wall_height_mm=10.0,
        wall_thickness_mm=2.0,
    )

    report = analyze_boundary_clearance(
        component=component,
        boundary=boundary,
        edge="negative_y",
    )

    assert not report.has_findings


def test_insufficient_directional_boundary_clearance_is_reported() -> None:
    component = AssemblyComponent(
        identifier="connector",
        geometry=cq.Workplane("XY").box(
            8.0,
            6.0,
            4.0,
            centered=(True, True, False),
        ),
        placement=Placement(
            y_mm=-26.0,
            z_mm=3.0,
        ),
        clearance_envelope=ClearanceEnvelope(
            negative_y_mm=2.0,
        ),
    )

    boundary = EnclosureBoundary(
        inner_width_mm=30.0,
        inner_depth_mm=60.0,
        wall_height_mm=10.0,
        wall_thickness_mm=2.0,
    )

    report = analyze_boundary_clearance(
        component=component,
        boundary=boundary,
        edge="negative_y",
        wall_identifier="usb_wall",
    )

    assert not report.collisions
    assert len(report.clearance_violations) == 1

    finding = report.clearance_violations[0]

    assert finding.pair == frozenset(
        (
            "connector",
            "usb_wall",
        )
    )
    assert finding.measured_clearance_mm == (pytest.approx(1.0))
    assert finding.required_clearance_mm == (pytest.approx(2.0))
    assert finding.clearance_source == "envelope"


@pytest.mark.parametrize(
    "field",
    (
        "inner_width_mm",
        "inner_depth_mm",
        "wall_height_mm",
        "wall_thickness_mm",
    ),
)
def test_boundary_rejects_nonpositive_dimensions(
    field: str,
) -> None:
    values = {
        "inner_width_mm": 40.0,
        "inner_depth_mm": 60.0,
        "wall_height_mm": 12.0,
        "wall_thickness_mm": 2.0,
    }
    values[field] = 0.0

    with pytest.raises(
        ValueError,
        match=field,
    ):
        EnclosureBoundary(
            **values,
        )


def test_wall_component_rejects_empty_identifier() -> None:
    with pytest.raises(
        ValueError,
        match="wall identifier",
    ):
        _boundary().wall_component(
            edge="positive_x",
            identifier=" ",
        )


def test_wall_component_rejects_unsupported_edge() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported enclosure boundary edge",
    ):
        _boundary().wall_component(
            edge="positive_z",
        )
