from __future__ import annotations

import json
from pathlib import Path

from zcad_core.retention import (
    PhysicalValidationCheck,
    PhysicalValidationDisposition,
    PhysicalValidationObservation,
    complete_physical_validation_record,
    create_pending_physical_validation_record,
    write_physical_validation_record,
)


def test_pending_record_fails_closed(
    tmp_path: Path,
) -> None:
    record = create_pending_physical_validation_record(
        candidate_report_path=(tmp_path / "candidate.json"),
        fixture_stl_path=(tmp_path / "fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
    )

    assert record.complete is True
    assert record.passed is False
    assert record.disposition is (PhysicalValidationDisposition.REVISE)


def test_complete_passing_record_passes() -> None:
    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        observations=tuple(
            PhysicalValidationObservation(
                check=check,
                passed=True,
                notes="Passed.",
            )
            for check in PhysicalValidationCheck
        ),
        disposition=(PhysicalValidationDisposition.PASS),
        operator_notes="Physical fit accepted.",
    )

    assert record.complete is True
    assert record.passed is True
    assert record.completed_at_utc


def test_failed_observation_blocks_pass() -> None:
    observations = tuple(
        PhysicalValidationObservation(
            check=check,
            passed=(check is not PhysicalValidationCheck.BOARD_SEATS_FULLY),
            notes="Observed.",
        )
        for check in PhysicalValidationCheck
    )

    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        observations=observations,
        disposition=(PhysicalValidationDisposition.PASS),
        operator_notes="Board did not seat.",
    )

    assert record.complete is True
    assert record.passed is False


def test_incomplete_record_fails_closed() -> None:
    observations = tuple(
        PhysicalValidationObservation(
            check=check,
            passed=True,
        )
        for check in tuple(PhysicalValidationCheck)[:-1]
    )

    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        observations=observations,
        disposition=(PhysicalValidationDisposition.PASS),
        operator_notes="Incomplete.",
    )

    assert record.complete is False
    assert record.passed is False


def test_record_writes_json(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "record.json"

    record = create_pending_physical_validation_record(
        candidate_report_path=(tmp_path / "candidate.json"),
        fixture_stl_path=(tmp_path / "fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
    )

    write_physical_validation_record(
        record,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["complete"] is True
    assert payload["passed"] is False
    assert len(payload["observations"]) == len(PhysicalValidationCheck)
