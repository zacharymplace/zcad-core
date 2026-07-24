"""Tests for Raspberry Pi Pico 2 specification."""

from zcad_core.hardware import (
    get_raspberry_pi_pico2,
)


def test_pico2_dimensions() -> None:
    board = get_raspberry_pi_pico2()

    assert board.board_width_mm == 21.0
    assert board.board_length_mm == 51.0
    assert board.board_thickness_mm == 1.0

    assert board.mounting_hole_diameter_mm == 2.1

    assert board.recommended_standoff_height_mm == 3.0
    assert board.recommended_clearance_mm == 0.5
