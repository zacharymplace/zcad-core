#!/usr/bin/env python3

from pathlib import Path

from zcad_core.retention import (
    EdgeCapturePolicy,
    ProductionEdgeExecutionRequest,
    ValidationFixturePolicy,
    create_pending_physical_validation_record,
    execute_production_edge_capture,
    export_edge_validation_fixture,
    write_physical_validation_record,
)

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_ROOT = ROOT / "evidence" / "arduino-uno-r4-wifi"

SOURCE_STEP = EVIDENCE_ROOT / "step" / "UNO_R4_WIFI.step"

EXECUTION_STEP = EVIDENCE_ROOT / "uno-r4-wifi-edge-capture.step"

CANDIDATE_REPORT = EVIDENCE_ROOT / "uno-r4-wifi-edge-capture.json"

FIXTURE_STL = EVIDENCE_ROOT / "uno-r4-wifi-physical-validation.stl"

VALIDATION_RECORD = EVIDENCE_ROOT / "uno-r4-wifi-physical-validation.json"


def main() -> None:
    execution = execute_production_edge_capture(
        ProductionEdgeExecutionRequest(
            source_step=SOURCE_STEP,
            pcb_solid_index=1,
            output_step=EXECUTION_STEP,
            policy=EdgeCapturePolicy(),
        )
    )

    fixture = export_edge_validation_fixture(
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

    print("=== UNO R4 WIFI PHYSICAL-VALIDATION READINESS ===")
    print(f"Fixture: {fixture.stl_path}")
    print(f"Record: {VALIDATION_RECORD}")
    print(f"Ready to print: {FIXTURE_STL.is_file()}")
    print(f"Physical validation passed: {record.passed}")


if __name__ == "__main__":
    main()
