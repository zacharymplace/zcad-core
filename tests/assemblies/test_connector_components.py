"""Tests for reusable board-edge connector components."""

import pytest

from zcad_core.assemblies import (
    ClearanceEnvelope,
    Placement,
    build_board_edge_connector_component,
)
from zcad_core.assemblies.retention import BoardEdge
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import (
    RectangularConnectorSpec,
)


@pytest.mark.parametrize(
    (
        "edge",
        "expected_x_mm",
        "expected_y_mm",
        "expected_size_x_mm",
        "expected_size_y_mm",
    ),
    (
        (
            "negative_x",
            3.5,
            22.0,
            5.0,
            8.0,
        ),
        (
            "positive_x",
            16.5,
            22.0,
            5.0,
            8.0,
        ),
        (
            "negative_y",
            12.0,
            -2.5,
            8.0,
            5.0,
        ),
        (
            "positive_y",
            12.0,
            42.5,
            8.0,
            5.0,
        ),
    ),
)
def test_connector_component_is_oriented_and_placed_by_edge(
    edge: BoardEdge,
    expected_x_mm: float,
    expected_y_mm: float,
    expected_size_x_mm: float,
    expected_size_y_mm: float,
) -> None:
    connector = RectangularConnectorSpec(
        identifier="TEST_CONNECTOR",
        width_mm=8.0,
        height_mm=3.0,
        depth_mm=5.0,
        board_edge=edge,
        center_offset_mm=2.0,
        bottom_offset_from_board_top_mm=0.5,
    )

    component = build_board_edge_connector_component(
        identifier="connector",
        connector=connector,
        board_width_mm=18.0,
        board_length_mm=50.0,
        board_thickness_mm=1.0,
        board_placement=Placement(
            x_mm=10.0,
            y_mm=20.0,
            z_mm=4.0,
        ),
    )

    bounds = workplane_shape(component.geometry).BoundingBox()

    assert component.placement.x_mm == pytest.approx(expected_x_mm)
    assert component.placement.y_mm == pytest.approx(expected_y_mm)
    assert component.placement.z_mm == pytest.approx(5.5)

    assert bounds.xlen == pytest.approx(expected_size_x_mm)
    assert bounds.ylen == pytest.approx(expected_size_y_mm)
    assert bounds.zlen == pytest.approx(3.0)


def test_connector_component_preserves_metadata_and_clearance() -> None:
    connector = RectangularConnectorSpec(
        identifier="USB_C",
        width_mm=9.0,
        height_mm=3.2,
        depth_mm=7.0,
        board_edge="negative_y",
    )
    envelope = ClearanceEnvelope.for_edge(
        edge="negative_y",
        clearance_mm=3.0,
    )

    component = build_board_edge_connector_component(
        identifier="usb_connector",
        connector=connector,
        board_width_mm=21.0,
        board_length_mm=51.0,
        board_thickness_mm=1.0,
        board_placement=Placement(),
        clearance_envelope=envelope,
    )

    assert component.metadata == {
        "kind": "connector",
        "hardware_identifier": "USB_C",
        "board_edge": "negative_y",
        "width_mm": 9.0,
        "depth_mm": 7.0,
        "height_mm": 3.2,
    }
    assert component.clearance_envelope is envelope


def test_connector_component_rejects_invalid_board_dimensions() -> None:
    connector = RectangularConnectorSpec(
        identifier="TEST",
        width_mm=8.0,
        height_mm=3.0,
        depth_mm=5.0,
        board_edge="positive_x",
    )

    with pytest.raises(
        ValueError,
        match="board_width_mm",
    ):
        build_board_edge_connector_component(
            identifier="connector",
            connector=connector,
            board_width_mm=0.0,
            board_length_mm=50.0,
            board_thickness_mm=1.0,
            board_placement=Placement(),
        )
