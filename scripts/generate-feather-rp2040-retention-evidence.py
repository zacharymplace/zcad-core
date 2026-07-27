#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    generate_production_evidence_artifact,
)

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_DIR = ROOT / "evidence" / "adafruit-feather-rp2040"

SOURCE_STEP = EVIDENCE_DIR / "4884 Feather RP2040.step"

OUTPUT_STEP = EVIDENCE_DIR / "feather-rp2040-corner-capture.step"

REPORT_PATH = EVIDENCE_DIR / "feather-rp2040-corner-capture.json"


def main() -> None:
    if not SOURCE_STEP.is_file():
        raise SystemExit(f"Missing source STEP: {SOURCE_STEP}")

    artifact = generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=SOURCE_STEP,
            pcb_solid_index=1,
            output_step=OUTPUT_STEP,
            policy=CornerCapturePolicy(),
            corner_keepout_mm=4.0,
        ),
        report_path=REPORT_PATH,
    )

    print("=== FEATHER RP2040 RETENTION EVIDENCE ===")
    print(f"Passed: {artifact.passed}")
    print(
        "Selected corners: "
        + ", ".join(
            corner.value for corner in (artifact.execution.derivation.selected_corners)
        )
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
