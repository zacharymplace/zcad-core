"""The board and display catalogs, and the boards added for enclosures."""

import pytest

from zcad_core.hardware import (
    get_adafruit_feather_rp2040,
    get_arduino_uno_r4_wifi,
    get_board,
    get_display,
    get_raspberry_pi5,
    get_reference_oled_128x64,
    list_boards,
    list_displays,
)


def test_catalogs_list_every_board_and_display() -> None:
    assert list_boards() == (
        "ADAFRUIT_FEATHER_RP2040",
        "ARDUINO_UNO_R4_WIFI",
        "RASPBERRY_PI_5",
        "RASPBERRY_PI_PICO_2",
        "SEEED_XIAO_ESP32_S3",
    )
    assert list_displays() == (
        "ADAFRUIT_EINK_200X200_1_54IN",
        "ADAFRUIT_OLED_128X128_1_5IN",
        "ADAFRUIT_OLED_128X64_1_3IN",
        "REFERENCE_OLED_128X64",
    )


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


def test_the_pi5_declares_its_hdmi_ports_and_card_but_not_its_power_input() -> None:
    openings = {
        wall.identifier: wall for wall in get_board("RASPBERRY_PI_5").wall_openings
    }

    assert set(openings) == {
        "ETHERNET",
        "USB3_PAIR",
        "USB2_PAIR",
        "MICRO_HDMI_0",
        "MICRO_HDMI_1",
        "MICRO_SD",
    }
    card = openings["MICRO_SD"]
    assert card.edge == "negative_y"
    assert card.bottom_offset_from_board_top_mm + card.height_mm == pytest.approx(-1.4)


@pytest.mark.parametrize("identifier", list_boards())
def test_other_boards_declare_no_wall_openings(identifier: str) -> None:
    if identifier != "RASPBERRY_PI_5":
        assert get_board(identifier).wall_openings == ()


def test_a_fitted_active_cooler_adds_the_cooler_and_a_vented_fan() -> None:
    pi = get_raspberry_pi5()
    cooled = pi.with_active_cooler()
    added = {part.identifier: part for part in cooled.components[len(pi.components) :]}

    assert set(added) == {"active-cooler", "active-cooler-fan"}
    assert added["active-cooler-fan"].lid_vent
    assert not added["active-cooler"].lid_vent
    fan = added["active-cooler-fan"]
    assert fan.bottom_offset_from_board_top_mm + fan.height_mm == pi.cooler_height_mm
    # The bare board is unchanged.
    assert not any(part.lid_vent for part in pi.components)
