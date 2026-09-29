"""Tests for board-retention metadata."""

from dataclasses import dataclass, field

import pytest

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    RectangularBoardSpec,
    board_retention_metadata,
    build_board_display_assembly,
)
from zcad_core.hardware import (
    RectangularConnectorSpec,
    get_raspberry_pi_pico2,
    get_seeed_xiao_esp32s3,
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
        retention_insertion_axis = "positive_z"

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


def _retention_connector() -> RectangularConnectorSpec:
    """Return a connector for assembly publication tests."""
    return RectangularConnectorSpec(
        identifier="TEST_USB",
        width_mm=8.0,
        depth_mm=6.0,
        height_mm=3.0,
        board_edge="negative_y",
    )


@dataclass(frozen=True)
class RetentionAssemblyBoard:
    """Rectangular board with verified test retention metadata."""

    identifier: str = "RETENTION_TEST_BOARD"
    board_width_mm: float = 20.0
    board_length_mm: float = 40.0
    board_thickness_mm: float = 1.6
    usb_connector: RectangularConnectorSpec = field(
        default_factory=_retention_connector,
    )

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
            "center_y_mm": -17.0,
            "width_mm": 10.0,
            "depth_mm": 6.0,
        },
    )


@dataclass(frozen=True)
class RetentionTestDisplay:
    """Minimal display for assembly publication tests."""

    identifier: str = "RETENTION_TEST_DISPLAY"
    module_width_mm: float = 28.0
    module_height_mm: float = 20.0
    module_depth_mm: float = 4.0
    mount_style: str = "bezel"


def _retention_assembly(board: RectangularBoardSpec) -> DeviceAssembly:
    """Build an assembly for one retention metadata fixture."""
    return build_board_display_assembly(
        board=board,
        display=RetentionTestDisplay(),
        board_placement=Placement(),
        display_placement=Placement(
            z_mm=8.0,
        ),
    )


def test_assembly_publishes_board_retention_metadata() -> None:
    assembly = _retention_assembly(RetentionAssemblyBoard())

    retention = assembly.get("board").metadata["retention"]

    assert retention == {
        "board_thickness_mm": 1.6,
        "insertion_axis": "positive_z",
        "clip_regions": (
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
        ),
        "keepout_regions": (
            {
                "center_x_mm": 0.0,
                "center_y_mm": -17.0,
                "width_mm": 10.0,
                "depth_mm": 6.0,
            },
        ),
    }


def test_pico_omits_unverified_retention_metadata() -> None:
    assembly = _retention_assembly(get_raspberry_pi_pico2())

    assert "retention" not in assembly.get("board").metadata


def test_xiao_omits_unverified_retention_metadata() -> None:
    assembly = _retention_assembly(get_seeed_xiao_esp32s3())

    assert "retention" not in assembly.get("board").metadata


def test_board_thickness_alone_does_not_enable_retention_metadata() -> None:
    class OrdinaryBoard:
        board_thickness_mm = 1.6

    assert board_retention_metadata(OrdinaryBoard()) is None
