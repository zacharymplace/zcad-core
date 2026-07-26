from __future__ import annotations

import pytest

from zcad_core.retention.corner_capture import (
    BoardCorner,
    CornerCaptureLocation,
    CornerCaptureParameters,
    CornerCapturePolicy,
    derive_corner_capture_parameters,
)


def opposite_corner_locations() -> tuple[CornerCaptureLocation, ...]:
    return (
        CornerCaptureLocation(
            corner=(BoardCorner.NEGATIVE_X_NEGATIVE_Y),
            x_mm=-20.0,
            y_mm=-15.0,
        ),
        CornerCaptureLocation(
            corner=(BoardCorner.POSITIVE_X_POSITIVE_Y),
            x_mm=20.0,
            y_mm=15.0,
        ),
    )


def test_default_policy_is_valid() -> None:
    policy = CornerCapturePolicy()

    assert policy.arm_width_mm == pytest.approx(3.0)
    assert policy.engagement_depth_mm == pytest.approx(2.0)
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
        "arm_width_mm": 3.0,
        "engagement_depth_mm": 2.0,
        "board_clearance_mm": 0.25,
        "vertical_overlap_mm": 0.6,
        "minimum_wall_mm": 1.2,
    }
    values[field] = 0.0

    with pytest.raises(
        ValueError,
        match=field,
    ):
        CornerCapturePolicy(**values)


def test_clearance_cannot_be_negative() -> None:
    with pytest.raises(
        ValueError,
        match="board_clearance_mm",
    ):
        CornerCapturePolicy(board_clearance_mm=-0.01)


def test_derivation_preserves_validated_policy() -> None:
    policy = CornerCapturePolicy(
        arm_width_mm=3.4,
        engagement_depth_mm=2.2,
        board_clearance_mm=0.3,
        vertical_overlap_mm=0.7,
        minimum_wall_mm=1.4,
    )

    result = derive_corner_capture_parameters(
        board_thickness_mm=1.6,
        locations=opposite_corner_locations(),
        policy=policy,
    )

    assert result.board_thickness_mm == pytest.approx(1.6)
    assert result.locations == (opposite_corner_locations())
    assert result.arm_width_mm == pytest.approx(3.4)
    assert result.engagement_depth_mm == pytest.approx(2.2)
    assert result.board_clearance_mm == pytest.approx(0.3)
    assert result.vertical_overlap_mm == pytest.approx(0.7)
    assert result.minimum_wall_mm == pytest.approx(1.4)


def test_one_location_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="at least two",
    ):
        CornerCaptureParameters(
            board_thickness_mm=1.6,
            locations=(opposite_corner_locations()[0],),
            arm_width_mm=3.0,
            engagement_depth_mm=2.0,
            board_clearance_mm=0.25,
            vertical_overlap_mm=0.6,
            minimum_wall_mm=1.2,
        )


def test_duplicate_corner_is_rejected() -> None:
    location = opposite_corner_locations()[0]

    with pytest.raises(
        ValueError,
        match="unique",
    ):
        derive_corner_capture_parameters(
            board_thickness_mm=1.6,
            locations=(location, location),
            policy=CornerCapturePolicy(),
        )


def test_adjacent_same_side_corners_are_rejected() -> None:
    locations = (
        CornerCaptureLocation(
            corner=(BoardCorner.NEGATIVE_X_NEGATIVE_Y),
            x_mm=-20.0,
            y_mm=-15.0,
        ),
        CornerCaptureLocation(
            corner=(BoardCorner.NEGATIVE_X_POSITIVE_Y),
            x_mm=-20.0,
            y_mm=15.0,
        ),
    )

    with pytest.raises(
        ValueError,
        match="both board-plane axes",
    ):
        derive_corner_capture_parameters(
            board_thickness_mm=1.6,
            locations=locations,
            policy=CornerCapturePolicy(),
        )


@pytest.mark.parametrize(
    "locations",
    (
        (
            CornerCaptureLocation(
                BoardCorner.NEGATIVE_X_NEGATIVE_Y,
                -20.0,
                -15.0,
            ),
            CornerCaptureLocation(
                BoardCorner.POSITIVE_X_POSITIVE_Y,
                20.0,
                15.0,
            ),
        ),
        (
            CornerCaptureLocation(
                BoardCorner.NEGATIVE_X_POSITIVE_Y,
                -20.0,
                15.0,
            ),
            CornerCaptureLocation(
                BoardCorner.POSITIVE_X_NEGATIVE_Y,
                20.0,
                -15.0,
            ),
        ),
    ),
)
def test_opposite_corners_resist_both_axes(
    locations: tuple[CornerCaptureLocation, ...],
) -> None:
    result = derive_corner_capture_parameters(
        board_thickness_mm=1.6,
        locations=locations,
        policy=CornerCapturePolicy(),
    )

    assert result.locations == locations


def test_negative_corner_radius_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="local_radius_mm",
    ):
        CornerCaptureLocation(
            corner=(BoardCorner.NEGATIVE_X_NEGATIVE_Y),
            x_mm=-20.0,
            y_mm=-15.0,
            local_radius_mm=-0.1,
        )
