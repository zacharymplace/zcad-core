"""Outline geometry: plain polygons about a board's centre."""

from __future__ import annotations

import math
from typing import Any

import pytest

from zcad_core.hardware.electronics import board_outline as outline

SQUARE = ((-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0))
# A square with a notch in its top edge.
NOTCHED = (
    (-5.0, -5.0),
    (5.0, -5.0),
    (5.0, 5.0),
    (1.0, 5.0),
    (1.0, 1.0),
    (-1.0, 1.0),
    (-1.0, 5.0),
    (-5.0, 5.0),
)


def test_a_rounded_rectangle_fills_its_bounding_rectangle_less_its_corners() -> None:
    points = outline.rounded_rectangle_points(30, 40, 4)
    x0, x1, y0, y1 = outline.bounding_box(points)

    assert (x1 - x0, y1 - y0) == pytest.approx((30, 40), abs=1e-5)
    assert (x0 + x1, y0 + y1) == pytest.approx((0, 0), abs=1e-5)
    assert outline.signed_area(points) == pytest.approx(
        30 * 40 - (4 - math.pi) * 16, rel=2e-3
    )
    assert outline.is_simple(points)
    assert outline.signed_area(points) > 0


def test_area_is_signed_by_winding() -> None:
    assert outline.signed_area(SQUARE) == 100
    assert outline.signed_area(SQUARE[::-1]) == -100
    assert outline.signed_area(outline.counter_clockwise(SQUARE[::-1])) == 100


def test_a_bow_tie_is_not_simple() -> None:
    assert not outline.is_simple(((0, 0), (4, 4), (4, 0), (0, 4)))
    assert outline.is_simple(NOTCHED)


@pytest.mark.parametrize(
    "points",
    [
        # Two lobes joined at one vertex, with opposite winding.
        ((-15, -22.5), (-15, 22.5), (0, 0), (15, 5), (15, -5), (0, 0)),
        # A vertex resting on another edge.
        ((0, 0), (10, 0), (10, 10), (5, 0), (0, 10)),
        # Two edges that are not neighbours lying along each other.
        ((0, 0), (10, 0), (10, 5), (6, 5), (6, 0.0), (4, 0.0), (4, 5), (0, 5)),
        # An edge that folds back along its neighbour, a spike.
        ((0, 0), (10, 0), (10, 10), (10, 5), (0, 10)),
        # A vertex given twice in a row.
        ((0, 0), (10, 0), (10, 0), (10, 10), (0, 10)),
    ],
)
def test_a_pinched_or_touching_loop_is_not_simple(points: tuple[Any, ...]) -> None:
    assert not outline.is_simple(points)


def test_points_in_a_straight_line_along_an_edge_are_still_simple() -> None:
    assert outline.is_simple(((0, 0), (5, 0), (10, 0), (10, 10), (0, 10)))


def test_containment_and_depth() -> None:
    assert outline.contains(NOTCHED, (0, -3))
    assert not outline.contains(NOTCHED, (0, 3))
    assert outline.depth_inside(SQUARE, (0, 0)) == pytest.approx(5)
    assert outline.depth_inside(SQUARE, (7, 0)) == pytest.approx(-2)
    # The bottom edge is 2 mm away; the notch's floor is 4 mm away.
    assert outline.depth_inside(NOTCHED, (0, -3)) == pytest.approx(2)
    assert outline.depth_inside(NOTCHED, (0, 0)) == pytest.approx(1)


def test_a_chord_spans_the_outline_at_a_height() -> None:
    assert outline.chord(SQUARE, 0) == (-5, 5)
    # The leftmost and rightmost crossings: the notch lies between them.
    assert outline.chord(NOTCHED, 3) == (-5, 5)
    assert outline.chord(SQUARE, 9) is None


def test_rotating_turns_points_counter_clockwise() -> None:
    (x, y) = outline.rotated(((1.0, 0.0),), 90)[0]

    assert (x, y) == pytest.approx((0, 1), abs=1e-9)
