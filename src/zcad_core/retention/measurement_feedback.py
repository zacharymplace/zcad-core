"""Turn a fixture trial's measurements into the next revision's policy.

A fixture trial measures two fits the retention policy sets:

- ``board_clearance``: the gap between the board edge and a capture wall,
  designed as ``board_clearance_mm``; and
- ``vertical_play``: the gap between the board top and a capture ledge,
  designed as ``board_clearance_mm + vertical_overlap_mm``.

Each is compared with its nominal. A shortfall means the printer printed the
fit tighter than modelled, so the next revision models it that much looser
(and an excess, that much tighter), aiming the printed fit at the designed
one. The vertical fit is corrected through ``vertical_overlap_mm`` after the
clearance change, since the clearance raises the ledge too. Changes stay at
or above the manufacturing minimums, and differences within gauge noise
change nothing.

Everything else a trial records, failed checks and gaps to components,
becomes a note: no single policy setting follows from it.

:func:`propose_fixture_revision` only reads. ``scripts/regenerate-candidate.py
--from-trial`` applies a proposal and writes it beside the new revision as
``measurement-feedback.json``, so each parameter change traces to the
measurements behind it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.retention.manufacturing import ManufacturingPolicy
from zcad_core.retention.physical_validation import (
    PhysicalValidationRecord,
    load_physical_validation_record,
)
from zcad_core.retention.revision_history import RevisionRelationshipType
from zcad_core.retention.revision_registration import load_candidate_revision
from zcad_core.validation.measurements import PhysicalMeasurement

MEASUREMENT_FEEDBACK_SCHEMA_VERSION = "1.0.0"
MEASUREMENT_FEEDBACK = "measurement-feedback.json"
# Feeler gauges step in 0.02-0.05 mm; smaller differences are noise.
NOISE_MM = 0.03
# One revision moves a fit at most this far, so a mismeasurement cannot
# swing the geometry wildly.
MAXIMUM_STEP_MM = 0.5
CLEARANCE = "board_clearance_mm"
OVERLAP = "vertical_overlap_mm"

FAILED_CHECK_GUIDANCE = {
    "board_inserts_without_force": (
        "The board needed force. If the clearance measured true, the ledges "
        "may be catching; check vertical play."
    ),
    "board_seats_fully": "The board rocks. Look for a part under it touching the base.",
    "board_retains_when_inverted": (
        "The board falls out upside down. More vertical_overlap_mm or "
        "engagement_depth_mm holds it; neither follows from a measurement."
    ),
    "board_resists_lateral_push": (
        "The board slides out sideways. More engagement_depth_mm resists it; "
        "check the push direction against the open corners."
    ),
    "components_remain_clear": (
        "A capture touches a part. Record which; the capture needs moving, "
        "not a looser fit."
    ),
    "connectors_remain_accessible": "A port is blocked. Record which one.",
    "cables_seat_fully": (
        "A cable will not seat. The base lip under an overhanging connector is "
        "the usual cause; see the roadmap's base-lip note."
    ),
    "board_removes_without_damage": "Removal damaged the board; record where.",
    "print_completed": "The print failed; fix the print before the design.",
    "no_visible_defects": "The print has defects; fix the print before the design.",
}


@dataclass(frozen=True)
class PolicyChange:
    """One retention-policy change and the measurement behind it."""

    parameter: str
    current: float
    proposed: float
    measurement: str
    nominal_mm: float
    measured_mm: float
    reason: str


@dataclass(frozen=True)
class FixtureRevisionProposal:
    """What a fixture trial says to change in the next revision."""

    candidate_directory: Path
    candidate_id: str
    trial_id: str
    physical_validation_path: Path
    physical_validation_sha256: str
    policy: dict[str, float]
    changes: tuple[PolicyChange, ...]
    notes: tuple[str, ...]

    @property
    def updates(self) -> dict[str, float]:
        return {change.parameter: change.proposed for change in self.changes}

    @property
    def relationship(self) -> RevisionRelationshipType:
        changed = set(self.updates)

        if CLEARANCE in changed:
            return RevisionRelationshipType.ADJUSTS_CLEARANCE_FROM

        return RevisionRelationshipType.ADJUSTS_OVERLAP_FROM

    @property
    def reason(self) -> str:
        measurements = {
            change.measurement: (change.measured_mm, change.nominal_mm)
            for change in self.changes
        }
        measured = "; ".join(
            f"{name} measured {value:.2f} mm against {nominal:.2f} nominal"
            for name, (value, nominal) in measurements.items()
        )

        return f"{self.trial_id} of {self.candidate_id}: {measured}."

    def record(self) -> dict[str, Any]:
        """The ``measurement-feedback.json`` payload."""

        return {
            "schema_version": MEASUREMENT_FEEDBACK_SCHEMA_VERSION,
            "parent_candidate_id": self.candidate_id,
            "trial_id": self.trial_id,
            "physical_validation_path": str(self.physical_validation_path),
            "physical_validation_sha256": self.physical_validation_sha256,
            "changes": [
                {
                    "parameter": change.parameter,
                    "previous_value": change.current,
                    "current_value": change.proposed,
                    "measurement": change.measurement,
                    "nominal_mm": change.nominal_mm,
                    "measured_mm": change.measured_mm,
                    "reason": change.reason,
                }
                for change in self.changes
            ],
            "notes": list(self.notes),
        }


def _bounded(current: float, target: float, minimum: float) -> float:
    step = max(-MAXIMUM_STEP_MM, min(MAXIMUM_STEP_MM, target - current))

    return round(max(minimum, current + step), 2)


def _clearance_change(
    policy: dict[str, float],
    measured: dict[str, PhysicalMeasurement],
    minimums: ManufacturingPolicy,
) -> PolicyChange | None:
    entry = measured.get("board_clearance")

    if entry is None or entry.nominal_mm is None:
        return None

    shortfall = entry.nominal_mm - entry.value_mm

    if abs(shortfall) < NOISE_MM:
        return None

    current = policy[CLEARANCE]
    proposed = _bounded(
        current, current + shortfall, minimums.minimum_board_clearance_mm
    )

    if proposed == current:
        return None

    return PolicyChange(
        parameter=CLEARANCE,
        current=current,
        proposed=proposed,
        measurement=entry.name,
        nominal_mm=entry.nominal_mm,
        measured_mm=entry.value_mm,
        reason=(
            f"The side gap printed {abs(shortfall):.2f} mm "
            f"{'tight' if shortfall > 0 else 'loose'}."
        ),
    )


def _overlap_change(
    policy: dict[str, float],
    measured: dict[str, PhysicalMeasurement],
    clearance: float,
    minimums: ManufacturingPolicy,
) -> PolicyChange | None:
    entry = measured.get("vertical_play")
    current = policy[OVERLAP]

    if entry is None or entry.nominal_mm is None:
        return None

    shortfall = entry.nominal_mm - entry.value_mm

    if abs(shortfall) < NOISE_MM:
        return None

    # The ledge sits clearance + overlap above the board; aim the printed
    # play back at its nominal after any clearance change raised it.
    target = entry.nominal_mm + shortfall - clearance
    proposed = _bounded(current, target, minimums.minimum_vertical_overlap_mm)

    if proposed == current:
        return None

    return PolicyChange(
        parameter=OVERLAP,
        current=current,
        proposed=proposed,
        measurement=entry.name,
        nominal_mm=entry.nominal_mm,
        measured_mm=entry.value_mm,
        reason=(
            f"The vertical play printed {abs(shortfall):.2f} mm "
            f"{'tight' if shortfall > 0 else 'loose'}."
        ),
    )


def _keep_play(
    policy: dict[str, float], clearance: PolicyChange, minimums: ManufacturingPolicy
) -> PolicyChange | None:
    """Without a vertical measurement, hold the modelled play where it was
    while the clearance change moves the ledge."""

    current = policy[OVERLAP]
    play = clearance.current + current
    proposed = _bounded(
        current, play - clearance.proposed, minimums.minimum_vertical_overlap_mm
    )

    if proposed == current:
        return None

    return PolicyChange(
        parameter=OVERLAP,
        current=current,
        proposed=proposed,
        measurement=clearance.measurement,
        nominal_mm=clearance.nominal_mm,
        measured_mm=clearance.measured_mm,
        reason=(
            "Holds the modelled vertical play while the clearance change "
            "moves the ledge; vertical play was not measured."
        ),
    )


def _notes(
    record: PhysicalValidationRecord,
    measured: dict[str, PhysicalMeasurement],
    changes: list[PolicyChange],
) -> list[str]:
    notes = [
        f"{observation.check.value}: "
        + FAILED_CHECK_GUIDANCE.get(observation.check.value, "Record what failed.")
        for observation in record.observations
        if not observation.passed
    ]

    for name, entry in measured.items():
        if name in ("board_clearance", "vertical_play") or entry.nominal_mm is None:
            continue

        if entry.value_mm < entry.nominal_mm - NOISE_MM:
            notes.append(
                f"{name}: measured {entry.value_mm:.2f} mm against "
                f"{entry.nominal_mm:.2f} nominal. A gap to a part closed up; "
                "the capture may need moving."
            )

    if not changes and not notes:
        notes.append("The trial found nothing to change.")

    return notes


def propose_fixture_revision(
    candidate_directory: Path,
    *,
    trial_id: str = "trial-001",
    minimums: ManufacturingPolicy | None = None,
) -> FixtureRevisionProposal:
    """Read a completed fixture trial and propose the next revision's policy."""

    candidate = load_candidate_revision(candidate_directory / "candidate.json")
    record_path = candidate_directory / "trials" / trial_id / "physical-validation.json"
    record = load_physical_validation_record(record_path)

    if record.pending:
        raise ValueError(
            f"{trial_id} of {candidate.candidate_id} has not been recorded yet; "
            "run zcad-validation trial complete first"
        )

    minimums = minimums or ManufacturingPolicy()
    policy = {name: float(value) for name, value in candidate.retention_policy.items()}
    measured = {entry.name: entry for entry in record.measurements}
    changes: list[PolicyChange] = []
    clearance = _clearance_change(policy, measured, minimums)

    if clearance is not None:
        changes.append(clearance)

    overlap = _overlap_change(
        policy,
        measured,
        clearance.proposed if clearance else policy[CLEARANCE],
        minimums,
    )

    if overlap is None and clearance is not None and "vertical_play" not in measured:
        overlap = _keep_play(policy, clearance, minimums)

    if overlap is not None:
        changes.append(overlap)

    return FixtureRevisionProposal(
        candidate_directory=candidate_directory,
        candidate_id=candidate.candidate_id,
        trial_id=trial_id,
        physical_validation_path=record_path,
        physical_validation_sha256=hashlib.sha256(record_path.read_bytes()).hexdigest(),
        policy=policy,
        changes=tuple(changes),
        notes=tuple(_notes(record, measured, changes)),
    )


def write_measurement_feedback(
    proposal: FixtureRevisionProposal, revision_directory: Path
) -> Path:
    """Record the proposal beside the revision it produced; never replaces one."""

    path = revision_directory / MEASUREMENT_FEEDBACK

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite measurement feedback: {path}")

    path.write_text(
        json.dumps(proposal.record(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return path
