from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

# Records and trial manifests written before the slicer profile was tracked
# carry no ``slicer_profile``; they load with this value rather than failing.
UNRECORDED_SLICER_PROFILE = "unrecorded"


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
    BOARD_RESISTS_LATERAL_PUSH = "board_resists_lateral_push"
    CABLES_SEAT_FULLY = "cables_seat_fully"


PHYSICAL_VALIDATION_SCHEMA_VERSION = "1.1.0"

# Schema 1.1.0 adds checks for the reservations the first visual reviews
# raised (a board sliding out under a sideways push, a cable plug binding on
# the base), plus dimensional measurements. Records written at 1.0.0 load and
# are judged against the checks that existed when they were written.
REQUIRED_PHYSICAL_CHECKS: dict[str, frozenset[PhysicalValidationCheck]] = {
    "1.0.0": frozenset(PhysicalValidationCheck)
    - {
        PhysicalValidationCheck.BOARD_RESISTS_LATERAL_PUSH,
        PhysicalValidationCheck.CABLES_SEAT_FULLY,
    },
    PHYSICAL_VALIDATION_SCHEMA_VERSION: frozenset(PhysicalValidationCheck),
}

_MEASUREMENT_NAME = re.compile(r"[a-z][a-z0-9_]*")


class PhysicalValidationDisposition(str, Enum):
    """Operator disposition for one physical trial.

    ``PENDING`` marks a trial that has been started but not yet printed and
    inspected; it is never an outcome and never counts as a complete trial.
    """

    PENDING = "pending"
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
class PhysicalMeasurement:
    """One dimensional measurement of the printed fixture or fitted board.

    ``nominal_mm`` is the designed value when there is one (for example the
    export-validation vertical play), so the deviation that drives the next
    revision is recorded rather than recomputed from memory.
    """

    name: str
    value_mm: float
    nominal_mm: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not _MEASUREMENT_NAME.fullmatch(self.name):
            raise ValueError(
                f"Measurement name must be lowercase snake_case: {self.name!r}"
            )

        if not math.isfinite(self.value_mm):
            raise ValueError(f"Measurement {self.name} needs a finite value_mm")

        if self.nominal_mm is not None and not math.isfinite(self.nominal_mm):
            raise ValueError(f"Measurement {self.name} has a non-finite nominal_mm")

    @property
    def deviation_mm(self) -> float | None:
        """Measured minus nominal, when a nominal is recorded."""

        return None if self.nominal_mm is None else self.value_mm - self.nominal_mm


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
    measurements: tuple[PhysicalMeasurement, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version not in REQUIRED_PHYSICAL_CHECKS:
            raise ValueError("Unsupported physical validation schema")

        names = [measurement.name for measurement in self.measurements]

        if len(names) != len(set(names)):
            raise ValueError("Measurement names must be unique")

        if self.disposition is PhysicalValidationDisposition.PENDING:
            if self.completed_at_utc.strip():
                raise ValueError("Pending physical validation cannot be completed")

            if any(observation.passed for observation in self.observations):
                raise ValueError(
                    "Pending physical validation cannot record passing observations"
                )

            if self.measurements:
                raise ValueError(
                    "Pending physical validation cannot record measurements"
                )

    @property
    def pending(self) -> bool:
        """Whether the trial is still awaiting print and inspection.

        Records written before the explicit ``pending`` disposition existed
        carried a placeholder ``revise`` disposition with no completion
        timestamp; an empty ``completed_at_utc`` identifies them as pending.
        """

        return (
            self.disposition is PhysicalValidationDisposition.PENDING
            or not self.completed_at_utc.strip()
        )

    @property
    def complete(self) -> bool:
        """Whether the trial was performed and every check required by the
        record's schema is observed once."""

        if self.pending:
            return False

        observed = {observation.check for observation in self.observations}

        return observed == REQUIRED_PHYSICAL_CHECKS[self.schema_version] and len(
            observed
        ) == len(self.observations)

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
        schema_version=PHYSICAL_VALIDATION_SCHEMA_VERSION,
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
        disposition=PhysicalValidationDisposition.PENDING,
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

    for measurement, entry in zip(
        record.measurements, payload["measurements"], strict=True
    ):
        entry["deviation_mm"] = measurement.deviation_mm

    payload["pending"] = record.pending
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
    measurements: tuple[PhysicalMeasurement, ...] = (),
) -> PhysicalValidationRecord:
    """Create a completed operator validation record.

    A ``pass`` disposition is refused unless every required check is observed
    once and passed, so a record cannot claim a pass its observations deny.
    ``pass`` and ``revise`` also need at least one measurement: a revise
    derives the next revision from measured deltas, and a pass promotes a
    candidate whose fit should be on record. A ``reject`` may have nothing
    to measure, such as a failed print.
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

    if (
        disposition
        in {PhysicalValidationDisposition.PASS, PhysicalValidationDisposition.REVISE}
        and not measurements
    ):
        raise ValueError(
            f"A {disposition.value} disposition requires at least one measurement"
        )

    if disposition is PhysicalValidationDisposition.PENDING:
        raise ValueError("A completed physical validation cannot be pending")

    return PhysicalValidationRecord(
        schema_version=PHYSICAL_VALIDATION_SCHEMA_VERSION,
        candidate_report_path=str(candidate_report_path),
        fixture_stl_path=str(fixture_stl_path),
        printer_profile=printer_profile,
        material_profile=material_profile,
        slicer_profile=slicer_profile,
        observations=observations,
        disposition=disposition,
        operator_notes=operator_notes.strip(),
        completed_at_utc=(datetime.now(UTC).isoformat()),
        measurements=measurements,
    )


def physical_validation_record_from_payload(
    payload: dict[str, Any],
) -> PhysicalValidationRecord:
    """Parse a physical-validation record written to disk.

    Legacy pending records (placeholder ``revise`` disposition, empty
    ``completed_at_utc``) load with the explicit ``pending`` disposition so
    they can never be read as a revise outcome. Derived keys stored beside
    the record (``complete``, ``passed``, ``pending``) are recomputed rather
    than trusted.
    """

    completed_at_utc = str(payload.get("completed_at_utc") or "")
    disposition = PhysicalValidationDisposition(str(payload["disposition"]))

    if not completed_at_utc.strip():
        disposition = PhysicalValidationDisposition.PENDING

    observations = tuple(
        PhysicalValidationObservation(
            check=PhysicalValidationCheck(str(observation["check"])),
            passed=(
                bool(observation["passed"])
                and disposition is not PhysicalValidationDisposition.PENDING
            ),
            notes=str(observation.get("notes", "")),
        )
        for observation in payload["observations"]
    )

    return PhysicalValidationRecord(
        schema_version=str(payload["schema_version"]),
        candidate_report_path=str(payload["candidate_report_path"]),
        fixture_stl_path=str(payload["fixture_stl_path"]),
        printer_profile=str(payload["printer_profile"]),
        material_profile=str(payload["material_profile"]),
        slicer_profile=str(payload.get("slicer_profile", UNRECORDED_SLICER_PROFILE)),
        observations=observations,
        disposition=disposition,
        operator_notes=str(payload.get("operator_notes", "")),
        completed_at_utc=completed_at_utc,
        # Stored deviation_mm is derived, so it is recomputed, not read.
        measurements=tuple(
            PhysicalMeasurement(
                name=str(measurement["name"]),
                value_mm=float(measurement["value_mm"]),
                nominal_mm=(
                    None
                    if measurement.get("nominal_mm") is None
                    else float(measurement["nominal_mm"])
                ),
                notes=str(measurement.get("notes", "")),
            )
            for measurement in payload.get("measurements", ())
        ),
    )


def load_physical_validation_record(
    path: Path,
) -> PhysicalValidationRecord:
    """Load a physical-validation record, reading legacy pending records as pending."""

    if not path.is_file():
        raise FileNotFoundError(path)

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError("Physical validation record root must be an object")

    return physical_validation_record_from_payload(payload)
