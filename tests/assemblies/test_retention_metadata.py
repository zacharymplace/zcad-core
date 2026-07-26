"""Tests for board-retention metadata."""

from dataclasses import dataclass

import pytest

from zcad_core.assemblies import (
    board_retention_metadata,
)


@dataclass(frozen=True)
class RetentionBoard:
    """Complete board-retention fixture."""

    board_thickness_mm: float = 1.6
    retention_insertion_axis: str = "positive_z"
    retention_clip_regions: tuple = (
        {
            "edge": "negative_x",
            "center_offset_mm": 0.0,
            "width_mm": 6.0,
            "edge_clearance_mm": 0.5,
        },
        {
            "edge": "positive_x",
            "center_offset_mm": 0.0,
            "width_mm": 6.0,
            "edge_clearance_mm": 0.5,
        },
    )
    retention_keepout_regions: tuple = (
        {
            "center_x_mm": 0.0,
            "center_y_mm": 10.0,
            "width_mm": 12.0,
            "depth_mm": 5.0,
        },
    )


def test_board_without_retention_metadata_returns_none() -> None:
    assert board_retention_metadata(object()) is None


def test_complete_retention_metadata_is_normalized() -> None:
    metadata = board_retention_metadata(RetentionBoard())

    assert metadata is not None
    assert metadata["board_thickness_mm"] == 1.6
    assert metadata["insertion_axis"] == "positive_z"
    assert len(metadata["clip_regions"]) == 2
    assert len(metadata["keepout_regions"]) == 1


def test_retention_metadata_requires_complete_contract() -> None:
    class PartialBoard:
        board_thickness_mm = 1.6

    with pytest.raises(
        ValueError,
        match="must be complete",
    ):
        board_retention_metadata(PartialBoard())


def test_retention_metadata_requires_clip_region() -> None:
    board = RetentionBoard(
        retention_clip_regions=(),
    )

    with pytest.raises(
        ValueError,
        match="at least one clip region",
    ):
        board_retention_metadata(board)


def test_retention_metadata_rejects_unknown_edge() -> None:
    board = RetentionBoard(
        retention_clip_regions=(
            {
                "edge": "diagonal",
                "center_offset_mm": 0.0,
                "width_mm": 6.0,
                "edge_clearance_mm": 0.5,
            },
        ),
    )

    with pytest.raises(
        ValueError,
        match="unsupported edge",
    ):
        board_retention_metadata(board)


def test_retention_metadata_rejects_negative_clearance() -> None:
    board = RetentionBoard(
        retention_clip_regions=(
            {
                "edge": "negative_y",
                "center_offset_mm": 0.0,
                "width_mm": 6.0,
                "edge_clearance_mm": -0.1,
            },
        ),
    )

    with pytest.raises(
        ValueError,
        match="must not be negative",
    ):
        board_retention_metadata(board)


def test_retention_metadata_rejects_invalid_keepout() -> None:
    board = RetentionBoard(
        retention_keepout_regions=(
            {
                "center_x_mm": 0.0,
                "center_y_mm": 0.0,
                "width_mm": 0.0,
                "depth_mm": 4.0,
            },
        ),
    )

    with pytest.raises(
        ValueError,
        match="width_mm must be greater than zero",
    ):
        board_retention_metadata(board)
