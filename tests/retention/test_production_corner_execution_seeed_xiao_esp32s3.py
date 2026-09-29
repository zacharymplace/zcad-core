from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    CornerCaptureFitCheck,
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    execute_production_corner_capture,
    generate_production_evidence_artifact,
)

pytestmark = pytest.mark.slow

XIAO_ESP32S3_STEP = Path("evidence/seeed-xiao-esp32s3/step/xiao_esp32s3_z_up.step")

POLICY = CornerCapturePolicy(
    arm_width_mm=1.8,
    engagement_depth_mm=0.3,
    board_clearance_mm=0.25,
)

CORNER_KEEPOUT_MM = 2.1


@pytest.mark.skipif(
    not XIAO_ESP32S3_STEP.is_file(),
    reason=("Official Seeed XIAO ESP32-S3 STEP evidence is not available locally"),
)
def test_xiao_esp32s3_production_execution_exports_step(
    tmp_path: Path,
) -> None:
    output_step = tmp_path / "seeed-xiao-esp32s3-corner-capture.step"

    result = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=XIAO_ESP32S3_STEP,
            pcb_solid_index=37,
            output_step=output_step,
            policy=POLICY,
            corner_keepout_mm=CORNER_KEEPOUT_MM,
        )
    )

    assert result.passed is True
    assert output_step.is_file()
    assert len(result.derivation.selected_corners) == 2

    component_result = next(
        item
        for item in result.execution.report.results
        if (item.check is CornerCaptureFitCheck.COMPONENT_CLEARANCE)
    )

    assert component_result.passed is True
    assert "Production STEP evidence confirmed" in (component_result.detail)

    exported = cq.importers.importStep(str(output_step)).val()

    assert exported is not None
    assert exported.BoundingBox().xlen > result.board_model.pcb.BoundingBox().xlen
    assert exported.BoundingBox().ylen > result.board_model.pcb.BoundingBox().ylen


@pytest.mark.skipif(
    not XIAO_ESP32S3_STEP.is_file(),
    reason=("Official Seeed XIAO ESP32-S3 STEP evidence is not available locally"),
)
def test_xiao_esp32s3_full_evidence_artifact_passes_manufacturing(
    tmp_path: Path,
) -> None:
    """The tuned policy must clear manufacturing validation, not just
    derivation and interference - this is what generate_production_evidence
    _artifact requires before a candidate can be registered."""

    artifact = generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=XIAO_ESP32S3_STEP,
            pcb_solid_index=37,
            output_step=(tmp_path / "seeed-xiao-esp32s3-corner-capture.step"),
            policy=POLICY,
            corner_keepout_mm=CORNER_KEEPOUT_MM,
        ),
        report_path=(tmp_path / "seeed-xiao-esp32s3-corner-capture.json"),
    )

    assert artifact.passed is True
    assert artifact.step_path.is_file()
    assert artifact.report_path.is_file()
