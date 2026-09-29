"""Tests for display-window and bezel features."""

import cadquery as cq
import pytest

from zcad_core.features import (
    DisplayBezelParameters,
    DisplayWindowParameters,
    add_display_bezel,
    cut_display_window,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import (
    get_reference_oled_128x64,
)


def test_window_derives_from_display() -> None:
    display = get_reference_oled_128x64()

    window = DisplayWindowParameters.from_display(
        display=display,
        panel_base_z_mm=0.0,
        panel_thickness_mm=2.0,
    )

    assert window.opening_width_mm == pytest.approx(22.8)
    assert window.opening_height_mm == pytest.approx(11.8)


def test_display_window_removes_material() -> None:
    panel = cq.Workplane("XY").box(
        40.0,
        30.0,
        2.0,
        centered=(True, True, False),
    )

    window = DisplayWindowParameters.from_display(
        display=get_reference_oled_128x64(),
        panel_base_z_mm=0.0,
        panel_thickness_mm=2.0,
    )

    result = cut_display_window(
        panel,
        parameters=window,
    )

    assert workplane_shape(result).isValid()
    assert workplane_shape(result).Volume() < workplane_shape(panel).Volume()


def test_display_bezel_adds_material() -> None:
    panel = cq.Workplane("XY").box(
        40.0,
        30.0,
        2.0,
        centered=(True, True, False),
    )

    window = DisplayWindowParameters.from_display(
        display=get_reference_oled_128x64(),
        panel_base_z_mm=0.0,
        panel_thickness_mm=2.0,
    )

    cut_panel = cut_display_window(
        panel,
        parameters=window,
    )

    bezel = DisplayBezelParameters.from_window(
        window=window,
    )

    result = add_display_bezel(
        cut_panel,
        parameters=bezel,
    )

    assert workplane_shape(result).isValid()
    assert workplane_shape(result).Volume() > (workplane_shape(cut_panel).Volume())


def test_window_rejects_excessive_radius() -> None:
    window = DisplayWindowParameters(
        x=0.0,
        y=0.0,
        panel_base_z_mm=0.0,
        panel_thickness_mm=2.0,
        opening_width_mm=20.0,
        opening_height_mm=10.0,
        corner_radius_mm=5.0,
    )

    with pytest.raises(
        ValueError,
        match="corner_radius_mm",
    ):
        window.validate()
