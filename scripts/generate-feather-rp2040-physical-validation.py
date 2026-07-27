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

EVIDENCE_ROOT = ROOT / "evidence" / "adafruit-feather-rp2040"

SOURCE_STEP = EVIDENCE_ROOT / "4884 Feather RP2040.step"

EXECUTION_STEP = EVIDENCE_ROOT / "feather-rp2040-corner-capture.step"

CANDIDATE_REPORT = EVIDENCE_ROOT / "feather-rp2040-corner-capture.json"

FIXTURE_STL = EVIDENCE_ROOT / "feather-rp2040-physical-validation.stl"

VALIDATION_RECORD = EVIDENCE_ROOT / "feather-rp2040-physical-validation.json"


def main() -> None:
    execution = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=SOURCE_STEP,
            pcb_solid_index=1,
            output_step=EXECUTION_STEP,
            policy=CornerCapturePolicy(),
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
    )

    write_physical_validation_record(
        record,
        output_path=VALIDATION_RECORD,
    )

    print("=== FEATHER RP2040 PHYSICAL-VALIDATION READINESS ===")
    print(f"Fixture: {fixture.stl_path}")
    print(f"Record: {VALIDATION_RECORD}")
    print(f"Ready to print: {FIXTURE_STL.is_file()}")
    print(f"Physical validation passed: {record.passed}")


if __name__ == "__main__":
    main()
