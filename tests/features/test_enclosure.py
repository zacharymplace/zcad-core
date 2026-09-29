from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    build_board_display_assembly,
)
from zcad_core.features import (
    Enclosure,
    EnclosureDesign,
    build_enclosure,
    centered_mounting_hole_positions,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_raspberry_pi_pico2, get_reference_oled_128x64

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()
DISPLAY_HEIGHT_MM = 8.0
CLEAR_DESIGN = EnclosureDesign(internal_clearance_mm=5.0)


def pico2_oled_assembly() -> DeviceAssembly:
    return build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=DISPLAY_HEIGHT_MM),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )


@pytest.fixture(scope="module")
def enclosure() -> Enclosure:
    return build_enclosure(
        pico2_oled_assembly(), board=BOARD, display=DISPLAY, design=CLEAR_DESIGN
    )


def solid(model: cq.Workplane) -> cq.Solid:
    (only,) = model.solids().vals()
    assert isinstance(only, cq.Solid)

    return only


def cavity_top(enclosure: Enclosure) -> float:
    spec = enclosure.specification

    return spec.bottom_z_mm + spec.inner_height_mm


def test_refuses_bosses_that_would_hit_the_board() -> None:
    with pytest.raises(ValueError, match="base intersects 'board'"):
        build_enclosure(pico2_oled_assembly(), board=BOARD, display=DISPLAY)


def test_base_and_lid_enclose_the_cavity(enclosure: Enclosure) -> None:
    spec = enclosure.specification
    base = solid(enclosure.base).BoundingBox()
    lid = solid(enclosure.lid).BoundingBox()

    assert (base.xlen, base.ylen, base.zlen) == pytest.approx(
        (spec.inner_width_mm + 4, spec.inner_depth_mm + 4, spec.inner_height_mm + 2)
    )
    assert base.zmax == pytest.approx(cavity_top(enclosure))
    assert (lid.xlen, lid.ylen, lid.zlen) == pytest.approx((base.xlen, base.ylen, 2))
    assert lid.zmin == pytest.approx(base.zmax)


def test_corner_bosses_hold_open_insert_pockets_under_lid_holes(
    enclosure: Enclosure,
) -> None:
    base = solid(enclosure.base)
    lid = solid(enclosure.lid)
    top = cavity_top(enclosure)
    insert_radius = (enclosure.fastener.heat_set_insert_diameter_mm or 0) / 2
    wall_offset = insert_radius + CLEAR_DESIGN.boss_radial_wall_mm / 2

    assert len(enclosure.fastener_positions) == 4
    for x, y in enclosure.fastener_positions:
        assert not base.isInside(cq.Vector(x, y, top - 1.0))
        assert base.isInside(cq.Vector(x, y + wall_offset, top - 1.0))
        assert base.isInside(cq.Vector(x, y - wall_offset, top - 1.0))
        assert not lid.isInside(cq.Vector(x, y, top + 1.0))


def test_standoffs_rise_to_the_board_under_each_mounting_hole(
    enclosure: Enclosure,
) -> None:
    base = solid(enclosure.base)

    for x, y in centered_mounting_hole_positions(BOARD):
        probe = cq.Solid.makeBox(6, 6, 0.5, pnt=cq.Vector(x - 3, y - 3, -0.5))
        assert intersection_volume(base, probe) > 0


def test_lid_has_a_window_over_the_display(enclosure: Enclosure) -> None:
    lid = solid(enclosure.lid)
    top = cavity_top(enclosure)
    without_display = build_enclosure(
        pico2_oled_assembly(), board=BOARD, design=CLEAR_DESIGN
    )

    assert not lid.isInside(cq.Vector(0, 0, top + 1.0))
    assert solid(without_display.lid).isInside(cq.Vector(0, 0, top + 1.0))


def test_cable_opening_breaks_through_the_connector_wall(
    enclosure: Enclosure,
) -> None:
    spec = enclosure.specification
    assert spec.cable_edge == "negative_y"
    wall_y = spec.center_y_mm - spec.inner_depth_mm / 2 - 1.0
    z = spec.cable_bottom_z_mm + spec.cable_height_mm / 2

    assert not solid(enclosure.base).isInside(cq.Vector(0, wall_y, z))


def test_parts_are_clear_of_every_component(enclosure: Enclosure) -> None:
    for component in pico2_oled_assembly().components:
        geometry = component.transformed_geometry().val()
        assert isinstance(geometry, cq.Shape)

        for part in (enclosure.base, enclosure.lid):
            assert intersection_volume(solid(part), geometry) == 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"wall_mm": 0}, "wall_mm must be greater than zero"),
        ({"lid_mm": -1}, "lid_mm must be greater than zero"),
        ({"floor_mm": 0.5}, "floor_mm must exceed"),
        ({"internal_clearance_mm": -0.1}, "must not be negative"),
    ],
)
def test_design_rejects_invalid_settings(
    change: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        EnclosureDesign(**change).validate()  # type: ignore[arg-type]
