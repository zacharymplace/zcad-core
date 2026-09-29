"""The board and display catalogs, and the boards added for enclosures."""

import pytest

from zcad_core.hardware import (
    get_adafruit_feather_rp2040,
    get_arduino_uno_r4_wifi,
    get_board,
    get_display,
    get_reference_oled_128x64,
    list_boards,
    list_displays,
)


def test_catalogs_list_every_board_and_display() -> None:
    assert list_boards() == (
        "ADAFRUIT_FEATHER_RP2040",
        "ARDUINO_UNO_R4_WIFI",
        "RASPBERRY_PI_PICO_2",
        "SEEED_XIAO_ESP32_S3",
    )
    assert list_displays() == ("REFERENCE_OLED_128X64",)


def test_lookup_ignores_case() -> None:
    assert get_board("arduino_uno_r4_wifi") is get_arduino_uno_r4_wifi()
    assert get_display("reference_oled_128x64") is get_reference_oled_128x64()


def test_unknown_board_is_refused() -> None:
    with pytest.raises(ValueError, match="Unsupported board: NOPE"):
        get_board("NOPE")


def test_feather_matches_the_vendor_model() -> None:
    feather = get_adafruit_feather_rp2040()

    assert (feather.board_width_mm, feather.board_length_mm) == (22.86, 50.8)
    assert feather.board_thickness_mm == pytest.approx(1.57)
    assert (feather.mounting_hole_spacing_x_mm, feather.mounting_hole_spacing_y_mm) == (
        17.78,
        45.72,
    )
    feather.usb_connector.validate()


def test_uno_holes_lie_inside_the_board() -> None:
    uno = get_arduino_uno_r4_wifi()
    margin = uno.mounting_hole_diameter_mm / 2

    assert uno.geometry_evidence_status == "provisional"
    for x, y in uno.mounting_hole_positions_mm:
        assert abs(x) + margin < uno.board_width_mm / 2
        assert abs(y) + margin < uno.board_length_mm / 2
    uno.usb_connector.validate()
