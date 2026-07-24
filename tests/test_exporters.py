"""Tests for the reusable export service."""

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad.exporters import (
    ExportRequest,
    export_parts,
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
