from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from zcad_core.retention import (
    UNRECORDED_SLICER_PROFILE,
    PhysicalMeasurement,
    PhysicalValidationCheck,
    PhysicalValidationDisposition,
    PhysicalValidationObservation,
    complete_physical_validation_record,
    create_pending_physical_validation_record,
    load_physical_validation_record,
    write_physical_validation_record,
)

MEASUREMENTS = (
    PhysicalMeasurement(name="vertical_play", value_mm=0.8, nominal_mm=0.85),
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
        measurements=MEASUREMENTS,
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

    with pytest.raises(ValueError, match="failed: \\['board_seats_fully'\\]"):
        complete_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="test-printer",
            material_profile="test-material",
            slicer_profile="test-slicer",
            observations=observations,
            disposition=(PhysicalValidationDisposition.PASS),
            measurements=MEASUREMENTS,
            operator_notes="Board did not seat.",
        )

    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
        observations=observations,
        disposition=(PhysicalValidationDisposition.REVISE),
        measurements=MEASUREMENTS,
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

    with pytest.raises(ValueError, match="missing: \\['cables_seat_fully'\\]"):
        complete_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="test-printer",
            material_profile="test-material",
            slicer_profile="test-slicer",
            observations=observations,
            disposition=(PhysicalValidationDisposition.PASS),
            measurements=MEASUREMENTS,
            operator_notes="Incomplete.",
        )

    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
        observations=observations,
        disposition=(PhysicalValidationDisposition.REVISE),
        measurements=MEASUREMENTS,
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
            measurements=MEASUREMENTS,
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


def all_passing() -> tuple[PhysicalValidationObservation, ...]:
    return tuple(
        PhysicalValidationObservation(check=check, passed=True, notes="Passed.")
        for check in PhysicalValidationCheck
    )


@pytest.mark.parametrize(
    "disposition",
    [PhysicalValidationDisposition.PASS, PhysicalValidationDisposition.REVISE],
)
def test_pass_and_revise_require_measurements(
    disposition: PhysicalValidationDisposition,
) -> None:
    with pytest.raises(ValueError, match="requires at least one measurement"):
        complete_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="test-printer",
            material_profile="test-material",
            slicer_profile="test-slicer",
            observations=all_passing(),
            disposition=disposition,
            operator_notes="Unmeasured.",
        )


def test_reject_may_have_nothing_to_measure() -> None:
    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
        observations=tuple(
            PhysicalValidationObservation(check=check, passed=False)
            for check in PhysicalValidationCheck
        ),
        disposition=PhysicalValidationDisposition.REJECT,
        operator_notes="Print failed.",
    )

    assert record.complete is True
    assert record.measurements == ()


def test_measurements_round_trip_with_deviation(tmp_path: Path) -> None:
    record = complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
        observations=all_passing(),
        disposition=PhysicalValidationDisposition.PASS,
        operator_notes="Measured.",
        measurements=(
            PhysicalMeasurement(name="vertical_play", value_mm=0.8, nominal_mm=0.85),
            PhysicalMeasurement(name="clip_to_header_gap", value_mm=0.2),
        ),
    )
    path = tmp_path / "record.json"
    write_physical_validation_record(record, output_path=path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.1.0"
    assert payload["measurements"][0]["deviation_mm"] == pytest.approx(-0.05)
    assert payload["measurements"][1]["deviation_mm"] is None

    assert load_physical_validation_record(path) == record


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("Vertical Play", 0.8, "lowercase snake_case"),
        ("vertical_play", float("nan"), "finite value_mm"),
    ],
)
def test_measurement_rejects_bad_input(name: str, value: float, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        PhysicalMeasurement(name=name, value_mm=value)


def test_duplicate_measurement_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        complete_physical_validation_record(
            candidate_report_path=Path("candidate.json"),
            fixture_stl_path=Path("fixture.stl"),
            printer_profile="test-printer",
            material_profile="test-material",
            slicer_profile="test-slicer",
            observations=all_passing(),
            disposition=PhysicalValidationDisposition.PASS,
            operator_notes="Measured twice.",
            measurements=MEASUREMENTS + MEASUREMENTS,
        )


def test_legacy_record_is_judged_by_its_own_checklist(tmp_path: Path) -> None:
    """A 1.0.0 record answered the eight original checks and no more."""

    legacy_checks = [
        check
        for check in PhysicalValidationCheck
        if check
        not in {
            PhysicalValidationCheck.BOARD_RESISTS_LATERAL_PUSH,
            PhysicalValidationCheck.CABLES_SEAT_FULLY,
        }
    ]
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "candidate_report_path": "candidate.json",
                "fixture_stl_path": "fixture.stl",
                "printer_profile": "test-printer",
                "material_profile": "test-material",
                "slicer_profile": "test-slicer",
                "observations": [
                    {"check": check.value, "passed": True, "notes": ""}
                    for check in legacy_checks
                ],
                "disposition": "pass",
                "operator_notes": "Legacy pass.",
                "completed_at_utc": "2026-07-28T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    record = load_physical_validation_record(path)

    assert record.complete is True
    assert record.passed is True
    assert record.measurements == ()


def test_pending_record_uses_current_schema(tmp_path: Path) -> None:
    record = create_pending_physical_validation_record(
        candidate_report_path=tmp_path / "candidate.json",
        fixture_stl_path=tmp_path / "fixture.stl",
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
    )

    assert record.schema_version == "1.1.0"
    assert {observation.check for observation in record.observations} == set(
        PhysicalValidationCheck
    )


def completed_record(
    disposition: PhysicalValidationDisposition = PhysicalValidationDisposition.PASS,
    notes: str = "Fit accepted.",
):
    return complete_physical_validation_record(
        candidate_report_path=Path("candidate.json"),
        fixture_stl_path=Path("fixture.stl"),
        printer_profile="test-printer",
        material_profile="test-material",
        slicer_profile="test-slicer",
        observations=all_passing(),
        disposition=disposition,
        operator_notes=notes,
        measurements=MEASUREMENTS,
    )


def test_completed_record_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    first = completed_record()
    write_physical_validation_record(first, output_path=path)
    before = path.read_text(encoding="utf-8")

    # Rewriting identical content is a no-op, not an error.
    write_physical_validation_record(first, output_path=path)

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        write_physical_validation_record(
            completed_record(
                PhysicalValidationDisposition.REVISE, notes="Second opinion."
            ),
            output_path=path,
        )

    assert path.read_text(encoding="utf-8") == before


def test_completed_record_cannot_revert_to_pending(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    write_physical_validation_record(completed_record(), output_path=path)

    with pytest.raises(FileExistsError, match="only a pending record"):
        write_physical_validation_record(
            create_pending_physical_validation_record(
                candidate_report_path=Path("candidate.json"),
                fixture_stl_path=Path("fixture.stl"),
                printer_profile="test-printer",
                material_profile="test-material",
                slicer_profile="test-slicer",
            ),
            output_path=path,
        )


def test_unreadable_existing_file_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        write_physical_validation_record(completed_record(), output_path=path)

    assert path.read_text(encoding="utf-8") == "[]\n"
