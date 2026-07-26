from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.geometry.edge_outline import (
    EdgeOutlineAnalyzer,
)
from zcad_core.geometry.types import (
    BoardEdge,
    EdgeSegment,
)


def rectangular_board() -> cq.Shape:
    shape = cq.Workplane("XY").box(40.0, 30.0, 1.6).val()

    assert isinstance(shape, cq.Shape)
    return shape


def board_with_positive_x_notch() -> cq.Shape:
    board = rectangular_board()
    cutter = cq.Workplane("XY").box(4.0, 8.0, 4.0).translate((19.0, 0.0, 0.0)).val()

    assert isinstance(cutter, cq.Shape)
    return board.cut(cutter)


def board_with_positive_x_edge_hole() -> cq.Shape:
    board = rectangular_board()
    cutter = (
        cq.Workplane("XY").center(18.5, 0.0).circle(1.5).extrude(4.0, both=True).val()
    )

    assert isinstance(cutter, cq.Shape)
    return board.cut(cutter)


def test_rectangle_segment_is_usable() -> None:
    analyzer = EdgeOutlineAnalyzer(
        rectangular_board(),
        sample_resolution_mm=0.25,
    )

    result = analyzer.validate_segment(
        EdgeSegment(
            edge=BoardEdge.POSITIVE_X,
            start_mm=-5.0,
            end_mm=5.0,
        )
    )

    assert result.usable
    assert result.continuous
    assert result.blocked_spans == ()
    assert result.minimum_material_ratio == pytest.approx(1.0)


def test_notch_blocks_crossing_segment() -> None:
    analyzer = EdgeOutlineAnalyzer(
        board_with_positive_x_notch(),
        sample_resolution_mm=0.25,
    )

    result = analyzer.validate_segment(
        EdgeSegment(
            edge=BoardEdge.POSITIVE_X,
            start_mm=-5.0,
            end_mm=5.0,
        )
    )

    assert not result.usable
    assert not result.continuous
    assert result.blocked_spans
    assert result.minimum_material_ratio < 1.0


def test_edge_hole_blocks_engagement_band() -> None:
    analyzer = EdgeOutlineAnalyzer(
        board_with_positive_x_edge_hole(),
        sample_resolution_mm=0.20,
    )

    result = analyzer.validate_segment(
        EdgeSegment(
            edge=BoardEdge.POSITIVE_X,
            start_mm=-4.0,
            end_mm=4.0,
        )
    )

    assert not result.usable
    assert result.blocked_spans


def test_internal_hole_outside_band_is_ignored() -> None:
    cutter = cq.Workplane("XY").circle(2.0).extrude(4.0, both=True).val()

    assert isinstance(cutter, cq.Shape)

    analyzer = EdgeOutlineAnalyzer(
        rectangular_board().cut(cutter),
        engagement_depth_mm=2.5,
        sample_resolution_mm=0.25,
    )

    result = analyzer.validate_segment(
        EdgeSegment(
            edge=BoardEdge.POSITIVE_X,
            start_mm=-5.0,
            end_mm=5.0,
        )
    )

    assert result.usable


def test_candidates_split_around_notch() -> None:
    analyzer = EdgeOutlineAnalyzer(
        board_with_positive_x_notch(),
        sample_resolution_mm=0.25,
    )

    candidates = analyzer.candidate_segments(
        BoardEdge.POSITIVE_X,
        minimum_length_mm=6.0,
    )

    assert len(candidates) == 2
    assert candidates[0].end_mm <= -3.5
    assert candidates[1].start_mm >= 3.5


def test_segment_outside_limits_fails() -> None:
    analyzer = EdgeOutlineAnalyzer(rectangular_board())

    with pytest.raises(
        ValueError,
        match="outside",
    ):
        analyzer.validate_segment(
            EdgeSegment(
                edge=BoardEdge.POSITIVE_X,
                start_mm=-16.0,
                end_mm=0.0,
            )
        )


@pytest.mark.parametrize(
    "edge",
    tuple(BoardEdge),
)
def test_rectangle_has_full_candidate_on_each_edge(
    edge: BoardEdge,
) -> None:
    analyzer = EdgeOutlineAnalyzer(
        rectangular_board(),
        sample_resolution_mm=0.5,
    )

    candidates = analyzer.candidate_segments(
        edge,
        minimum_length_mm=6.0,
    )

    assert len(candidates) == 1

    lower, upper = analyzer.edge_limits(edge)

    assert candidates[0].start_mm == pytest.approx(lower)
    assert candidates[0].end_mm == pytest.approx(upper)
