"""Tests for the reusable export service."""

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.exporters import (
    ExportRequest,
    export_parts,
)


def _tapered_block(
    *,
    width: float,
    depth: float,
    height: float,
    taper: float,
) -> cq.Workplane:
    """A loft between two differently-sized rectangles."""
    return (
        cq.Workplane("XY")
        .rect(width, depth)
        .workplane(offset=height)
        .rect(width - taper, depth - taper)
        .loft(combine=True)
    )


def _loft_cut_union_part() -> cq.Workplane:
    """A loft + cut + union solid shaped like the drip-tray basin that
    was observed to leave a stale, mesh-polluted BoundingBox() on the
    Workplane after cq.exporters.export() triangulated it for STL."""
    basin = _tapered_block(
        width=60,
        depth=40,
        height=14,
        taper=10,
    )
    cavity = _tapered_block(
        width=50,
        depth=30,
        height=14,
        taper=8,
    ).translate((0, 0, 2))

    body = basin.cut(cavity)

    spout = (
        cq.Workplane("XY")
        .box(
            20,
            15,
            4,
            centered=(True, False, False),
        )
        .translate((0, 20, 4))
    )

    return body.union(spout)


def test_metadata_bounds_match_freshly_reimported_step(
    tmp_path: Path,
) -> None:
    """Regression test: metadata bounding_box_mm must match the bounds of
    the actual exported geometry, not a stale post-export BoundingBox()
    call on the in-memory Workplane (see _loft_cut_union_part)."""
    result = export_parts(
        ExportRequest(
            design_name="test-basin",
            design_type="test",
            parts={"main": _loft_cut_union_part()},
            output_directory=tmp_path,
            repository_root=Path.cwd(),
        )
    )

    exported = result.parts[0]
    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))

    reimported = cq.importers.importStep(str(exported.step_path))
    fresh_bounds = reimported.val().BoundingBox()

    bounding_box_mm = metadata["part"]["bounding_box_mm"]

    assert bounding_box_mm["x"] == pytest.approx(fresh_bounds.xlen, abs=1e-2)
    assert bounding_box_mm["y"] == pytest.approx(fresh_bounds.ylen, abs=1e-2)
    assert bounding_box_mm["z"] == pytest.approx(fresh_bounds.zlen, abs=1e-2)

    assert exported.bounds_mm == pytest.approx(
        (
            fresh_bounds.xlen,
            fresh_bounds.ylen,
            fresh_bounds.zlen,
        ),
        abs=1e-2,
    )


def test_single_main_part_uses_design_name(
    tmp_path: Path,
) -> None:
    result = export_parts(
        ExportRequest(
            design_name="test-cube",
            design_type="test",
            parts={"main": (cq.Workplane("XY").box(10, 10, 10))},
            output_directory=tmp_path,
            repository_root=Path.cwd(),
        )
    )

    exported = result.parts[0]

    assert exported.stem == "test-cube"
    assert exported.step_path.is_file()
    assert exported.stl_path.is_file()
    assert exported.metadata_path.is_file()

    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))

    assert metadata["design"]["name"] == "test-cube"
    assert metadata["part"]["name"] == "main"


def test_multi_part_names_include_part(
    tmp_path: Path,
) -> None:
    result = export_parts(
        ExportRequest(
            design_name="test-box",
            design_type="assembly",
            parts={
                "body": (cq.Workplane("XY").box(20, 20, 10)),
                "lid": (cq.Workplane("XY").box(20, 20, 2)),
            },
            output_directory=tmp_path,
            repository_root=Path.cwd(),
        )
    )

    stems = {part.stem for part in result.parts}

    assert stems == {
        "test-box-body",
        "test-box-lid",
    }


def test_empty_parts_are_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="no parts",
    ):
        export_parts(
            ExportRequest(
                design_name="empty",
                design_type="test",
                parts={},
                output_directory=tmp_path,
                repository_root=Path.cwd(),
            )
        )


@pytest.mark.parametrize(
    ("field_value", "message"),
    [
        (
            "bad design",
            "design_name",
        ),
        (
            "../escape",
            "design_name",
        ),
    ],
)
def test_unsafe_design_names_are_rejected(
    tmp_path: Path,
    field_value: str,
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        export_parts(
            ExportRequest(
                design_name=field_value,
                design_type="test",
                parts={"main": (cq.Workplane("XY").box(5, 5, 5))},
                output_directory=tmp_path,
                repository_root=Path.cwd(),
            )
        )
