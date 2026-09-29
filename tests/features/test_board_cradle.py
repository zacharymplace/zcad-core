"""The snap-in cradle for boards without mounting holes."""

from __future__ import annotations

from dataclasses import replace

import cadquery as cq
import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.features import (
    BoardCradleParameters,
    Enclosure,
    add_board_cradle,
    build_enclosure,
)
from zcad_core.hardware import get_seeed_xiao_esp32s3

XIAO = get_seeed_xiao_esp32s3()
BOARD_BOTTOM_MM = 2.0
PARAMETERS = BoardCradleParameters(
    center_x_mm=0.0,
    center_y_mm=0.0,
    board_width_mm=XIAO.board_width_mm,
    board_depth_mm=XIAO.board_length_mm,
    board_bottom_z_mm=BOARD_BOTTOM_MM,
    board_thickness_mm=XIAO.board_thickness_mm,
    base_z_mm=0.0,
    connector_edge="positive_y",
)
HALF_W = XIAO.board_width_mm / 2
HALF_D = XIAO.board_length_mm / 2
BOARD_TOP_MM = BOARD_BOTTOM_MM + XIAO.board_thickness_mm


@pytest.fixture(scope="module")
def cradle() -> cq.Solid:
    model = add_board_cradle(
        cq.Workplane("XY")
        .box(40, 40, 1, centered=(True, True, False))
        .translate((0, 0, -1)),
        parameters=PARAMETERS,
    )
    (only,) = model.solids().vals()
    assert isinstance(only, cq.Solid)

    return only


def board() -> cq.Solid:
    return cq.Solid.makeBox(
        XIAO.board_width_mm,
        XIAO.board_length_mm,
        XIAO.board_thickness_mm,
        pnt=cq.Vector(-HALF_W, -HALF_D, BOARD_BOTTOM_MM),
    )


def test_board_fits_without_overlap(cradle: cq.Solid) -> None:
    overlap = cradle.intersect(board())

    assert overlap.isNull() or overlap.Volume() < 1e-6


def test_ledge_supports_the_board_edges(cradle: cq.Solid) -> None:
    just_under = BOARD_BOTTOM_MM - 0.1

    # Along the connector edge (open above) and the back edge (stop above).
    assert cradle.isInside(cq.Vector(0, -HALF_D + 0.5, just_under))
    assert cradle.isInside(cq.Vector(0, HALF_D - 0.5, just_under))
    # Not under the middle of the board.
    assert not cradle.isInside(cq.Vector(0, 0, just_under))


def test_clips_hook_over_the_side_edges(cradle: cq.Solid) -> None:
    above_board = BOARD_TOP_MM + PARAMETERS.clip_gap_mm + 0.5
    lip_reach = PARAMETERS.clip_overhang_mm - PARAMETERS.clearance_mm

    for side in (-1, 1):
        assert cradle.isInside(
            cq.Vector(side * (HALF_W - lip_reach / 2), 0, above_board)
        )
        # The ledge is slotted beside the clip so the clip can flex.
        slot_y = PARAMETERS.clip_width_mm / 2 + PARAMETERS.clip_slot_mm / 2
        assert not cradle.isInside(cq.Vector(side * (HALF_W - 0.5), slot_y, 1.0))


def test_back_edge_has_a_stop_and_connector_edge_is_open(cradle: cq.Solid) -> None:
    at_board = BOARD_BOTTOM_MM + XIAO.board_thickness_mm / 2
    behind = HALF_D + PARAMETERS.clearance_mm + PARAMETERS.wall_mm / 2

    # The connector is on positive Y, so the stop is on negative Y.
    assert cradle.isInside(cq.Vector(0, -behind, at_board))
    assert not cradle.isInside(cq.Vector(0, behind, at_board))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"ledge_mm": 0}, "ledge_mm must be greater than zero"),
        ({"clearance_mm": -0.1}, "clearance_mm must not be negative"),
        ({"base_z_mm": 5.0}, "above the cradle base"),
        ({"clip_overhang_mm": 0.2}, "must exceed clearance_mm"),
        ({"ledge_mm": 9.0}, "too wide for the board"),
        ({"clip_width_mm": 20.0}, "too wide for the board edge"),
    ],
)
def test_parameters_reject_invalid_geometry(
    change: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(PARAMETERS, **change).validate()  # type: ignore[arg-type]


def test_enclosure_seats_a_hole_less_board_in_a_cradle() -> None:
    assembly = build_board_assembly(
        board=XIAO, board_placement=Placement(), connector_access_clearance_mm=2.0
    )

    enclosure: Enclosure = build_enclosure(assembly, board=XIAO)

    assert enclosure.board_support == "cradle"
    (base,) = enclosure.base.solids().vals()
    assert isinstance(base, cq.Solid)
    assert base.isInside(cq.Vector(0, -HALF_D + 0.5, -0.1))
