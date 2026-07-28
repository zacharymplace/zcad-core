from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    ValidationFixturePolicy,
    execute_production_corner_capture,
    export_design_review_package,
)


def export_clear_board(
    path: Path,
) -> None:
    pcb = (
        cq.Workplane("XY")
        .box(
            40.0,
            30.0,
            1.6,
        )
        .translate(
            (
                0.0,
                0.0,
                0.8,
            )
        )
    )

    assembly = cq.Assembly()
    assembly.add(
        pcb,
        name="pcb",
    )
    assembly.save(
        str(path),
        exportType="STEP",
    )


def production_execution(
    tmp_path: Path,
):
    source_step = tmp_path / "board.step"

    export_clear_board(source_step)

    return execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=(tmp_path / "retention.step"),
            policy=CornerCapturePolicy(),
        )
    )


def test_exports_design_review_package(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)
    output_directory = tmp_path / "review"

    artifact = export_design_review_package(
        execution,
        output_directory=output_directory,
        fixture_policy=ValidationFixturePolicy(),
    )

    assert artifact.passed is True
    assert artifact.glb_path.is_file()
    assert artifact.step_path.is_file()
    assert artifact.three_mf_path.is_file()
    assert len(artifact.view_paths) == 4
    assert all(path.is_file() for path in artifact.view_paths)

    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))

    assert report["decision"] == ("visual_review_ready")
    assert report["passed"] is True
    assert report["geometry"]["component_count"] == 0
    assert report["review_status"] == {
        "automated_geometry_complete": True,
        "human_visual_review_complete": False,
        "physical_validation_complete": False,
    }


def test_refuses_existing_review_outputs(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)
    output_directory = tmp_path / "review"
    existing = output_directory / "design-review.json"

    output_directory.mkdir()
    existing.write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
        match="Refusing to overwrite",
    ):
        export_design_review_package(
            execution,
            output_directory=output_directory,
            fixture_policy=ValidationFixturePolicy(),
        )

    assert existing.read_text(encoding="utf-8") == "{}\n"
    assert not (output_directory / "design-review.glb").exists()


def test_rejects_negative_tolerance(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)

    with pytest.raises(
        ValueError,
        match="tolerance_mm3",
    ):
        export_design_review_package(
            execution,
            output_directory=(tmp_path / "review"),
            fixture_policy=ValidationFixturePolicy(),
            tolerance_mm3=-1.0,
        )
