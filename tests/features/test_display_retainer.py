"""The lid-hung display retainer."""

from __future__ import annotations

from dataclasses import replace

import cadquery as cq
import pytest

from zcad_core.assemblies import Placement, build_board_display_assembly
from zcad_core.features import (
    DisplayPostParameters,
    DisplayRetainerParameters,
    Enclosure,
    EnclosureDesign,
    add_display_retainer,
    build_enclosure,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import (
    get_display,
    get_raspberry_pi_pico2,
    get_reference_oled_128x64,
)

DISPLAY = get_reference_oled_128x64()
LID_UNDERSIDE_MM = 20.0
MODULE_TOP_MM = 18.0
PARAMETERS = DisplayRetainerParameters(
    center_x_mm=0.0,
    center_y_mm=0.0,
    module_width_mm=DISPLAY.module_width_mm,
    module_depth_mm=DISPLAY.module_height_mm,
    module_thickness_mm=DISPLAY.module_depth_mm,
    module_top_z_mm=MODULE_TOP_MM,
    lid_underside_z_mm=LID_UNDERSIDE_MM,
)
HALF_W = DISPLAY.module_width_mm / 2
HALF_D = DISPLAY.module_height_mm / 2
MODULE_BOTTOM_MM = MODULE_TOP_MM - DISPLAY.module_depth_mm


def module() -> cq.Solid:
    return cq.Solid.makeBox(
        DISPLAY.module_width_mm,
        DISPLAY.module_height_mm,
        DISPLAY.module_depth_mm,
        pnt=cq.Vector(-HALF_W, -HALF_D, MODULE_BOTTOM_MM),
    )


@pytest.fixture(scope="module")
def retainer() -> cq.Solid:
    lid = (
        cq.Workplane("XY")
        .box(50, 50, 2, centered=(True, True, False))
        .translate((0, 0, LID_UNDERSIDE_MM))
    )
    (only,) = add_display_retainer(lid, parameters=PARAMETERS).solids().vals()
    assert isinstance(only, cq.Solid)

    return only


def test_module_fits_without_overlap(retainer: cq.Solid) -> None:
    assert intersection_volume(retainer, module()) == 0


def test_pads_hold_the_module_face_below_the_lid(retainer: cq.Solid) -> None:
    for sx in (-1, 1):
        for sy in (-1, 1):
            corner = cq.Vector(
                sx * (HALF_W - 1), sy * (HALF_D - 1), MODULE_TOP_MM + 0.5
            )
            assert retainer.isInside(corner)

    assert retainer.distance(module()) == pytest.approx(0.0, abs=1e-6)
    # The pads stay clear of the active area.
    assert not retainer.isInside(cq.Vector(0, 0, MODULE_TOP_MM + 0.5))


def test_side_clips_hook_under_the_module(retainer: cq.Solid) -> None:
    lip_z = MODULE_BOTTOM_MM - PARAMETERS.clip_gap_mm - 0.5

    for side in (-1, 1):
        assert retainer.isInside(cq.Vector(side * (HALF_W - 0.4), 0, lip_z))


def test_header_edges_stay_open(retainer: cq.Solid) -> None:
    beside = HALF_D + PARAMETERS.clearance_mm + PARAMETERS.wall_mm / 2

    for side in (-1, 1):
        assert not retainer.isInside(cq.Vector(0, side * beside, MODULE_TOP_MM - 1.0))


def test_no_pads_when_the_module_meets_the_lid() -> None:
    flush = replace(PARAMETERS, module_top_z_mm=LID_UNDERSIDE_MM)
    lid = (
        cq.Workplane("XY")
        .box(50, 50, 2, centered=(True, True, False))
        .translate((0, 0, LID_UNDERSIDE_MM))
    )

    model = add_display_retainer(lid, parameters=flush)

    (solid,) = model.solids().vals()
    assert isinstance(solid, cq.Solid)
    assert not solid.isInside(cq.Vector(HALF_W - 1, HALF_D - 1, LID_UNDERSIDE_MM - 0.5))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"wall_mm": 0}, "wall_mm must be greater than zero"),
        ({"clip_gap_mm": -0.1}, "clip_gap_mm must not be negative"),
        ({"module_top_z_mm": 21.0}, "must sit under the lid"),
        ({"clip_reach_mm": 0.2}, "must exceed clearance_mm"),
        ({"corner_leg_mm": 12.0}, "too short for its corner posts"),
        ({"pad_mm": 14.0}, "pad_mm is too large"),
    ],
)
def test_parameters_reject_invalid_geometry(
    change: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(PARAMETERS, **change).validate()


def enclosure_lid(design: EnclosureDesign) -> cq.Shape:
    board = get_raspberry_pi_pico2()
    assembly = build_board_display_assembly(
        board=board,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )
    lid = build_enclosure(assembly, board=board, display=DISPLAY, design=design).lid
    shape = lid.val()
    assert isinstance(shape, cq.Shape)

    return shape


def test_enclosure_lid_holds_the_display_unless_turned_off() -> None:
    held = enclosure_lid(EnclosureDesign())
    plain = enclosure_lid(EnclosureDesign(display_retainer=False))
    display_top = 8.0 + DISPLAY.module_depth_mm

    assert held.BoundingBox().zmin < display_top - DISPLAY.module_depth_mm
    assert plain.BoundingBox().zmin == pytest.approx(
        display_top + EnclosureDesign().top_clearance_mm
    )


SCREWED = get_display("ADAFRUIT_OLED_128X64_1_3IN")


def screwed_enclosure(design: EnclosureDesign | None = None) -> tuple[Enclosure, float]:
    board = get_raspberry_pi_pico2()
    assembly = build_board_display_assembly(
        board=board,
        display=SCREWED,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )
    enclosure = build_enclosure(assembly, board=board, display=SCREWED, design=design)

    return enclosure, 8.0 + SCREWED.module_depth_mm - (SCREWED.panel_thickness_mm or 0)


def test_display_with_holes_screws_to_lid_posts() -> None:
    enclosure, pcb_face = screwed_enclosure()
    (lid,) = enclosure.lid.solids().vals()
    assert isinstance(lid, cq.Solid)
    half_x = (SCREWED.mounting_hole_spacing_x_mm or 0) / 2
    half_y = (SCREWED.mounting_hole_spacing_y_mm or 0) / 2

    assert enclosure.display_support == "posts"
    assert enclosure.display_screw_count == 4
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * half_x, sy * half_y
            # The post reaches the PCB face; its pilot hole is open.
            assert lid.isInside(cq.Vector(x + 1.5, y, pcb_face + 0.2))
            assert not lid.isInside(cq.Vector(x, y, pcb_face + 0.5))
    # The window is over the active area, off the panel centre.
    top = lid.BoundingBox().zmax
    assert not lid.isInside(cq.Vector(0, SCREWED.active_center_y_mm, top - 1.0))


def test_screw_reach_is_the_pcb_and_post() -> None:
    enclosure, pcb_face = screwed_enclosure()
    spec = enclosure.specification
    cavity_top = spec.bottom_z_mm + spec.inner_height_mm

    assert enclosure.display_screw_reach_mm == pytest.approx(
        cavity_top - pcb_face + (SCREWED.pcb_thickness_mm or 0)
    )


def test_refuses_display_screws_too_big_for_its_holes() -> None:
    with pytest.raises(ValueError, match="do not fit the display's 2.5 mm holes"):
        screwed_enclosure(EnclosureDesign(display_fastener="M3"))


def test_post_parameters_reject_invalid_geometry() -> None:
    posts = DisplayPostParameters(
        positions=((0.0, 0.0),),
        pcb_face_z_mm=10.0,
        lid_underside_z_mm=14.0,
        pilot_hole_mm=1.6,
        outer_diameter_mm=4.0,
    )
    posts.validate()

    for change, message in (
        ({"positions": ()}, "at least one post"),
        ({"outer_diameter_mm": 3.0}, "at least 0.8 mm thick"),
        ({"pcb_face_z_mm": 14.0}, "below the lid"),
    ):
        with pytest.raises(ValueError, match=message):
            replace(posts, **change).validate()
