"""Generated captures are single grounded bodies that keep board clearance."""

from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.types import BoardEdge
from zcad_core.retention import (
    BoardCorner,
    CornerCaptureLocation,
    CornerCaptureParameters,
    EdgeCaptureLocation,
    EdgeCaptureParameters,
    SyntheticCornerCaptureBackend,
    SyntheticEdgeCaptureBackend,
)

BOARD_X_MM = 40.0
BOARD_Y_MM = 20.0
THICKNESS_MM = 1.6
CLEARANCE_MM = 0.25
SHAPE = {
    "arm_width_mm": 3.0,
    "engagement_depth_mm": 2.0,
    "board_clearance_mm": CLEARANCE_MM,
    "vertical_overlap_mm": 0.6,
    "minimum_wall_mm": 1.2,
}


def corner_geometry(bottom: float = 0.0) -> cq.Workplane:
    return SyntheticCornerCaptureBackend().build_geometry(
        CornerCaptureParameters(
            board_thickness_mm=THICKNESS_MM,
            locations=(
                CornerCaptureLocation(
                    corner=BoardCorner.NEGATIVE_X_NEGATIVE_Y, x_mm=0.0, y_mm=0.0
                ),
                CornerCaptureLocation(
                    corner=BoardCorner.POSITIVE_X_POSITIVE_Y,
                    x_mm=BOARD_X_MM,
                    y_mm=BOARD_Y_MM,
                ),
            ),
            **SHAPE,
            board_bottom_z_mm=bottom,
        )
    )


def edge_geometry(bottom: float = 0.0) -> cq.Workplane:
    return SyntheticEdgeCaptureBackend().build_geometry(
        EdgeCaptureParameters(
            board_thickness_mm=THICKNESS_MM,
            locations=(
                EdgeCaptureLocation(
                    edge=BoardEdge.NEGATIVE_Y, position_mm=8.0, edge_coordinate_mm=0.0
                ),
                EdgeCaptureLocation(
                    edge=BoardEdge.POSITIVE_X,
                    position_mm=10.0,
                    edge_coordinate_mm=BOARD_X_MM,
                ),
            ),
            **SHAPE,
            board_bottom_z_mm=bottom,
        )
    )


BOTTOMS = pytest.mark.parametrize("bottom", [0.0, -1.6])


@BOTTOMS
@pytest.mark.parametrize("build", [corner_geometry, edge_geometry])
def test_each_capture_is_one_grounded_body(build, bottom: float) -> None:  # type: ignore[no-untyped-def]
    solids = build(bottom).solids().vals()

    assert len(solids) == 2
    for solid in solids:
        assert solid.BoundingBox().zmin == pytest.approx(bottom)


@BOTTOMS
@pytest.mark.parametrize("build", [corner_geometry, edge_geometry])
def test_captures_keep_board_clearance(build, bottom: float) -> None:  # type: ignore[no-untyped-def]
    # The board plus its clearance envelope, stopping just short of the
    # clearance so touching the envelope boundary is allowed.
    margin = CLEARANCE_MM - 1e-3
    envelope = (
        cq.Workplane("XY")
        .box(BOARD_X_MM + 2 * margin, BOARD_Y_MM + 2 * margin, THICKNESS_MM + margin)
        .translate(
            (BOARD_X_MM / 2, BOARD_Y_MM / 2, bottom + (THICKNESS_MM + margin) / 2)
        )
    )

    intersection = build(bottom).intersect(envelope)

    assert (
        intersection.solids().size() == 0
        or workplane_shape(intersection).Volume() < 1e-9
    )


@BOTTOMS
@pytest.mark.parametrize("build", [corner_geometry, edge_geometry])
def test_captures_still_reach_over_board(build, bottom: float) -> None:  # type: ignore[no-untyped-def]
    above_board = (
        cq.Workplane("XY")
        .box(BOARD_X_MM, BOARD_Y_MM, 10.0)
        .translate((BOARD_X_MM / 2, BOARD_Y_MM / 2, bottom + THICKNESS_MM + 5.0))
    )

    assert workplane_shape(build(bottom).intersect(above_board)).Volume() > 0
