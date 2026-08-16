#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from zcad_core.retention import (
    EdgeCapturePolicy,
    ProductionEdgeExecutionRequest,
    generate_production_edge_evidence_artifact,
)

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_DIR = ROOT / "evidence" / "arduino-uno-r4-wifi"

SOURCE_STEP = EVIDENCE_DIR / "step" / "UNO_R4_WIFI.step"

OUTPUT_STEP = EVIDENCE_DIR / "uno-r4-wifi-edge-capture.step"

REPORT_PATH = EVIDENCE_DIR / "uno-r4-wifi-edge-capture.json"


def main() -> None:
    if not SOURCE_STEP.is_file():
        raise SystemExit(f"Missing source STEP: {SOURCE_STEP}")

    artifact = generate_production_edge_evidence_artifact(
        ProductionEdgeExecutionRequest(
            source_step=SOURCE_STEP,
            pcb_solid_index=1,
            output_step=OUTPUT_STEP,
            policy=EdgeCapturePolicy(),
        ),
        report_path=REPORT_PATH,
    )

    print("=== UNO R4 WIFI EDGE-CAPTURE RETENTION EVIDENCE ===")
    print(f"Passed: {artifact.passed}")
    print(f"Selected edge: {artifact.execution.derivation.selected_edge.value}")
    print(
        f"Selected span: {artifact.execution.derivation.selected_span.length_mm:.3f} mm"
    )
    print(
        "PCB intersection: "
        f"{artifact.interference.pcb_capture_intersection_mm3:.9f} mm³"
    )
    print(
        "Component intersection: "
        f"{artifact.interference.component_capture_intersection_mm3:.9f} mm³"
    )
    print(f"STEP: {artifact.step_path}")
    print(f"Report: {artifact.report_path}")


if __name__ == "__main__":
    main()
