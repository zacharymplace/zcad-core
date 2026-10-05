"""A snap-in cradle that follows a board's outline."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import cast

import cadquery as cq
import pytest

from zcad_core.features import BoardCradleParameters, add_board_cradle
from zcad_core.hardware.electronics.board_outline import rounded_rectangle_points

WIDTH, LENGTH, THICKNESS = 30.0, 45.0, 1.6
BOTTOM = 2.0
TOP = BOTTOM + THICKNESS
HALF_W, HALF_L = WIDTH / 2, LENGTH / 2
ROUNDED = rounded_rectangle_points(WIDTH, LENGTH, 6.0)
# Rectangle with its +X +Y corner cut off diagonally.
CUT = ((-15.0, -22.5), (15.0, -22.5), (15.0, 14.5), (7.0, 22.5), (-15.0, 22.5))


def parameters(
    points: tuple[tuple[float, float], ...], edge: str
) -> BoardCradleParameters:
    return BoardCradleParameters(
        center_x_mm=0.0,
        center_y_mm=0.0,
        board_width_mm=WIDTH,
        board_depth_mm=LENGTH,
        board_bottom_z_mm=BOTTOM,
        board_thickness_mm=THICKNESS,
        base_z_mm=0.0,
        connector_edge=edge,  # type: ignore[arg-type]
        outline_points_mm=points,
    )


def cradle_of(p: BoardCradleParameters) -> cq.Solid:
    model = add_board_cradle(
        cq.Workplane("XY")
        .box(60, 70, 1, centered=(True, True, False))
        .translate((0, 0, -1)),
        parameters=p,
    )
    (only,) = model.solids().vals()
    assert isinstance(only, cq.Solid)

    return only


def board_prism(points: tuple[tuple[float, float], ...]) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .workplane(offset=BOTTOM)
        .polyline(list(points))
        .close()
        .extrude(THICKNESS)
    )


@pytest.fixture(scope="module")
def rounded() -> cq.Solid:
    return cradle_of(parameters(ROUNDED, "negative_y"))


@pytest.fixture(scope="module")
def cut() -> cq.Solid:
    return cradle_of(parameters(CUT, "positive_x"))


def test_the_board_fits_without_overlap(rounded: cq.Solid, cut: cq.Solid) -> None:
    for solid, points in ((rounded, ROUNDED), (cut, CUT)):
        overlap = solid.intersect(cast(cq.Shape, board_prism(points).val()))

        assert overlap.isNull() or overlap.Volume() < 1e-6


def test_the_ledge_follows_a_rounded_corner(rounded: cq.Solid) -> None:
    under = BOTTOM - 0.1

    # Outside the arc, a rectangular cradle would have a corner here.
    assert not rounded.isInside(cq.Vector(HALF_W + 0.5, HALF_L + 0.5, under))
    # Just outside the arc, the ledge's wall is.
    arc_centre = (HALF_W - 6.0, HALF_L - 6.0)
    outward = (6.0 + 0.9) * 0.70710678

    assert rounded.isInside(
        cq.Vector(arc_centre[0] + outward, arc_centre[1] + outward, under)
    )
    # And it holds the board's edge, but not the middle.
    assert rounded.isInside(cq.Vector(0, HALF_L - 0.5, under))
    assert not rounded.isInside(cq.Vector(0, 0, under))


def test_clips_hook_over_the_side_edges(rounded: cq.Solid) -> None:
    above = TOP + 0.1 + 0.5

    for side in (-1, 1):
        assert rounded.isInside(cq.Vector(side * (HALF_W - 0.25), 0, above))


def test_the_stop_is_behind_the_far_edge_and_the_connector_edge_is_open(
    rounded: cq.Solid,
) -> None:
    at_board = BOTTOM + THICKNESS / 2

    assert rounded.isInside(cq.Vector(0, HALF_L + 0.9, at_board))
    assert not rounded.isInside(cq.Vector(0, -(HALF_L + 0.9), at_board))


def test_a_cut_corner_is_followed_whichever_edge_the_connector_is_on(
    cut: cq.Solid,
) -> None:
    under = BOTTOM - 0.1
    # The bbox corner has no board: no ledge there.
    assert not cut.isInside(cq.Vector(14.5, 22.0, under))
    # Just outside the middle of the diagonal cut, there is.
    assert cut.isInside(
        cq.Vector(11 + 0.9 * 0.70710678, 18.5 + 0.9 * 0.70710678, under)
    )


def test_the_clips_and_stop_turn_with_the_connector_edge(cut: cq.Solid) -> None:
    above = TOP + 0.1 + 0.5
    at_board = BOTTOM + THICKNESS / 2

    # Connector on +X: open there, stop behind -X, clips on the +Y and -Y edges.
    assert not cut.isInside(cq.Vector(HALF_W + 0.9, 0, at_board))
    assert cut.isInside(cq.Vector(-(HALF_W + 0.9), 0, at_board))

    for side in (-1, 1):
        assert cut.isInside(cq.Vector(0, side * (HALF_L - 0.25), above))


def test_a_cradle_needs_a_board_long_enough_for_its_clips_and_stop() -> None:
    short = tuple((x, y * 12.0 / 22.5) for x, y in CUT)

    with pytest.raises(ValueError, match="too short"):
        replace(parameters(short, "negative_y"), board_depth_mm=12.0).validate()


def test_an_outline_needs_three_points() -> None:
    with pytest.raises(ValueError, match="three points"):
        parameters(((0.0, 0.0), (1.0, 1.0)), "negative_y").validate()


@pytest.mark.parametrize(
    ("points", "width", "depth", "fall_back"),
    [
        # A hexagon with a corner at each clip: the edge falls 1.73 mm away.
        (
            tuple(
                (15.0 * math.cos(math.radians(a)), 15.0 * math.sin(math.radians(a)))
                for a in range(0, 360, 60)
            ),
            30.0,
            30.0 * math.sin(math.radians(60)),
            "1.73",
        ),
        # A 16 mm round board: 0.59 mm, past the lip's 0.5 mm reach.
        (
            tuple(
                (
                    8.0 * math.cos(2 * math.pi * i / 64),
                    8.0 * math.sin(2 * math.pi * i / 64),
                )
                for i in range(64)
            ),
            16.0,
            16.0,
            "0.59",
        ),
    ],
)
def test_a_clip_on_an_edge_too_curved_for_its_lip_is_refused(
    points: tuple[tuple[float, float], ...], width: float, depth: float, fall_back: str
) -> None:
    # Before, these built, and the lips held 14% and 61% of a straight edge.
    p = replace(
        parameters(points, "negative_y"), board_width_mm=width, board_depth_mm=depth
    )

    with pytest.raises(ValueError, match=f"falls back {fall_back} mm"):
        cradle_of(p)
