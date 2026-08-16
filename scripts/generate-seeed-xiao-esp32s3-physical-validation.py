#!/usr/bin/env python3

from pathlib import Path

from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    ValidationFixturePolicy,
    create_pending_physical_validation_record,
    execute_production_corner_capture,
    export_validation_fixture,
    write_physical_validation_record,
)

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_ROOT = ROOT / "evidence" / "seeed-xiao-esp32s3"

SOURCE_STEP = EVIDENCE_ROOT / "step" / "xiao_esp32s3_z_up.step"

EXECUTION_STEP = EVIDENCE_ROOT / "seeed-xiao-esp32s3-corner-capture.step"

CANDIDATE_REPORT = EVIDENCE_ROOT / "seeed-xiao-esp32s3-corner-capture.json"

FIXTURE_STL = EVIDENCE_ROOT / "seeed-xiao-esp32s3-physical-validation.stl"

VALIDATION_RECORD = EVIDENCE_ROOT / "seeed-xiao-esp32s3-physical-validation.json"

# Must match generate-seeed-xiao-esp32s3-retention-evidence.py's policy.
POLICY = CornerCapturePolicy(
    arm_width_mm=1.8,
    engagement_depth_mm=0.3,
    board_clearance_mm=0.25,
)

CORNER_KEEPOUT_MM = 2.1


def main() -> None:
    execution = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=SOURCE_STEP,
            pcb_solid_index=37,
            output_step=EXECUTION_STEP,
            policy=POLICY,
            corner_keepout_mm=CORNER_KEEPOUT_MM,
        )
    )

    fixture = export_validation_fixture(
        execution,
        output_path=FIXTURE_STL,
        policy=ValidationFixturePolicy(),
    )

    record = create_pending_physical_validation_record(
        candidate_report_path=(CANDIDATE_REPORT),
        fixture_stl_path=(fixture.stl_path),
        printer_profile=("pending-selection"),
        material_profile=("pending-selection"),
        slicer_profile=("pending-selection"),
    )

    write_physical_validation_record(
        record,
        output_path=VALIDATION_RECORD,
    )

    print("=== SEEED XIAO ESP32-S3 PHYSICAL-VALIDATION READINESS ===")
    print(f"Fixture: {fixture.stl_path}")
    print(f"Record: {VALIDATION_RECORD}")
    print(f"Ready to print: {FIXTURE_STL.is_file()}")
    print(f"Physical validation passed: {record.passed}")


if __name__ == "__main__":
    main()
