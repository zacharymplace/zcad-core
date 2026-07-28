from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .revision_history import (
    RevisionDeltaReport,
    RevisionRelationship,
    RevisionRelationshipType,
    compare_candidate_parameters,
    write_revision_delta_report,
    write_revision_relationship,
)
from .validation_lab import (
    CandidateRevision,
    candidate_identifier,
    write_immutable_manifest,
)


@dataclass(frozen=True)
class RevisionRegistrationResult:
    candidate: CandidateRevision
    relationship: RevisionRelationship
    delta_report: RevisionDeltaReport

    candidate_path: Path
    relationship_path: Path
    delta_report_path: Path


def load_candidate_revision(
    path: Path,
) -> CandidateRevision:
    from .validation_lab import load_manifest

    payload = load_manifest(path)

    selected = payload["selected_corners"]
    policy = payload["retention_policy"]
    derived = payload["derived_parameters"]

    if not isinstance(selected, list):
        raise TypeError("selected_corners must be a list")

    if not isinstance(policy, dict):
        raise TypeError("retention_policy must be an object")

    if not isinstance(derived, dict):
        raise TypeError("derived_parameters must be an object")

    return CandidateRevision(
        schema_version=str(payload["schema_version"]),
        candidate_id=str(payload["candidate_id"]),
        target_id=str(payload["target_id"]),
        revision=str(payload["revision"]),
        source_sha256=str(payload["source_sha256"]),
        output_sha256=str(payload["output_sha256"]),
        git_commit=str(payload["git_commit"]),
        generator_version=str(payload["generator_version"]),
        retention_policy={str(key): float(value) for key, value in policy.items()},
        derived_parameters=dict(derived),
        selected_corners=tuple(str(value) for value in selected),
        automated_decision=str(payload["automated_decision"]),
        automated_evidence_path=str(payload["automated_evidence_path"]),
        fixture_artifact_path=str(payload["fixture_artifact_path"]),
        created_at_utc=str(payload["created_at_utc"]),
    )


def derive_candidate_revision(
    *,
    parent_candidate: CandidateRevision,
    revision: str,
    parameter_updates: dict[str, float],
    automated_decision: str,
) -> CandidateRevision:
    """Derive one deterministic candidate from its parent."""

    if not parameter_updates:
        raise ValueError("parameter_updates cannot be empty")

    shared_parameters = set(parent_candidate.retention_policy) & set(
        parent_candidate.derived_parameters
    )

    unsupported_parameters = sorted(set(parameter_updates) - shared_parameters)

    if unsupported_parameters:
        names = ", ".join(unsupported_parameters)
        raise ValueError(
            "parameter_updates must reference "
            "parameters present in retention_policy "
            f"and derived_parameters: {names}"
        )

    retention_policy = dict(parent_candidate.retention_policy)
    derived_parameters = dict(parent_candidate.derived_parameters)

    for parameter, value in parameter_updates.items():
        numeric_value = float(value)
        retention_policy[parameter] = numeric_value
        derived_parameters[parameter] = numeric_value

    return replace(
        parent_candidate,
        candidate_id=candidate_identifier(
            target_id=parent_candidate.target_id,
            strategy="corner-capture",
            revision=revision,
        ),
        revision=revision,
        retention_policy=retention_policy,
        derived_parameters=derived_parameters,
        automated_decision=automated_decision,
        created_at_utc=(parent_candidate.created_at_utc),
    )


def persist_candidate_revision(
    *,
    parent_candidate: CandidateRevision,
    candidate: CandidateRevision,
    relationship: RevisionRelationshipType,
    reason: str,
    output_directory: Path,
) -> RevisionRegistrationResult:
    """Persist one fully prepared candidate revision."""

    if candidate.target_id != parent_candidate.target_id:
        raise ValueError(
            "Candidate and parent must reference the same validation target"
        )

    if candidate.candidate_id == parent_candidate.candidate_id:
        raise ValueError("Candidate revision cannot reference itself")

    relationship_record = RevisionRelationship(
        schema_version="1.0.0",
        target_id=candidate.target_id,
        source_candidate_id=candidate.candidate_id,
        target_candidate_id=parent_candidate.candidate_id,
        relationship=relationship,
        reason=reason,
        created_at_utc=candidate.created_at_utc,
    )

    delta_report = compare_candidate_parameters(
        source_candidate_id=parent_candidate.candidate_id,
        target_candidate_id=candidate.candidate_id,
        source_parameters=(parent_candidate.derived_parameters),
        target_parameters=candidate.derived_parameters,
    )

    candidate_path = output_directory / "candidate.json"
    relationship_path = output_directory / "relationship.json"
    delta_path = output_directory / "parameter-delta.json"

    write_immutable_manifest(
        candidate,
        output_path=candidate_path,
    )

    write_revision_relationship(
        relationship_record,
        output_path=relationship_path,
    )

    write_revision_delta_report(
        delta_report,
        output_path=delta_path,
    )

    return RevisionRegistrationResult(
        candidate=candidate,
        relationship=relationship_record,
        delta_report=delta_report,
        candidate_path=candidate_path,
        relationship_path=relationship_path,
        delta_report_path=delta_path,
    )


def register_candidate_revision(
    *,
    parent_candidate: CandidateRevision,
    revision: str,
    parameter_updates: dict[str, float],
    relationship: RevisionRelationshipType,
    reason: str,
    output_directory: Path,
    automated_decision: str,
) -> RevisionRegistrationResult:
    candidate = derive_candidate_revision(
        parent_candidate=parent_candidate,
        revision=revision,
        parameter_updates=parameter_updates,
        automated_decision=automated_decision,
    )

    return persist_candidate_revision(
        parent_candidate=parent_candidate,
        candidate=candidate,
        relationship=relationship,
        reason=reason,
        output_directory=output_directory,
    )
