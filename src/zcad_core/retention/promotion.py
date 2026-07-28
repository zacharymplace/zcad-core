from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


class PromotionDecision(str, Enum):
    PROMOTED = "promoted"
    REJECTED = "rejected"
    REQUIRES_REVISION = "requires_revision"


@dataclass(frozen=True)
class PublicationEligibility:
    eligible: bool
    failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.eligible and self.failures:
            raise ValueError("Eligible publication cannot contain failures")

        if not self.eligible and not self.failures:
            raise ValueError("Ineligible publication must contain failures")


@dataclass(frozen=True)
class PromotionRecord:
    schema_version: str
    target_id: str
    candidate_id: str
    decision: PromotionDecision
    reason: str
    reviewer: str
    automated_validation_passed: bool
    physical_validation_passed: bool
    candidate_manifest_path: str
    relationship_path: str
    parameter_delta_path: str
    physical_trial_path: str
    created_at_utc: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("Unsupported promotion record schema")

        for field_name, value in (
            ("target_id", self.target_id),
            ("candidate_id", self.candidate_id),
            ("reason", self.reason),
            ("reviewer", self.reviewer),
            (
                "candidate_manifest_path",
                self.candidate_manifest_path,
            ),
            (
                "relationship_path",
                self.relationship_path,
            ),
            (
                "parameter_delta_path",
                self.parameter_delta_path,
            ),
            (
                "physical_trial_path",
                self.physical_trial_path,
            ),
            ("created_at_utc", self.created_at_utc),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        if self.decision is PromotionDecision.PROMOTED:
            if not self.automated_validation_passed:
                raise ValueError("Promoted candidate requires automated validation")

            if not self.physical_validation_passed:
                raise ValueError("Promoted candidate requires physical validation")


def evaluate_publication_eligibility(
    *,
    automated_validation_passed: bool,
    physical_validation_passed: bool,
    candidate_manifest_exists: bool,
    relationship_exists: bool,
    parameter_delta_exists: bool,
    physical_trial_exists: bool,
) -> PublicationEligibility:
    failures: list[str] = []

    if not automated_validation_passed:
        failures.append("automated_validation_not_passed")

    if not physical_validation_passed:
        failures.append("physical_validation_not_passed")

    if not candidate_manifest_exists:
        failures.append("candidate_manifest_missing")

    if not relationship_exists:
        failures.append("relationship_record_missing")

    if not parameter_delta_exists:
        failures.append("parameter_delta_missing")

    if not physical_trial_exists:
        failures.append("physical_trial_missing")

    return PublicationEligibility(
        eligible=not failures,
        failures=tuple(failures),
    )


def write_promotion_record(
    record: PromotionRecord,
    *,
    output_path: Path,
) -> None:
    payload = asdict(record)
    payload["decision"] = record.decision.value

    serialized = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")

        if existing == serialized:
            return

        raise FileExistsError(
            f"Refusing to overwrite immutable promotion record: {output_path}"
        )

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )
