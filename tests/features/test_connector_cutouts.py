"""Tests for reusable connector-cutout features."""

import cadquery as cq
import pytest

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
