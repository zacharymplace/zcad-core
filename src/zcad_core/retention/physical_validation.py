from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


class PhysicalValidationCheck(str, Enum):
    """Required physical-validation observations."""

    PRINT_COMPLETED = "print_completed"
    NO_VISIBLE_DEFECTS = "no_visible_defects"
    BOARD_INSERTS_WITHOUT_FORCE = "board_inserts_without_force"
    BOARD_SEATS_FULLY = "board_seats_fully"
    BOARD_RETAINS_WHEN_INVERTED = "board_retains_when_inverted"
    CONNECTORS_REMAIN_ACCESSIBLE = "connectors_remain_accessible"
    COMPONENTS_REMAIN_CLEAR = "components_remain_clear"
    BOARD_REMOVES_WITHOUT_DAMAGE = "board_removes_without_damage"


class PhysicalValidationDisposition(str, Enum):
    """Operator disposition for one physical trial."""

    PASS = "pass"
    REVISE = "revise"
    REJECT = "reject"


@dataclass(frozen=True)
class PhysicalValidationObservation:
    """One required physical observation."""

    check: PhysicalValidationCheck
    passed: bool
    notes: str = ""


@dataclass(frozen=True)
class PhysicalValidationRecord:
    """Structured result from one physical validation trial."""

    schema_version: str
    candidate_report_path: str
    fixture_stl_path: str
    printer_profile: str
    material_profile: str
    slicer_profile: str
    observations: tuple[PhysicalValidationObservation, ...]
    disposition: PhysicalValidationDisposition
    operator_notes: str
    completed_at_utc: str

    @property
    def complete(self) -> bool:
        """Whether every required observation is present once."""

        observed = {observation.check for observation in self.observations}

        return observed == set(PhysicalValidationCheck) and len(observed) == len(
            self.observations
        )

    @property
    def passed(self) -> bool:
        """Whether the record supports physical validation."""

        return (
            self.complete
            and all(observation.passed for observation in self.observations)
            and self.disposition is PhysicalValidationDisposition.PASS
        )


def create_pending_physical_validation_record(
    *,
    candidate_report_path: Path,
    fixture_stl_path: Path,
    printer_profile: str,
    material_profile: str,
    slicer_profile: str,
) -> PhysicalValidationRecord:
    """Create a fail-closed record awaiting operator inspection."""

    return PhysicalValidationRecord(
        schema_version="1.0.0",
        candidate_report_path=str(candidate_report_path),
        fixture_stl_path=str(fixture_stl_path),
        printer_profile=printer_profile,
        material_profile=material_profile,
        slicer_profile=slicer_profile,
        observations=tuple(
            PhysicalValidationObservation(
                check=check,
                passed=False,
                notes="Pending physical validation.",
            )
            for check in PhysicalValidationCheck
        ),
        disposition=(PhysicalValidationDisposition.REVISE),
        operator_notes=("Pending print, inspection, and board-fit trial."),
        completed_at_utc="",
    )


def write_physical_validation_record(
    record: PhysicalValidationRecord,
    *,
    output_path: Path,
) -> None:
    """Write a deterministic physical-validation record."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = asdict(record)
    payload["complete"] = record.complete
    payload["passed"] = record.passed

    output_path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def complete_physical_validation_record(
    *,
    candidate_report_path: Path,
    fixture_stl_path: Path,
    printer_profile: str,
    material_profile: str,
    slicer_profile: str,
    observations: tuple[PhysicalValidationObservation, ...],
    disposition: PhysicalValidationDisposition,
    operator_notes: str,
) -> PhysicalValidationRecord:
    """Create a completed operator validation record.

    A ``pass`` disposition is refused unless every required check is observed
    once and passed, so a record cannot claim a pass its observations deny.
    """

    if disposition is PhysicalValidationDisposition.PASS:
        observed = [observation.check for observation in observations]
        missing = sorted(
            check.value for check in PhysicalValidationCheck if check not in observed
        )
        failed = [
            observation.check.value
            for observation in observations
            if not observation.passed
        ]

        if missing or failed or len(observed) != len(set(observed)):
            raise ValueError(
                "A pass disposition requires every check to pass once; "
                f"missing: {missing or 'none'}, failed: {failed or 'none'}"
            )

    return PhysicalValidationRecord(
        schema_version="1.0.0",
        candidate_report_path=str(candidate_report_path),
        fixture_stl_path=str(fixture_stl_path),
        printer_profile=printer_profile,
        material_profile=material_profile,
        slicer_profile=slicer_profile,
        observations=observations,
        disposition=disposition,
        operator_notes=operator_notes.strip(),
        completed_at_utc=(datetime.now(UTC).isoformat()),
    )
