"""Tests for electronics connector specifications."""

import pytest

from zcad_core.hardware import (
    RectangularConnectorSpec,
    get_raspberry_pi_pico2,
)


def test_pico2_usb_connector_metadata() -> None:
    board = get_raspberry_pi_pico2()
    connector = board.usb_connector

    assert connector.identifier == "USB_MICRO_B"
    assert connector.width_mm == 8.9
    assert connector.height_mm == 3.2
    assert connector.depth_mm == pytest.approx(6.075)
    assert connector.board_edge == "negative_y"
    assert connector.center_offset_mm == 0.0


def test_connector_validation() -> None:
    connector = RectangularConnectorSpec(
        identifier="TEST",
        width_mm=8.0,
        height_mm=3.0,
        depth_mm=5.0,
        board_edge="positive_x",
    )

    connector.validate()


def test_connector_rejects_invalid_width() -> None:
    connector = RectangularConnectorSpec(
        identifier="TEST",
        width_mm=0.0,
        height_mm=3.0,
        depth_mm=5.0,
        board_edge="positive_x",
    )

    with pytest.raises(
        ValueError,
        match="width_mm",
    ):
        connector.validate()


def test_connector_rejects_invalid_depth() -> None:
    connector = RectangularConnectorSpec(
        identifier="TEST",
        width_mm=8.0,
        height_mm=3.0,
        depth_mm=0.0,
        board_edge="positive_x",
    )

    with pytest.raises(
        ValueError,
        match="depth_mm",
    ):
        connector.validate()
