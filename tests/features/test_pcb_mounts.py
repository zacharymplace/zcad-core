"""Tests for reusable PCB mounting features."""

import cadquery as cq
import pytest

from zcad_core.features import (
    PcbStandoffParameters,
    add_board_standoffs,
    add_pcb_standoff,
    centered_mounting_hole_positions,
)
from zcad_core.hardware import (
    get_raspberry_pi_pico2,
)


def test_standoff_parameters_derive_from_board() -> None:
    board = get_raspberry_pi_pico2()

    parameters = PcbStandoffParameters.from_board(
        board=board,
        x=4.0,
        y=-7.0,
        base_height_mm=2.0,
    )

    assert parameters.x == 4.0
    assert parameters.y == -7.0
    assert parameters.base_height_mm == 2.0
    assert parameters.standoff_height_mm == 3.0
    assert parameters.hole_diameter_mm == pytest.approx(2.6)
    assert parameters.outer_diameter_mm == pytest.approx(5.6)


def test_centered_mounting_hole_positions() -> None:
    board = get_raspberry_pi_pico2()

    assert centered_mounting_hole_positions(board) == (
        (-5.7, -23.5),
        (5.7, -23.5),
        (-5.7, 23.5),
        (5.7, 23.5),
    )


def test_add_pcb_standoff_adds_geometry() -> None:
    board = get_raspberry_pi_pico2()

    base = cq.Workplane("XY").box(
        20.0,
        20.0,
        2.0,
        centered=(True, True, False),
    )

    parameters = PcbStandoffParameters.from_board(
        board=board,
        base_height_mm=2.0,
    )

    result = add_pcb_standoff(
        base,
        parameters=parameters,
    )

    assert result.val().Volume() > base.val().Volume()


def test_add_board_standoffs_adds_four_mounts() -> None:
    board = get_raspberry_pi_pico2()

    base = cq.Workplane("XY").box(
        30.0,
        60.0,
        2.0,
        centered=(True, True, False),
    )

    result = add_board_standoffs(
        base,
        board=board,
        base_height_mm=2.0,
    )

    assert result.val().Volume() > base.val().Volume()


def test_standoff_rejects_invalid_wall() -> None:
    board = get_raspberry_pi_pico2()

    with pytest.raises(
        ValueError,
        match="radial_wall_mm",
    ):
        PcbStandoffParameters.from_board(
            board=board,
            base_height_mm=2.0,
            radial_wall_mm=0.0,
        )


def test_standoff_validation_rejects_thin_body() -> None:
    invalid = PcbStandoffParameters(
        x=0.0,
        y=0.0,
        base_height_mm=2.0,
        standoff_height_mm=3.0,
        outer_diameter_mm=2.5,
        hole_diameter_mm=2.6,
    )

    with pytest.raises(
        ValueError,
        match="outer diameter",
    ):
        invalid.validate()
