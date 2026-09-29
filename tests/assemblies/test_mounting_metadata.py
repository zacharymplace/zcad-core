"""Tests for assembly-aware PCB mounting metadata."""

from dataclasses import dataclass, field

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    AssemblyComponent,
    DeviceAssembly,
    Placement,
    RectangularBoardSpec,
    assembly_mounting_hole_positions,
    build_board_display_assembly,
    rectangular_board_mounting_metadata,
)
from zcad_core.hardware import (
    RectangularConnectorSpec,
    get_arduino_uno_r4_wifi,
    get_raspberry_pi_pico2,
    get_seeed_xiao_esp32s3,
)


def _connector() -> RectangularConnectorSpec:
    return RectangularConnectorSpec(
        identifier="TEST_USB",
        width_mm=8.0,
        depth_mm=6.0,
        height_mm=3.0,
        board_edge="negative_y",
    )


@dataclass(frozen=True)
class StubDisplay:
    identifier: str = "TEST_DISPLAY"
    module_width_mm: float = 28.0
    module_height_mm: float = 20.0
    module_depth_mm: float = 4.0
    mount_style: str = "bezel"


@dataclass(frozen=True)
class PartialMountingBoard:
    identifier: str = "PARTIAL_BOARD"
    board_width_mm: float = 20.0
    board_length_mm: float = 40.0
    board_thickness_mm: float = 1.0
    usb_connector: RectangularConnectorSpec = field(default_factory=_connector)

    mounting_hole_diameter_mm: float = 2.0


def _assembly_for_board(
    board: RectangularBoardSpec,
    *,
    placement: Placement | None = None,
) -> DeviceAssembly:
    return build_board_display_assembly(
        board=board,
        display=StubDisplay(),
        board_placement=(placement if placement is not None else Placement()),
        display_placement=Placement(
            z_mm=8.0,
        ),
    )


def test_pico_exposes_structured_mounting_metadata() -> None:
    board = get_raspberry_pi_pico2()
    assembly = _assembly_for_board(board)

    mounting = assembly.get("board").metadata["mounting"]

    assert mounting == {
        "pattern": "rectangular_4_hole",
        "hole_diameter_mm": 2.1,
        "spacing_x_mm": 11.4,
        "spacing_y_mm": 47.0,
        "recommended_standoff_height_mm": 3.0,
        "recommended_clearance_mm": 0.5,
    }


def test_xiao_omits_unverified_mounting_metadata() -> None:
    board = get_seeed_xiao_esp32s3()
    assembly = _assembly_for_board(board)

    assert "mounting" not in assembly.get("board").metadata

    assert assembly_mounting_hole_positions(assembly.get("board")) == ()


def test_mounting_positions_follow_translation() -> None:
    board = get_raspberry_pi_pico2()
    assembly = _assembly_for_board(
        board,
        placement=Placement(
            x_mm=10.0,
            y_mm=-5.0,
            z_mm=3.0,
        ),
    )

    positions = assembly_mounting_hole_positions(assembly.get("board"))

    expected = (
        (4.3, -28.5, 3.0),
        (15.7, -28.5, 3.0),
        (4.3, 18.5, 3.0),
        (15.7, 18.5, 3.0),
    )

    assert len(positions) == len(expected)

    for actual, target in zip(
        positions,
        expected,
        strict=True,
    ):
        assert actual == pytest.approx(target)


def test_mounting_positions_follow_z_rotation() -> None:
    component = AssemblyComponent(
        identifier="board",
        geometry=cq.Workplane("XY").box(
            20.0,
            40.0,
            1.0,
            centered=(True, True, False),
        ),
        placement=Placement(
            x_mm=2.0,
            y_mm=3.0,
            z_mm=4.0,
            rotation_z_deg=90.0,
        ),
        metadata={
            "mounting": {
                "pattern": "rectangular_4_hole",
                "hole_diameter_mm": 2.0,
                "spacing_x_mm": 10.0,
                "spacing_y_mm": 20.0,
                "recommended_standoff_height_mm": 3.0,
                "recommended_clearance_mm": 0.5,
            }
        },
    )

    positions = assembly_mounting_hole_positions(component)

    expected = (
        (12.0, -2.0, 4.0),
        (12.0, 8.0, 4.0),
        (-8.0, -2.0, 4.0),
        (-8.0, 8.0, 4.0),
    )

    assert len(positions) == len(expected)

    for actual, target in zip(
        positions,
        expected,
        strict=True,
    ):
        assert actual == pytest.approx(target)


def test_partial_mounting_metadata_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="must be complete",
    ):
        rectangular_board_mounting_metadata(PartialMountingBoard())


def test_unsupported_mounting_pattern_is_rejected() -> None:
    component = AssemblyComponent(
        identifier="board",
        geometry=cq.Workplane("XY").box(
            10.0,
            10.0,
            1.0,
            centered=(True, True, False),
        ),
        metadata={
            "mounting": {
                "pattern": "arbitrary",
            }
        },
    )

    with pytest.raises(
        ValueError,
        match="unsupported mounting pattern",
    ):
        assembly_mounting_hole_positions(component)


def test_irregular_hole_pattern_has_no_rectangular_metadata() -> None:
    assert rectangular_board_mounting_metadata(get_arduino_uno_r4_wifi()) is None
