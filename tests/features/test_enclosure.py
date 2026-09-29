from __future__ import annotations

from functools import cache

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    board_component_identifiers,
    build_board_assembly,
    build_board_display_assembly,
)
from zcad_core.features import (
    Enclosure,
    EnclosureDesign,
    build_enclosure,
    centered_mounting_hole_positions,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import (
    get_adafruit_feather_rp2040,
    get_arduino_uno_r4_wifi,
    get_board,
    get_raspberry_pi_pico2,
    get_reference_oled_128x64,
    list_boards,
)

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()
DISPLAY_HEIGHT_MM = 8.0
CLEAR_DESIGN = EnclosureDesign(side_clearance_mm=5.0)


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


def board_assembly(
    board_identifier: str, placement: Placement | None = None
) -> DeviceAssembly:
    return build_board_assembly(
        board=get_board(board_identifier),
        board_placement=placement or Placement(),
        connector_access_clearance_mm=2.0,
    )


@cache
def board_only(board_identifier: str) -> tuple[DeviceAssembly, Enclosure]:
    """One default enclosure per board, shared by the tests that only read it."""
    assembly = board_assembly(board_identifier)

    return assembly, build_enclosure(assembly, board=get_board(board_identifier))


def test_refuses_bosses_that_would_hit_the_board() -> None:
    design = EnclosureDesign(side_clearance_mm=2.0)

    with pytest.raises(ValueError, match="base intersects 'board'"):
        build_enclosure(
            pico2_oled_assembly(), board=BOARD, display=DISPLAY, design=design
        )


def test_automatic_side_clearance_widens_one_axis_just_enough(
    enclosure: Enclosure,
) -> None:
    automatic = build_enclosure(pico2_oled_assembly(), board=BOARD, display=DISPLAY)

    def footprint(built: Enclosure) -> float:
        bounds = solid(built.base).BoundingBox()
        return bounds.xlen * bounds.ylen

    assert automatic.side_clearance_mm == (2.0, 10.0)
    assert footprint(automatic) < footprint(enclosure)


@pytest.mark.parametrize("board_identifier", list_boards())
def test_every_catalogued_board_gets_a_clear_enclosure(board_identifier: str) -> None:
    _, enclosure = board_only(board_identifier)

    assert len(enclosure.base.solids().vals()) == 1
    assert len(enclosure.lid.solids().vals()) == 1
    assert enclosure.board_support == (
        "cradle" if board_identifier == "SEEED_XIAO_ESP32_S3" else "standoffs"
    )


def test_irregular_hole_pattern_gets_a_standoff_under_each_hole() -> None:
    uno = get_arduino_uno_r4_wifi()
    _, enclosure = board_only(uno.identifier)
    base = solid(enclosure.base)

    for x, y in uno.mounting_hole_positions_mm:
        assert not base.isInside(cq.Vector(x, y, -0.5))
        # Material rings the hole, though a standoff beside header pins is
        # notched clear of them.
        probe = cq.Solid.makeBox(7, 7, 0.5, pnt=cq.Vector(x - 3.5, y - 3.5, -0.5))
        assert intersection_volume(base, probe) > 1.0


def test_supports_are_notched_clear_of_parts_under_the_board() -> None:
    assembly, enclosure = board_only(get_arduino_uno_r4_wifi().identifier)
    base = solid(enclosure.base)

    for identifier in board_component_identifiers(assembly):
        part = assembly.get(identifier).transformed_geometry().val()
        assert isinstance(part, cq.Shape)
        assert intersection_volume(base, part) == 0


def test_barrel_jack_gets_its_own_opening() -> None:
    assembly, enclosure = board_only(get_arduino_uno_r4_wifi().identifier)
    spec = enclosure.specification
    jack = next(
        component.transformed_geometry().val().BoundingBox()  # type: ignore[union-attr]
        for component in assembly.components
        if component.metadata.get("access_edge") == "negative_x"
        and component.identifier.startswith("board_top")
    )
    wall_x = spec.center_x_mm - spec.inner_width_mm / 2 - 1.0
    centre = cq.Vector(wall_x, (jack.ymin + jack.ymax) / 2, (jack.zmin + jack.zmax) / 2)

    assert not solid(enclosure.base).isInside(centre)


def test_cable_opening_follows_an_off_centre_connector() -> None:
    uno = get_arduino_uno_r4_wifi()
    _, enclosure = board_only(uno.identifier)
    spec = enclosure.specification
    assert spec.cable_edge == "negative_x"
    wall_x = spec.center_x_mm - spec.inner_width_mm / 2 - 1.0
    z = spec.cable_bottom_z_mm + spec.cable_height_mm / 2
    base = solid(enclosure.base)

    assert not base.isInside(cq.Vector(wall_x, uno.usb_connector.center_offset_mm, z))
    assert base.isInside(cq.Vector(wall_x, -uno.usb_connector.center_offset_mm, z))


def test_cable_opening_passes_a_moulded_plug(enclosure: Enclosure) -> None:
    spec = enclosure.specification
    wall_y = spec.center_y_mm - spec.inner_depth_mm / 2 - 1.0
    z = spec.cable_bottom_z_mm + spec.cable_height_mm / 2
    base = solid(enclosure.base)
    half_width = enclosure.design.cable_plug_width_mm / 2 - 0.1
    half_height = enclosure.design.cable_plug_height_mm / 2 - 0.1

    for dx, dz in (
        (-half_width, 0),
        (half_width, 0),
        (0, -half_height),
        (0, half_height),
    ):
        assert not base.isInside(cq.Vector(dx, wall_y, z + dz))


def test_refuses_a_cable_opening_that_would_cut_a_boss() -> None:
    feather = get_adafruit_feather_rp2040()

    with pytest.raises(ValueError, match="cut a corner boss"):
        build_enclosure(
            board_assembly(feather.identifier),
            board=feather,
            design=EnclosureDesign(side_clearance_mm=2.0),
        )


def test_refuses_a_rotated_board() -> None:
    with pytest.raises(ValueError, match="must not be rotated"):
        build_enclosure(
            board_assembly(BOARD.identifier, Placement(rotation_z_deg=90.0)),
            board=BOARD,
        )


def test_base_and_lid_enclose_the_cavity(enclosure: Enclosure) -> None:
    spec = enclosure.specification
    base = solid(enclosure.base).BoundingBox()
    lid = solid(enclosure.lid).BoundingBox()

    assert (base.xlen, base.ylen, base.zlen) == pytest.approx(
        (spec.inner_width_mm + 4, spec.inner_depth_mm + 4, spec.inner_height_mm + 2)
    )
    assert base.zmax == pytest.approx(cavity_top(enclosure))
    # The lid plate sits on the rim; its display retainer hangs below it.
    assert (lid.xlen, lid.ylen) == pytest.approx((base.xlen, base.ylen))
    assert lid.zmax == pytest.approx(base.zmax + CLEAR_DESIGN.lid_mm)


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


def test_bottom_and_top_clearances_set_standoff_height_and_lid_gap() -> None:
    design = EnclosureDesign(
        side_clearance_mm=5.0, bottom_clearance_mm=3.0, top_clearance_mm=1.0
    )
    enclosure = build_enclosure(
        pico2_oled_assembly(), board=BOARD, display=DISPLAY, design=design
    )
    display_top = DISPLAY_HEIGHT_MM + DISPLAY.module_depth_mm

    assert enclosure.specification.bottom_z_mm == pytest.approx(-3.0)
    assert cavity_top(enclosure) == pytest.approx(display_top + 1.0)


def test_refuses_a_board_resting_on_the_floor() -> None:
    design = EnclosureDesign(side_clearance_mm=5.0, bottom_clearance_mm=0.0)

    with pytest.raises(ValueError, match="above the enclosure floor"):
        build_enclosure(pico2_oled_assembly(), board=BOARD, design=design)


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
        ({"side_clearance_mm": -0.1}, "side_clearance_mm must not be negative"),
        ({"bottom_clearance_mm": -0.1}, "bottom_clearance_mm must not be"),
        ({"top_clearance_mm": -0.1}, "top_clearance_mm must not be negative"),
        ({"cable_plug_width_mm": -1}, "cable_plug_width_mm must not be negative"),
    ],
)
def test_design_rejects_invalid_settings(
    change: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        EnclosureDesign(**change).validate()  # type: ignore[arg-type]
