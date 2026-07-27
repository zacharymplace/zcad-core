from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    BoardCorner,
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    generate_production_evidence_artifact,
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


def export_blocked_board(
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

    positions = (
        (-18.5, -13.5),
        (-18.5, 13.5),
    )

    assembly = cq.Assembly()
    assembly.add(
        pcb,
        name="pcb",
    )

    for index, (
        x_mm,
        y_mm,
    ) in enumerate(
        positions,
        start=1,
    ):
        component = (
            cq.Workplane("XY")
            .box(
                3.0,
                3.0,
                2.0,
            )
            .translate(
                (
                    x_mm,
                    y_mm,
                    2.6,
                )
            )
        )

        assembly.add(
            component,
            name=f"component-{index}",
        )

    assembly.save(
        str(path),
        exportType="STEP",
    )


def test_generates_step_and_json_evidence(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "capture.step"
    report_path = tmp_path / "capture.json"

    export_clear_board(source_step)

    artifact = generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        ),
        report_path=report_path,
    )

    assert artifact.passed is True
    assert output_step.is_file()
    assert report_path.is_file()

    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["schema_version"] == "1.0.0"
    assert report["decision"] == ("verified_candidate")
    assert len(report["selected_corners"]) == 2
    assert report["interference"]["passed"] is True
    assert report["metadata_publication"]["approved"] is False

    assert len(report["source"]["step_sha256"]) == 64
    assert len(report["output"]["step_sha256"]) == 64


def test_report_contains_all_fit_checks(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "capture.step"
    report_path = tmp_path / "capture.json"

    export_clear_board(source_step)

    generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        ),
        report_path=report_path,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert set(report["fit_checks"]) == {
        "planar_restraint",
        "vertical_retention",
        "component_clearance",
        "installation_path",
        "manufacturing_clearance",
    }

    assert all(item["passed"] for item in (report["fit_checks"].values()))


def test_rejected_board_creates_no_artifacts(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "blocked.step"
    output_step = tmp_path / "capture.step"
    report_path = tmp_path / "capture.json"

    export_blocked_board(source_step)

    with pytest.raises(
        ValueError,
        match="two component-clear diagonal corners",
    ):
        generate_production_evidence_artifact(
            ProductionCornerExecutionRequest(
                source_step=source_step,
                pcb_solid_index=1,
                output_step=output_step,
                policy=CornerCapturePolicy(),
            ),
            report_path=report_path,
        )

    assert not output_step.exists()
    assert not report_path.exists()


def test_selected_corners_are_balanced(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "capture.step"
    report_path = tmp_path / "capture.json"

    export_clear_board(source_step)

    artifact = generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        ),
        report_path=report_path,
    )

    assert (artifact.execution.derivation.selected_corners) == (
        BoardCorner.NEGATIVE_X_NEGATIVE_Y,
        BoardCorner.POSITIVE_X_POSITIVE_Y,
    )


def test_interference_uses_capture_only_geometry(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "capture.step"
    report_path = tmp_path / "capture.json"

    export_clear_board(source_step)

    artifact = generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        ),
        report_path=report_path,
    )

    assert artifact.interference.pcb_capture_intersection_mm3 == pytest.approx(
        0.0,
        abs=1e-6,
    )
    assert artifact.interference.component_capture_intersection_mm3 == pytest.approx(
        0.0,
        abs=1e-6,
    )


def test_report_contains_manufacturing_validation(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "capture.step"
    report_path = tmp_path / "capture.json"

    export_clear_board(source_step)

    generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        ),
        report_path=report_path,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))

    manufacturing = report["manufacturing"]

    assert manufacturing["passed"] is True
    assert set(manufacturing["checks"]) == {
        "minimum_wall",
        "board_clearance",
        "vertical_overlap",
        "arm_proportion",
        "capture_spacing",
        "print_orientation",
        "overhang",
    }

    assert all(result["passed"] for result in (manufacturing["checks"].values()))
