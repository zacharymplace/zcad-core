"""Assembly-aware board-retention metadata."""

from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict

BoardEdge = Literal[
    "negative_x",
    "positive_x",
    "negative_y",
    "positive_y",
]

InsertionAxis = Literal[
    "positive_z",
    "negative_z",
]


class BoardClipRegion(TypedDict):
    """One verified PCB edge region where a clip may engage."""

    edge: BoardEdge
    center_offset_mm: float
    width_mm: float
    edge_clearance_mm: float


class BoardKeepoutRegion(TypedDict):
    """One rectangular PCB region that retention features must avoid."""

    center_x_mm: float
    center_y_mm: float
    width_mm: float
    depth_mm: float


class BoardRetentionMetadata(TypedDict):
    """Verified metadata for tool-less board retention."""

    board_thickness_mm: float
    insertion_axis: InsertionAxis
    clip_regions: tuple[
        BoardClipRegion,
        ...,
    ]
    keepout_regions: tuple[
        BoardKeepoutRegion,
        ...,
    ]


def _numeric_value(
    *,
    value: object,
    name: str,
) -> float:
    """Return one numeric metadata value."""
    if not isinstance(value, int | float):
        raise TypeError(f"board retention {name} must be numeric")

    return float(value)


def _clip_region(
    value: object,
    *,
    index: int,
) -> BoardClipRegion:
    """Validate and normalize one clip region."""
    if not isinstance(value, Mapping):
        raise TypeError(f"board retention clip region {index} must be a mapping")

    edge = value.get("edge")

    valid_edges = {
        "negative_x",
        "positive_x",
        "negative_y",
        "positive_y",
    }

    if edge not in valid_edges:
        raise ValueError(
            f"board retention clip region {index} has unsupported edge: {edge}"
        )

    center_offset_mm = _numeric_value(
        value=value.get("center_offset_mm"),
        name=(f"clip region {index} center_offset_mm"),
    )
    width_mm = _numeric_value(
        value=value.get("width_mm"),
        name=f"clip region {index} width_mm",
    )
    edge_clearance_mm = _numeric_value(
        value=value.get("edge_clearance_mm"),
        name=(f"clip region {index} edge_clearance_mm"),
    )

    if width_mm <= 0:
        raise ValueError(
            f"board retention clip region {index} width_mm must be greater than zero"
        )

    if edge_clearance_mm < 0:
        raise ValueError(
            "board retention clip region "
            f"{index} edge_clearance_mm "
            "must not be negative"
        )

    return {
        "edge": edge,
        "center_offset_mm": center_offset_mm,
        "width_mm": width_mm,
        "edge_clearance_mm": edge_clearance_mm,
    }


def _keepout_region(
    value: object,
    *,
    index: int,
) -> BoardKeepoutRegion:
    """Validate and normalize one keep-out region."""
    if not isinstance(value, Mapping):
        raise TypeError(f"board retention keepout region {index} must be a mapping")

    center_x_mm = _numeric_value(
        value=value.get("center_x_mm"),
        name=(f"keepout region {index} center_x_mm"),
    )
    center_y_mm = _numeric_value(
        value=value.get("center_y_mm"),
        name=(f"keepout region {index} center_y_mm"),
    )
    width_mm = _numeric_value(
        value=value.get("width_mm"),
        name=f"keepout region {index} width_mm",
    )
    depth_mm = _numeric_value(
        value=value.get("depth_mm"),
        name=f"keepout region {index} depth_mm",
    )

    if width_mm <= 0:
        raise ValueError(
            f"board retention keepout region {index} width_mm must be greater than zero"
        )

    if depth_mm <= 0:
        raise ValueError(
            f"board retention keepout region {index} depth_mm must be greater than zero"
        )

    return {
        "center_x_mm": center_x_mm,
        "center_y_mm": center_y_mm,
        "width_mm": width_mm,
        "depth_mm": depth_mm,
    }


def board_retention_metadata(
    board: object,
) -> BoardRetentionMetadata | None:
    """Return verified board-retention metadata when supplied."""
    board_thickness_mm = getattr(
        board,
        "board_thickness_mm",
        None,
    )
    insertion_axis = getattr(
        board,
        "retention_insertion_axis",
        None,
    )
    clip_regions = getattr(
        board,
        "retention_clip_regions",
        None,
    )
    keepout_regions = getattr(
        board,
        "retention_keepout_regions",
        None,
    )

    # Every rectangular board already exposes board_thickness_mm.
    # Retention metadata is considered present only when one of the
    # retention-specific fields is supplied.
    supplied = (
        insertion_axis is not None
        or clip_regions is not None
        or keepout_regions is not None
    )

    if not supplied:
        return None

    missing = []

    if board_thickness_mm is None:
        missing.append("board_thickness_mm")

    if insertion_axis is None:
        missing.append("retention_insertion_axis")

    if clip_regions is None:
        missing.append("retention_clip_regions")

    if missing:
        rendered = ", ".join(sorted(missing))
        raise ValueError(
            f"board retention metadata must be complete; missing: {rendered}"
        )

    thickness = _numeric_value(
        value=board_thickness_mm,
        name="board_thickness_mm",
    )

    if thickness <= 0:
        raise ValueError("board retention board_thickness_mm must be greater than zero")

    if insertion_axis not in {
        "positive_z",
        "negative_z",
    }:
        raise ValueError(
            f"unsupported board retention insertion axis: {insertion_axis}"
        )

    if not isinstance(
        clip_regions,
        Sequence,
    ) or isinstance(
        clip_regions,
        str | bytes,
    ):
        raise TypeError("board retention clip regions must be a sequence")

    normalized_clips = tuple(
        _clip_region(
            region,
            index=index,
        )
        for index, region in enumerate(
            clip_regions,
            start=1,
        )
    )

    if not normalized_clips:
        raise ValueError("board retention metadata requires at least one clip region")

    resolved_keepouts = () if keepout_regions is None else keepout_regions

    if not isinstance(
        resolved_keepouts,
        Sequence,
    ) or isinstance(
        resolved_keepouts,
        str | bytes,
    ):
        raise TypeError("board retention keepout regions must be a sequence")

    normalized_keepouts = tuple(
        _keepout_region(
            region,
            index=index,
        )
        for index, region in enumerate(
            resolved_keepouts,
            start=1,
        )
    )

    return {
        "board_thickness_mm": thickness,
        "insertion_axis": insertion_axis,
        "clip_regions": normalized_clips,
        "keepout_regions": normalized_keepouts,
    }
