from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from zcad_core.retention import (
    UNRECORDED_SLICER_PROFILE,
    PhysicalValidationCheck,
    PhysicalValidationDisposition,
    PhysicalValidationObservation,
    complete_physical_validation_record,
    create_pending_physical_validation_record,
    load_physical_validation_record,
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
        slicer_profile="test-slicer",
    )

    assert record.pending is True
    assert record.complete is False
    assert record.passed is False
    assert record.disposition is PhysicalValidationDisposition.PENDING


def test_complete_passing_record_passes() -> None:
    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
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
        slicer_profile="test-slicer",
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
        slicer_profile="test-slicer",
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
        slicer_profile="test-slicer",
    )

    write_physical_validation_record(
        record,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["disposition"] == "pending"
    assert payload["pending"] is True
    assert payload["complete"] is False
    assert payload["passed"] is False
    assert payload["slicer_profile"] == "test-slicer"
    assert len(payload["observations"]) == len(PhysicalValidationCheck)


def all_passing_observations() -> tuple[PhysicalValidationObservation, ...]:
    return tuple(
        PhysicalValidationObservation(
            check=check,
            passed=True,
            notes="Passed.",
        )
        for check in PhysicalValidationCheck
    )


def test_pending_record_can_later_be_completed(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "record.json"

    write_physical_validation_record(
        create_pending_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="test-printer",
            material_profile="test-material",
            slicer_profile="test-slicer",
        ),
        output_path=output_path,
    )
    assert load_physical_validation_record(output_path).pending is True

    write_physical_validation_record(
        complete_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="test-printer",
            material_profile="test-material",
            slicer_profile="test-slicer",
            observations=all_passing_observations(),
            disposition=PhysicalValidationDisposition.REVISE,
            operator_notes="Printed; clearance too tight.",
        ),
        output_path=output_path,
    )

    record = load_physical_validation_record(output_path)

    assert record.pending is False
    assert record.complete is True
    assert record.passed is False
    assert record.disposition is PhysicalValidationDisposition.REVISE


def test_completed_record_cannot_be_pending() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be pending",
    ):
        complete_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="test-printer",
            material_profile="test-material",
            slicer_profile="test-slicer",
            observations=all_passing_observations(),
            disposition=PhysicalValidationDisposition.PENDING,
            operator_notes="",
        )


def test_pending_record_rejects_completion_timestamp(
    tmp_path: Path,
) -> None:
    record = create_pending_physical_validation_record(
        candidate_report_path=(tmp_path / "candidate.json"),
        fixture_stl_path=(tmp_path / "fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
    )

    with pytest.raises(
        ValueError,
        match="cannot be completed",
    ):
        replace(record, completed_at_utc="2026-09-27T00:00:00+00:00")


def test_legacy_pending_record_loads_as_pending(
    tmp_path: Path,
) -> None:
    # Shape written by trial start before the pending disposition existed.
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "candidate_report_path": "candidate.json",
                "complete": True,
                "completed_at_utc": "",
                "disposition": "revise",
                "fixture_stl_path": "fixture.stl",
                "material_profile": "petg",
                "observations": [
                    {
                        "check": check.value,
                        "notes": "Pending physical validation.",
                        "passed": False,
                    }
                    for check in PhysicalValidationCheck
                ],
                "operator_notes": "Pending print, inspection, and board-fit trial.",
                "passed": False,
                "printer_profile": "bambu-lab-a1-mini",
                "schema_version": "1.0.0",
                "slicer_profile": "bambu-studio-a1-mini-petg-validation",
            }
        ),
        encoding="utf-8",
    )

    record = load_physical_validation_record(path)

    assert record.disposition is PhysicalValidationDisposition.PENDING
    assert record.pending is True
    assert record.complete is False
    assert record.passed is False


def test_record_without_slicer_profile_loads_as_unrecorded(
    tmp_path: Path,
) -> None:
    # Records written before the slicer profile was tracked omit the key.
    path = tmp_path / "record.json"

    write_physical_validation_record(
        create_pending_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="pending-selection",
            material_profile="pending-selection",
            slicer_profile="pending-selection",
        ),
        output_path=path,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["slicer_profile"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    record = load_physical_validation_record(path)

    assert record.slicer_profile == UNRECORDED_SLICER_PROFILE
    assert record.pending is True
