from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.geometry.edge_outline import (
    EdgeOutlineAnalyzer,
)
from zcad_core.geometry.types import (
    BoardEdge,
    EdgeSegment,
)

STEP_PATH = (
    Path(__file__).resolve().parents[2]
    / "evidence"
    / "arduino-uno-r4-wifi"
    / "step"
    / "UNO_R4_WIFI.step"
)

PCB_SOLID_INDEX = 1
MINIMUM_CLIP_WIDTH_MM = 6.0
EPSILON_MM = 1e-6

NEGATIVE_Y_CLEARANCE = EdgeSegment(
    edge=BoardEdge.NEGATIVE_Y,
    start_mm=0.0,
    end_mm=16.010,
)

POSITIVE_X_LOWER_CLEARANCE = EdgeSegment(
    edge=BoardEdge.POSITIVE_X,
    start_mm=0.0,
    end_mm=10.846,
)

POSITIVE_X_UPPER_CLEARANCE = EdgeSegment(
    edge=BoardEdge.POSITIVE_X,
    start_mm=32.250,
    end_mm=53.340,
)


@pytest.fixture(scope="module")
def uno_r4_pcb() -> cq.Shape:
    if not STEP_PATH.is_file():
        pytest.skip(f"UNO R4 STEP evidence is unavailable: {STEP_PATH}")

    shape = cq.importers.importStep(str(STEP_PATH)).val()

    if shape is None:
        raise RuntimeError("UNO R4 STEP model contains no shape")

    solids = tuple(shape.Solids())

    if len(solids) < PCB_SOLID_INDEX:
        raise RuntimeError("UNO R4 STEP model does not contain the expected PCB solid")

    pcb = solids[PCB_SOLID_INDEX - 1]
    bounds = pcb.BoundingBox()

    assert bounds.xlen == pytest.approx(
        68.58,
        abs=0.02,
    )
    assert bounds.ylen == pytest.approx(
        53.34,
        abs=0.02,
    )
    assert bounds.zlen == pytest.approx(
        1.606,
        abs=0.02,
    )

    return pcb


@pytest.fixture(scope="module")
def analyzer(
    uno_r4_pcb: cq.Shape,
) -> EdgeOutlineAnalyzer:
    return EdgeOutlineAnalyzer(
        uno_r4_pcb,
        engagement_depth_mm=2.5,
        sample_resolution_mm=0.10,
        required_material_ratio=0.995,
    )


def intersect_segments(
    first: EdgeSegment,
    second: EdgeSegment,
) -> EdgeSegment | None:
    if first.edge is not second.edge:
        raise ValueError("Cannot intersect segments from different edges")

    start_mm = max(
        first.start_mm,
        second.start_mm,
    )
    end_mm = min(
        first.end_mm,
        second.end_mm,
    )

    if end_mm <= start_mm + EPSILON_MM:
        return None

    return EdgeSegment(
        edge=first.edge,
        start_mm=start_mm,
        end_mm=end_mm,
    )


def usable_intersections(
    *,
    analyzer: EdgeOutlineAnalyzer,
    clearance_segment: EdgeSegment,
) -> tuple[EdgeSegment, ...]:
    outline_segments = analyzer.candidate_segments(
        clearance_segment.edge,
        minimum_length_mm=0.10,
    )

    intersections: list[EdgeSegment] = []

    for outline_segment in outline_segments:
        intersection = intersect_segments(
            clearance_segment,
            outline_segment,
        )

        if intersection is None:
            continue

        if intersection.length_mm + EPSILON_MM >= MINIMUM_CLIP_WIDTH_MM:
            intersections.append(intersection)

    return tuple(intersections)


def test_negative_y_clearance_retains_usable_outline(
    analyzer: EdgeOutlineAnalyzer,
) -> None:
    intersections = usable_intersections(
        analyzer=analyzer,
        clearance_segment=NEGATIVE_Y_CLEARANCE,
    )

    assert len(intersections) == 1

    result = analyzer.validate_segment(intersections[0])

    assert intersections[0].length_mm >= (MINIMUM_CLIP_WIDTH_MM)
    assert result.usable
    assert result.continuous
    assert result.blocked_spans == ()


@pytest.mark.parametrize(
    "clearance_segment",
    (
        POSITIVE_X_LOWER_CLEARANCE,
        POSITIVE_X_UPPER_CLEARANCE,
    ),
)
def test_positive_x_clearance_is_rejected_by_outline(
    analyzer: EdgeOutlineAnalyzer,
    clearance_segment: EdgeSegment,
) -> None:
    intersections = usable_intersections(
        analyzer=analyzer,
        clearance_segment=clearance_segment,
    )

    assert intersections == ()


def test_uno_has_only_one_combined_clip_region(
    analyzer: EdgeOutlineAnalyzer,
) -> None:
    clearance_segments = (
        NEGATIVE_Y_CLEARANCE,
        POSITIVE_X_LOWER_CLEARANCE,
        POSITIVE_X_UPPER_CLEARANCE,
    )

    combined = tuple(
        segment
        for clearance in clearance_segments
        for segment in usable_intersections(
            analyzer=analyzer,
            clearance_segment=clearance,
        )
    )

    assert len(combined) == 1
    assert combined[0].edge is BoardEdge.NEGATIVE_Y


@pytest.mark.parametrize(
    "edge",
    tuple(BoardEdge),
)
def test_outline_candidates_are_self_consistent(
    analyzer: EdgeOutlineAnalyzer,
    edge: BoardEdge,
) -> None:
    candidates = analyzer.candidate_segments(
        edge,
        minimum_length_mm=MINIMUM_CLIP_WIDTH_MM,
    )

    for candidate in candidates:
        result = analyzer.validate_segment(candidate)

        assert result.usable, result
        assert result.continuous
        assert result.blocked_spans == ()
