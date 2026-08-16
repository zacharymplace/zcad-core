#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    generate_production_evidence_artifact,
)

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_DIR = ROOT / "evidence" / "seeed-xiao-esp32s3"

# The vendor STEP file has the board lying in the XZ plane (Y = thickness
# axis); this is a Z-up copy produced once with a 90deg rotation about X,
# keeping the original vendor file untouched as the source of record.
SOURCE_STEP = EVIDENCE_DIR / "step" / "xiao_esp32s3_z_up.step"

OUTPUT_STEP = EVIDENCE_DIR / "seeed-xiao-esp32s3-corner-capture.step"

REPORT_PATH = EVIDENCE_DIR / "seeed-xiao-esp32s3-corner-capture.json"

# At only 21 x 17.8mm, the default 3.0mm arm / 2.0mm engagement / 4.0mm
# keepout leaves no clear diagonal corner pair on this board at all - every
# corner has an interfering component within that footprint. A 1.8mm arm /
# 0.3mm engagement (2.1mm keepout) is the smallest change that clears both
# derivation and manufacturing validation (arm_proportion requires
# arm_width_mm > 2*board_clearance_mm + minimum_wall_mm = 1.7mm).
POLICY = CornerCapturePolicy(
    arm_width_mm=1.8,
    engagement_depth_mm=0.3,
    board_clearance_mm=0.25,
)

CORNER_KEEPOUT_MM = 2.1


def main() -> None:
    if not SOURCE_STEP.is_file():
        raise SystemExit(f"Missing source STEP: {SOURCE_STEP}")

    artifact = generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=SOURCE_STEP,
            pcb_solid_index=37,
            output_step=OUTPUT_STEP,
            policy=POLICY,
            corner_keepout_mm=CORNER_KEEPOUT_MM,
        ),
        report_path=REPORT_PATH,
    )

    print("=== SEEED XIAO ESP32-S3 RETENTION EVIDENCE ===")
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
