"""Tests for Seeed Studio XIAO ESP32-S3 specification."""

from zcad_core.hardware import (
    get_seeed_xiao_esp32s3,
)


def test_xiao_esp32s3_dimensions() -> None:
    board = get_seeed_xiao_esp32s3()

    assert board.identifier == "SEEED_XIAO_ESP32_S3"
    assert board.geometry_evidence_status == "provisional"
    assert "USB-C envelope unverified" in (board.geometry_source)

    assert board.board_width_mm == 17.8
    assert board.board_length_mm == 21.0
    assert board.board_thickness_mm == 1.25

    assert board.recommended_standoff_height_mm == 3.0
    assert board.recommended_clearance_mm == 0.5


def test_xiao_esp32s3_usb_connector_metadata() -> None:
    board = get_seeed_xiao_esp32s3()
    connector = board.usb_connector

    assert connector.identifier == "USB_C"
    assert connector.width_mm == 9.0
    assert connector.height_mm == 3.2
    assert connector.depth_mm == 7.0
    assert connector.board_edge == "positive_y"
    assert connector.center_offset_mm == 0.0
    assert connector.bottom_offset_from_board_top_mm == 0.0

    connector.validate()


def test_xiao_esp32s3_returns_canonical_spec() -> None:
    assert get_seeed_xiao_esp32s3() is get_seeed_xiao_esp32s3()
