from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .corner_capture import CornerCapturePolicy, as_corner_capture_parameters
from .evidence_artifact import (
    ProductionEvidenceArtifact,
    generate_production_evidence_artifact,
)
from .export_validation import (
    ExportValidationRecord,
    ReferenceBoard,
    run_candidate_export_validation,
)
from .production_execution import (
    ProductionCornerExecutionRequest,
)
from .revision_history import (
    RevisionRelationshipType,
)
from .revision_registration import (
    RevisionRegistrationResult,
    derive_candidate_revision,
    persist_candidate_revision,
)
from .validation_fixture import (
    ValidationFixtureArtifact,
    ValidationFixturePolicy,
    export_validation_fixture,
)
from .validation_lab import (
    CandidateRevision,
    sha256_file,
)


@dataclass(frozen=True)
class ArtifactBackedRevisionResult:
    """Generated artifacts and immutable revision records."""

    registration: RevisionRegistrationResult
    evidence_artifact: ProductionEvidenceArtifact
    fixture_artifact: ValidationFixtureArtifact
    export_validation: ExportValidationRecord
    export_validation_path: Path

    @property
    def candidate(self) -> CandidateRevision:
        return self.registration.candidate


def register_artifact_backed_revision(
    *,
    parent_candidate: CandidateRevision,
    revision: str,
    parameter_updates: dict[str, float],
    relationship: RevisionRelationshipType,
    reason: str,
    output_directory: Path,
    source_step: Path,
    pcb_solid_index: int,
    git_commit: str,
    generator_version: str,
    created_at_utc: str,
    printer_profile: dict[str, Any],
    repository_root: Path = Path("."),
    fixture_policy: (ValidationFixturePolicy | None) = None,
    corner_keepout_mm: float = 4.0,
    vertical_margin_mm: float = 0.10,
) -> ArtifactBackedRevisionResult:
    """Generate and register one evidence-backed revision.

    The new candidate is export-validated immediately, with the embedded
    source board reported separately; a failing run is recorded and blocks
    promotion, not registration.
    """

    planned_candidate = derive_candidate_revision(
        parent_candidate=parent_candidate,
        revision=revision,
        parameter_updates=parameter_updates,
        automated_decision="artifact_generation_pending",
    )

    retention_step = output_directory / "retention.step"
    evidence_path = output_directory / "automated-validation.json"
    fixture_path = output_directory / "fixture.stl"
    validation_root = output_directory / "export-validation"
    manifest_paths = (
        output_directory / "candidate.json",
        output_directory / "relationship.json",
        output_directory / "parameter-delta.json",
    )

    output_paths = (
        retention_step,
        evidence_path,
        fixture_path,
        validation_root,
        *manifest_paths,
    )

    existing_paths = [path for path in output_paths if path.exists()]

    if existing_paths:
        names = ", ".join(str(path) for path in existing_paths)
        raise FileExistsError(
            f"Refusing to overwrite artifact-backed revision outputs: {names}"
        )

    policy = CornerCapturePolicy(
        arm_width_mm=float(planned_candidate.retention_policy["arm_width_mm"]),
        engagement_depth_mm=float(
            planned_candidate.retention_policy["engagement_depth_mm"]
        ),
        board_clearance_mm=float(
            planned_candidate.retention_policy["board_clearance_mm"]
        ),
        vertical_overlap_mm=float(
            planned_candidate.retention_policy["vertical_overlap_mm"]
        ),
        minimum_wall_mm=float(planned_candidate.retention_policy["minimum_wall_mm"]),
    )

    evidence_artifact = generate_production_evidence_artifact(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=pcb_solid_index,
            output_step=retention_step,
            policy=policy,
            corner_keepout_mm=corner_keepout_mm,
            vertical_margin_mm=vertical_margin_mm,
        ),
        report_path=evidence_path,
    )

    fixture_artifact = export_validation_fixture(
        evidence_artifact.execution,
        output_path=fixture_path,
        policy=(fixture_policy or ValidationFixturePolicy()),
    )

    parameters = as_corner_capture_parameters(
        evidence_artifact.execution.execution.parameters
    )

    candidate = replace(
        planned_candidate,
        source_sha256=sha256_file(source_step),
        output_sha256=sha256_file(retention_step),
        git_commit=git_commit,
        generator_version=generator_version,
        retention_policy={
            "arm_width_mm": parameters.arm_width_mm,
            "board_clearance_mm": (parameters.board_clearance_mm),
            "engagement_depth_mm": (parameters.engagement_depth_mm),
            "minimum_wall_mm": (parameters.minimum_wall_mm),
            "vertical_overlap_mm": (parameters.vertical_overlap_mm),
        },
        derived_parameters={
            "arm_width_mm": parameters.arm_width_mm,
            "board_clearance_mm": (parameters.board_clearance_mm),
            "board_thickness_mm": (parameters.board_thickness_mm),
            "engagement_depth_mm": (parameters.engagement_depth_mm),
            "minimum_wall_mm": (parameters.minimum_wall_mm),
            "vertical_overlap_mm": (parameters.vertical_overlap_mm),
        },
        selected_corners=tuple(
            corner.value
            for corner in (evidence_artifact.execution.derivation.selected_corners)
        ),
        automated_decision="verified_candidate",
        automated_evidence_path=str(evidence_path),
        fixture_artifact_path=str(fixture_path),
        created_at_utc=created_at_utc,
    )

    registration = persist_candidate_revision(
        parent_candidate=parent_candidate,
        candidate=candidate,
        relationship=relationship,
        reason=reason,
        output_directory=output_directory,
    )

    export_validation, export_validation_path = run_candidate_export_validation(
        candidate=registration.candidate,
        retention_step=retention_step,
        validation_root=validation_root,
        printer_profile=printer_profile,
        repository_root=repository_root,
        validated_at_utc=created_at_utc,
        reference_board=ReferenceBoard(
            source_step=source_step,
            pcb_solid_index=pcb_solid_index,
        ),
    )

    return ArtifactBackedRevisionResult(
        registration=registration,
        evidence_artifact=evidence_artifact,
        fixture_artifact=fixture_artifact,
        export_validation=export_validation,
        export_validation_path=export_validation_path,
    )
