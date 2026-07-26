from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    CornerCaptureFitCheck,
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    execute_production_corner_capture,
)

FEATHER_STEP = Path("evidence/adafruit-feather-rp2040/4884 Feather RP2040.step")


@pytest.mark.skipif(
    not FEATHER_STEP.is_file(),
    reason=("Official Feather RP2040 STEP evidence is not available locally"),
)
def test_feather_production_execution_exports_step(
    tmp_path: Path,
) -> None:
    output_step = tmp_path / "feather-rp2040-corner-capture.step"

    result = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=FEATHER_STEP,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
            corner_keepout_mm=4.0,
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
