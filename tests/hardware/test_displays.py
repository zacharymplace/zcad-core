"""Tests for display hardware specifications."""

import pytest

from zcad_core.hardware import (
    DisplaySpec,
    get_reference_oled_128x64,
)


def test_reference_display_is_valid() -> None:
    display = get_reference_oled_128x64()

    display.validate()

    assert display.identifier == ("REFERENCE_OLED_128X64")
    assert display.active_width_mm < (display.module_width_mm)
    assert display.active_height_mm < (display.module_height_mm)


def test_display_rejects_oversized_active_area() -> None:
    display = DisplaySpec(
        identifier="INVALID",
        module_width_mm=20.0,
        module_height_mm=20.0,
        module_depth_mm=3.0,
        active_width_mm=21.0,
        active_height_mm=10.0,
    )

    with pytest.raises(
        ValueError,
        match="active_width_mm",
    ):
        display.validate()


def test_partial_mounting_pattern_is_rejected() -> None:
    display = DisplaySpec(
        identifier="INVALID",
        module_width_mm=30.0,
        module_height_mm=20.0,
        module_depth_mm=3.0,
        active_width_mm=20.0,
        active_height_mm=10.0,
        mounting_hole_diameter_mm=2.0,
    )

    with pytest.raises(
        ValueError,
        match="mounting-hole",
    ):
        display.validate()
