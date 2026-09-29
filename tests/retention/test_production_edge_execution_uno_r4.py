from __future__ import annotations

from pathlib import Path

import pytest

from zcad_core.geometry.types import BoardEdge
from zcad_core.retention.edge_backend import (
    EdgeCaptureFitCheck,
    as_edge_capture_fit_report,
)
from zcad_core.retention.edge_capture import EdgeCapturePolicy
from zcad_core.retention.edge_evidence_artifact import (
    generate_production_edge_evidence_artifact,
)
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionRequest,
    execute_production_edge_capture,
)

pytestmark = pytest.mark.slow

UNO_R4_WIFI_STEP = Path("evidence/arduino-uno-r4-wifi/step/UNO_R4_WIFI.step")


@pytest.mark.skipif(
    not UNO_R4_WIFI_STEP.is_file(),
    reason=("Official Arduino UNO R4 WiFi STEP evidence is not available locally"),
)
def test_uno_r4_wifi_edge_capture_finds_a_real_clear_span(
    tmp_path: Path,
) -> None:
    """Edge capture succeeds where corner capture cannot for this board.

    See test_production_board_uno_r4_wifi.py: corner capture has no
    diagonal-clear corner pair on this board at all. This proves edge
    capture generates real, board-validated geometry with zero exact
    solid intersection against the PCB or any component, using the
    board's negative-Y edge - which corner capture never considered.
    """

    output_step = tmp_path / "uno-r4-wifi-edge-capture.step"

    result = execute_production_edge_capture(
        ProductionEdgeExecutionRequest(
            source_step=UNO_R4_WIFI_STEP,
            pcb_solid_index=1,
            output_step=output_step,
            policy=EdgeCapturePolicy(),
        )
    )

    assert result.passed is True
    assert output_step.is_file()
    assert result.derivation.selected_edge is BoardEdge.NEGATIVE_Y
    assert result.derivation.selected_span.length_mm > 12.0
    assert len(result.derivation.request.locations) == 2

    for check in EdgeCaptureFitCheck:
        matching = next(
            item
            for item in as_edge_capture_fit_report(result.execution.report).results
            if item.check is check
        )
        assert matching.passed is True, matching.detail

    component_result = next(
        item
        for item in as_edge_capture_fit_report(result.execution.report).results
        if item.check is EdgeCaptureFitCheck.COMPONENT_CLEARANCE
    )
    assert "Production STEP evidence confirmed" in component_result.detail


@pytest.mark.skipif(
    not UNO_R4_WIFI_STEP.is_file(),
    reason=("Official Arduino UNO R4 WiFi STEP evidence is not available locally"),
)
def test_uno_r4_wifi_full_evidence_artifact_passes_manufacturing(
    tmp_path: Path,
) -> None:
    """Regression test for the adapter/manufacturing spacing mismatch.

    The default arm_width_mm and minimum_anchor_separation_mm were
    originally chosen independently of ManufacturingPolicy's own default
    minimum_capture_spacing_mm, so ProductionBoardEdgeAdapter could select
    a span whose two capture points ended up spaced closer than
    manufacturing validation required - passing derivation, then failing
    downstream. This exercises the full evidence-artifact layer
    (derivation, interference, and manufacturing together) against the
    real board that first exposed the mismatch.
    """

    artifact = generate_production_edge_evidence_artifact(
        ProductionEdgeExecutionRequest(
            source_step=UNO_R4_WIFI_STEP,
            pcb_solid_index=1,
            output_step=(tmp_path / "uno-r4-wifi-edge-capture-evidence.step"),
            policy=EdgeCapturePolicy(),
        ),
        report_path=(tmp_path / "uno-r4-wifi-edge-capture-evidence.json"),
    )

    assert artifact.passed is True
    assert artifact.step_path.is_file()
    assert artifact.report_path.is_file()
