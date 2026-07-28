from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .revision_history import (
    RevisionDeltaReport,
    RevisionRelationship,
)
from .validation_lab import CandidateRevision


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
