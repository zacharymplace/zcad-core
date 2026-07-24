"""Tests for reusable connector-cutout features."""

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    AssemblyComponent,
    Placement,
)
from zcad_core.features import (
    ConnectorCutoutParameters,
    cut_connector_opening,
)
from zcad_core.hardware import (
    get_raspberry_pi_pico2,
)


def test_parameters_derive_from_connector() -> None:
    board = get_raspberry_pi_pico2()

    parameters = ConnectorCutoutParameters.from_connector(
        connector=board.usb_connector,
        board_top_z_mm=6.0,
    )

    assert parameters.edge == "negative_y"
    assert parameters.bottom_z_mm == 6.0
    assert parameters.opening_width_mm == pytest.approx(9.5)
    assert parameters.opening_height_mm == pytest.approx(3.8)


def test_cut_connector_opening_removes_material() -> None:
    enclosure = cq.Workplane("XY").box(
        40.0,
        70.0,
        14.0,
        centered=(True, True, False),
    )

    board = get_raspberry_pi_pico2()

    parameters = ConnectorCutoutParameters.from_connector(
        connector=board.usb_connector,
        board_top_z_mm=6.0,
        cutter_depth_mm=8.0,
    )

    result = cut_connector_opening(
        enclosure,
        parameters=parameters,
    )

    assert result.val().isValid()
    assert result.val().Volume() < enclosure.val().Volume()


def test_cutout_supports_positive_x_edge() -> None:
    enclosure = cq.Workplane("XY").box(
        40.0,
        40.0,
        12.0,
        centered=(True, True, False),
    )

    parameters = ConnectorCutoutParameters(
        edge="positive_x",
        center_offset_mm=0.0,
        bottom_z_mm=4.0,
        width_mm=8.0,
        height_mm=3.0,
        cutter_depth_mm=8.0,
    )

    result = cut_connector_opening(
        enclosure,
        parameters=parameters,
    )

    assert result.val().isValid()
    assert result.val().Volume() < enclosure.val().Volume()


def test_cutout_rejects_negative_clearance() -> None:
    parameters = ConnectorCutoutParameters(
        edge="negative_y",
        center_offset_mm=0.0,
        bottom_z_mm=4.0,
        width_mm=8.0,
        height_mm=3.0,
        width_clearance_mm=-0.1,
    )

    with pytest.raises(
        ValueError,
        match="width_clearance_mm",
    ):
        parameters.validate()


def test_parameters_derive_from_negative_y_component() -> None:
    board = get_raspberry_pi_pico2()
    connector = board.usb_connector

    component = AssemblyComponent(
        identifier="usb_connector",
        geometry=cq.Workplane("XY").box(
            connector.width_mm,
            connector.depth_mm,
            connector.height_mm,
            centered=(True, True, False),
        ),
        placement=Placement(
            x_mm=2.5,
            y_mm=-20.0,
            z_mm=6.0,
        ),
    )

    parameters = ConnectorCutoutParameters.from_component(
        component=component,
        connector=connector,
    )

    assert parameters.edge == "negative_y"
    assert parameters.center_offset_mm == pytest.approx(2.5)
    assert parameters.bottom_z_mm == pytest.approx(6.0)
    assert parameters.width_mm == pytest.approx(connector.width_mm)
    assert parameters.height_mm == pytest.approx(connector.height_mm)


def test_parameters_derive_from_positive_x_component() -> None:
    from zcad_core.hardware import (
        RectangularConnectorSpec,
    )

    connector = RectangularConnectorSpec(
        identifier="TEST",
        width_mm=8.0,
        height_mm=3.0,
        depth_mm=5.0,
        board_edge="positive_x",
    )

    component = AssemblyComponent(
        identifier="connector",
        geometry=cq.Workplane("XY").box(
            connector.depth_mm,
            connector.width_mm,
            connector.height_mm,
            centered=(True, True, False),
        ),
        placement=Placement(
            x_mm=15.0,
            y_mm=-4.5,
            z_mm=7.0,
        ),
    )

    parameters = ConnectorCutoutParameters.from_component(
        component=component,
        connector=connector,
        width_clearance_mm=0.8,
        height_clearance_mm=0.4,
        cutter_depth_mm=6.0,
        cutter_overtravel_mm=1.5,
    )

    assert parameters.edge == "positive_x"
    assert parameters.center_offset_mm == pytest.approx(-4.5)
    assert parameters.bottom_z_mm == pytest.approx(7.0)
    assert parameters.opening_width_mm == pytest.approx(8.8)
    assert parameters.opening_height_mm == pytest.approx(3.4)
    assert parameters.cutter_depth_mm == pytest.approx(6.0)
    assert parameters.cutter_overtravel_mm == pytest.approx(1.5)


def test_component_constructor_uses_catalog_dimensions() -> None:
    from zcad_core.hardware import (
        RectangularConnectorSpec,
    )

    connector = RectangularConnectorSpec(
        identifier="CATALOG_CONNECTOR",
        width_mm=9.0,
        height_mm=3.5,
        depth_mm=6.0,
        board_edge="negative_y",
    )

    component = AssemblyComponent(
        identifier="connector",
        geometry=cq.Workplane("XY").box(
            20.0,
            20.0,
            20.0,
        ),
        placement=Placement(
            x_mm=1.0,
            z_mm=4.0,
        ),
    )

    parameters = ConnectorCutoutParameters.from_component(
        component=component,
        connector=connector,
    )

    assert parameters.width_mm == pytest.approx(9.0)
    assert parameters.height_mm == pytest.approx(3.5)
