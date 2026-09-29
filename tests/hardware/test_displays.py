"""Tests for display hardware specifications."""

from dataclasses import replace
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.hardware import (
    ADAFRUIT_EINK_200X200_1_54IN,
    ADAFRUIT_OLED_128X64_1_3IN,
    ADAFRUIT_OLED_128X128_1_5IN,
    DisplaySpec,
    get_reference_oled_128x64,
)

EVIDENCE = Path(__file__).resolve().parents[2] / "evidence"


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


ADAFRUIT_DISPLAYS = (
    ADAFRUIT_OLED_128X64_1_3IN,
    ADAFRUIT_OLED_128X128_1_5IN,
    ADAFRUIT_EINK_200X200_1_54IN,
)


@pytest.mark.parametrize("display", ADAFRUIT_DISPLAYS, ids=lambda d: d.identifier)
def test_adafruit_displays_are_layered_with_screw_holes(display: DisplaySpec) -> None:
    display.validate()

    assert display.is_layered
    assert display.back_depth_mm > 0
    assert display.mount_style == "screws"
    assert display.mounting_hole_diameter_mm == 2.5
    assert display.geometry_source
    # The active area lies within the panel.
    assert display.panel_width_mm is not None
    assert display.panel_height_mm is not None
    assert (
        abs(display.active_center_x_mm - display.panel_center_x_mm)
        + display.active_width_mm / 2
        <= display.panel_width_mm / 2
    )
    assert (
        abs(display.active_center_y_mm - display.panel_center_y_mm)
        + display.active_height_mm / 2
        <= display.panel_height_mm / 2
    )


def test_layered_display_needs_every_layer() -> None:
    with pytest.raises(ValueError, match="a layered display needs"):
        replace(ADAFRUIT_OLED_128X64_1_3IN, panel_width_mm=None).validate()


def test_layered_display_must_hold_its_layers() -> None:
    with pytest.raises(ValueError, match="must hold the panel and the PCB"):
        replace(ADAFRUIT_OLED_128X64_1_3IN, module_depth_mm=3.0).validate()


def test_panel_must_lie_within_the_module() -> None:
    with pytest.raises(ValueError, match="within the module outline"):
        replace(ADAFRUIT_OLED_128X64_1_3IN, panel_center_y_mm=6.0).validate()


@pytest.mark.slow
@pytest.mark.parametrize(
    ("display", "model"),
    [
        (ADAFRUIT_OLED_128X64_1_3IN, "adafruit-oled-938"),
        (ADAFRUIT_OLED_128X128_1_5IN, "adafruit-oled-4741"),
        (ADAFRUIT_EINK_200X200_1_54IN, "adafruit-eink-4196"),
    ],
    ids=lambda value: getattr(value, "identifier", value),
)
def test_display_matches_its_vendor_model(display: DisplaySpec, model: str) -> None:
    steps = sorted((EVIDENCE / model / "step").glob("*.step"))

    if not steps:
        pytest.skip("the vendor model is in the evidence checkout")

    solids = [
        solid
        for solid in cq.importers.importStep(str(steps[0])).solids().vals()
        if isinstance(solid, cq.Shape)
    ]
    pcb = max(
        solids, key=lambda solid: solid.BoundingBox().xlen * solid.BoundingBox().ylen
    )
    bounds = pcb.BoundingBox()
    holes = {
        (round(face.Center().x, 1), round(face.Center().y, 1))
        for face in pcb.Faces()
        if face.geomType() == "CYLINDER"
        and abs(max(face.BoundingBox().xlen, face.BoundingBox().ylen) - 2.5) < 0.02
    }

    assert (bounds.xlen, bounds.ylen) == pytest.approx(
        (display.module_width_mm, display.module_height_mm), abs=0.01
    )
    assert bounds.zlen == pytest.approx(display.pcb_thickness_mm, abs=0.01)
    xs, ys = sorted({x for x, _ in holes}), sorted({y for _, y in holes})
    assert xs[-1] - xs[0] == pytest.approx(display.mounting_hole_spacing_x_mm, abs=0.1)
    assert ys[-1] - ys[0] == pytest.approx(display.mounting_hole_spacing_y_mm, abs=0.1)
