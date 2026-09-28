from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    EdgeCapturePolicy,
    ProductionCornerExecutionRequest,
    ProductionEdgeExecutionRequest,
    ValidationFixturePolicy,
    execute_production_corner_capture,
    execute_production_edge_capture,
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
    assembly.export(
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


def test_exports_edge_clip_design_review_package(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    export_clear_board(source_step)
    execution = execute_production_edge_capture(
        ProductionEdgeExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=tmp_path / "retention.step",
            policy=EdgeCapturePolicy(),
        )
    )

    artifact = export_design_review_package(
        execution,
        output_directory=tmp_path / "review",
        fixture_policy=ValidationFixturePolicy(),
    )

    assert artifact.passed is True
    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))
    assert report["geometry"]["selected_corners"] == [
        execution.derivation.selected_edge.value
    ]


def board_with_underside_part(
    path: Path, *, depth_mm: float, z_offset: float = 0.0
) -> None:
    """A board with one bottom-side part proud of its underside by depth_mm."""

    pcb = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8 + z_offset))
    pad = (
        cq.Workplane("XY")
        .box(2.0, 2.0, depth_mm + 0.5)
        .translate((0.0, 0.0, z_offset - depth_mm + (depth_mm + 0.5) / 2))
    )
    assembly = cq.Assembly()
    assembly.add(pcb, name="pcb")
    assembly.add(pad, name="pad")
    assembly.export(str(path), exportType="STEP")


def review_board(tmp_path: Path, **board: float) -> dict[str, object]:
    source_step = tmp_path / "board.step"
    board_with_underside_part(source_step, **board)
    execution = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=tmp_path / "retention.step",
            policy=CornerCapturePolicy(),
        )
    )
    artifact = export_design_review_package(
        execution,
        output_directory=tmp_path / "review",
        fixture_policy=ValidationFixturePolicy(),
    )
    report = json.loads(artifact.report_path.read_text(encoding="utf-8"))
    assert report["passed"] is artifact.passed

    return report


def test_shallow_underside_pads_are_seating_contact(tmp_path: Path) -> None:
    report = review_board(tmp_path, depth_mm=0.04)

    interference = report["interference"]
    assert report["passed"] is True
    assert interference["component_fixture_intersections"] == []
    assert len(interference["underside_seating_contacts"]) == 1
    assert interference["underside_seating_contacts"][0]["depth_mm"] == pytest.approx(
        0.04, abs=1e-6
    )


def test_deep_underside_parts_block_review(tmp_path: Path) -> None:
    report = review_board(tmp_path, depth_mm=0.3)

    assert report["passed"] is False
    assert len(report["interference"]["component_fixture_intersections"]) == 1
    assert report["interference"]["underside_seating_contacts"] == []


def test_board_modelled_below_origin_seats_on_base(tmp_path: Path) -> None:
    report = review_board(tmp_path, depth_mm=0.04, z_offset=-1.6)

    assert report["passed"] is True
    assert report["interference"]["pcb_fixture_intersection_mm3"] == 0.0
