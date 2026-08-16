from __future__ import annotations

import pytest

from zcad_core.geometry.types import BoardEdge
from zcad_core.retention.edge_capture import (
    EdgeCaptureLocation,
    EdgeCaptureParameters,
    EdgeCapturePolicy,
    as_edge_capture_parameters,
    derive_edge_capture_parameters,
)


def spaced_locations() -> tuple[EdgeCaptureLocation, ...]:
    return (
        EdgeCaptureLocation(
            edge=BoardEdge.NEGATIVE_Y,
            position_mm=4.0,
            edge_coordinate_mm=0.0,
        ),
        EdgeCaptureLocation(
            edge=BoardEdge.NEGATIVE_Y,
            position_mm=16.0,
            edge_coordinate_mm=0.0,
        ),
    )


def test_default_policy_is_valid() -> None:
    policy = EdgeCapturePolicy()

    assert policy.arm_width_mm == pytest.approx(5.0)
    assert policy.engagement_depth_mm == pytest.approx(2.5)
    assert policy.board_clearance_mm == pytest.approx(0.25)
    assert policy.vertical_overlap_mm == pytest.approx(0.6)


@pytest.mark.parametrize(
    "field",
    (
        "arm_width_mm",
        "engagement_depth_mm",
        "vertical_overlap_mm",
        "minimum_wall_mm",
    ),
)
def test_positive_policy_dimensions_are_required(
    field: str,
) -> None:
    values = {
        "arm_width_mm": 6.0,
        "engagement_depth_mm": 2.5,
        "board_clearance_mm": 0.25,
        "vertical_overlap_mm": 0.6,
        "minimum_wall_mm": 1.2,
    }
    values[field] = 0.0

    with pytest.raises(
        ValueError,
        match=field,
    ):
        EdgeCapturePolicy(**values)


def test_clearance_cannot_be_negative() -> None:
    with pytest.raises(
        ValueError,
        match="board_clearance_mm",
    ):
        EdgeCapturePolicy(board_clearance_mm=-0.01)


def test_derivation_preserves_validated_policy() -> None:
    policy = EdgeCapturePolicy(
        arm_width_mm=5.0,
        engagement_depth_mm=2.2,
        board_clearance_mm=0.3,
        vertical_overlap_mm=0.7,
        minimum_wall_mm=1.4,
    )

    result = derive_edge_capture_parameters(
        board_thickness_mm=1.6,
        locations=spaced_locations(),
        policy=policy,
    )

    assert result.board_thickness_mm == pytest.approx(1.6)
    assert result.locations == spaced_locations()
    assert result.arm_width_mm == pytest.approx(5.0)
    assert result.engagement_depth_mm == pytest.approx(2.2)
    assert result.board_clearance_mm == pytest.approx(0.3)
    assert result.vertical_overlap_mm == pytest.approx(0.7)
    assert result.minimum_wall_mm == pytest.approx(1.4)


def test_one_location_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="at least two",
    ):
        EdgeCaptureParameters(
            board_thickness_mm=1.6,
            locations=(spaced_locations()[0],),
            arm_width_mm=6.0,
            engagement_depth_mm=2.5,
            board_clearance_mm=0.25,
            vertical_overlap_mm=0.6,
            minimum_wall_mm=1.2,
        )


def test_duplicate_location_is_rejected() -> None:
    location = spaced_locations()[0]

    with pytest.raises(
        ValueError,
        match="unique",
    ):
        derive_edge_capture_parameters(
            board_thickness_mm=1.6,
            locations=(location, location),
            policy=EdgeCapturePolicy(),
        )


def test_overlapping_same_edge_locations_are_rejected() -> None:
    locations = (
        EdgeCaptureLocation(
            edge=BoardEdge.NEGATIVE_Y,
            position_mm=4.0,
            edge_coordinate_mm=0.0,
        ),
        EdgeCaptureLocation(
            edge=BoardEdge.NEGATIVE_Y,
            position_mm=4.0 + 1e-9,
            edge_coordinate_mm=0.0,
        ),
    )

    with pytest.raises(
        ValueError,
        match="must not overlap",
    ):
        derive_edge_capture_parameters(
            board_thickness_mm=1.6,
            locations=locations,
            policy=EdgeCapturePolicy(),
        )


def test_locations_on_different_edges_are_accepted() -> None:
    locations = (
        EdgeCaptureLocation(
            edge=BoardEdge.NEGATIVE_Y,
            position_mm=4.0,
            edge_coordinate_mm=0.0,
        ),
        EdgeCaptureLocation(
            edge=BoardEdge.POSITIVE_X,
            position_mm=10.0,
            edge_coordinate_mm=20.0,
        ),
    )

    result = derive_edge_capture_parameters(
        board_thickness_mm=1.6,
        locations=locations,
        policy=EdgeCapturePolicy(),
    )

    assert result.locations == locations


def test_as_edge_capture_parameters_rejects_wrong_type() -> None:
    with pytest.raises(
        TypeError,
        match="EdgeCaptureParameters",
    ):
        as_edge_capture_parameters(object())


def test_as_edge_capture_parameters_returns_matching_instance() -> None:
    parameters = derive_edge_capture_parameters(
        board_thickness_mm=1.6,
        locations=spaced_locations(),
        policy=EdgeCapturePolicy(),
    )

    assert as_edge_capture_parameters(parameters) is parameters
