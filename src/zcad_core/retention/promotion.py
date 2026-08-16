from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


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
    physical_trial_path: str
    created_at_utc: str
    relationship_path: str | None = None
    parameter_delta_path: str | None = None
    supersedes_candidate_id: str | None = None

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
                "physical_trial_path",
                self.physical_trial_path,
            ),
            ("created_at_utc", self.created_at_utc),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        for optional_field_name, optional_value in (
            ("relationship_path", self.relationship_path),
            ("parameter_delta_path", self.parameter_delta_path),
        ):
            if optional_value is not None and not optional_value.strip():
                raise ValueError(f"{optional_field_name} cannot be empty")

        if self.decision is PromotionDecision.PROMOTED:
            if not self.automated_validation_passed:
                raise ValueError("Promoted candidate requires automated validation")

            if not self.physical_validation_passed:
                raise ValueError("Promoted candidate requires physical validation")

        if self.supersedes_candidate_id == self.candidate_id:
            raise ValueError("A promotion cannot supersede its own candidate")


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


def register_candidate_promotion(
    *,
    record: PromotionRecord,
    output_path: Path,
) -> PromotionRecord:
    eligibility = evaluate_publication_eligibility(
        automated_validation_passed=(record.automated_validation_passed),
        physical_validation_passed=(record.physical_validation_passed),
        candidate_manifest_exists=Path(record.candidate_manifest_path).is_file(),
        relationship_exists=(
            record.relationship_path is None or Path(record.relationship_path).is_file()
        ),
        parameter_delta_exists=(
            record.parameter_delta_path is None
            or Path(record.parameter_delta_path).is_file()
        ),
        physical_trial_exists=Path(record.physical_trial_path).is_file(),
    )

    if not eligibility.eligible:
        failures = ", ".join(eligibility.failures)

        raise ValueError(f"Candidate is not eligible for promotion: {failures}")

    write_promotion_record(
        record,
        output_path=output_path,
    )

    return record


def select_preferred_revision(
    *,
    target_id: str,
    promotion_records: Sequence[PromotionRecord],
) -> PromotionRecord | None:
    """Return the currently preferred candidate for one target, if any.

    A candidate is preferred when it is PROMOTED and no other PROMOTED
    record for the same target names it via ``supersedes_candidate_id``.
    Promotion records are never rewritten when superseded — supersession is
    expressed only by the superseding record's own field — so each
    historical promotion decision remains intact.

    Deliberately independent of :class:`RevisionRelationship`: a
    ``supersedes`` relationship written by candidate derivation records
    revision *lineage* ("this candidate was derived from that one"), which
    is unrelated to which candidate is currently *preferred*. Conflating
    the two would make every candidate except the newest derived one look
    superseded, regardless of promotion history.
    """

    promoted = tuple(
        record
        for record in promotion_records
        if record.target_id == target_id
        and record.decision is PromotionDecision.PROMOTED
    )

    superseded_candidate_ids = {
        record.supersedes_candidate_id
        for record in promoted
        if record.supersedes_candidate_id is not None
    }

    preferred = tuple(
        record
        for record in promoted
        if record.candidate_id not in superseded_candidate_ids
    )

    if len(preferred) > 1:
        candidate_ids = ", ".join(sorted(record.candidate_id for record in preferred))

        raise ValueError(
            f"Ambiguous preferred revision for {target_id}: {candidate_ids}"
        )

    return preferred[0] if preferred else None


def promote_preferred_revision(
    *,
    record: PromotionRecord,
    output_path: Path,
    existing_promotion_records: Sequence[PromotionRecord] = (),
) -> PromotionRecord:
    """Register a candidate as the preferred revision for its target.

    When a different candidate is already preferred, ``record`` must set
    ``supersedes_candidate_id`` to that candidate's id; the prior promotion
    record is left untouched, preserving its historical decision.
    """

    current_preferred = select_preferred_revision(
        target_id=record.target_id,
        promotion_records=existing_promotion_records,
    )

    if (
        current_preferred is not None
        and current_preferred.candidate_id != record.candidate_id
        and record.supersedes_candidate_id != current_preferred.candidate_id
    ):
        raise ValueError(
            "Promoting a new preferred revision requires supersedes_candidate_id "
            f"to reference the currently preferred candidate: "
            f"{current_preferred.candidate_id}"
        )

    return register_candidate_promotion(
        record=record,
        output_path=output_path,
    )


def build_publication_record(
    *,
    part_record: dict[str, Any],
    promotion_record: PromotionRecord,
    eligibility: PublicationEligibility,
) -> dict[str, Any]:
    """Attach an explicit, evidence-gated publication decision to a part record.

    ``part_record`` is the product-agnostic metadata built by
    :func:`zcad_core.metadata.build_record.build_part_record`. Publication is
    approved only when the promotion decision is explicit and the automated
    and physical evidence backing it is complete; there is no path to
    approval by editing a Boolean directly.
    """

    if promotion_record.decision is not PromotionDecision.PROMOTED:
        raise ValueError(
            "Metadata publication requires an explicit PROMOTED decision, "
            f"got {promotion_record.decision.value}"
        )

    if not eligibility.eligible:
        failures = ", ".join(eligibility.failures)

        raise ValueError(f"Metadata publication blocked by evidence gaps: {failures}")

    return {
        **part_record,
        "publication": {
            "approved": True,
            "candidate_id": promotion_record.candidate_id,
            "target_id": promotion_record.target_id,
            "reviewer": promotion_record.reviewer,
            "promoted_at_utc": promotion_record.created_at_utc,
        },
    }
