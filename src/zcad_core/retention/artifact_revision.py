from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .corner_capture import (
    CornerCaptureParameters,
    CornerCapturePolicy,
    as_corner_capture_parameters,
)
from .edge_capture import (
    EdgeCaptureParameters,
    EdgeCapturePolicy,
    as_edge_capture_parameters,
)
from .edge_evidence_artifact import (
    ProductionEdgeEvidenceArtifact,
    generate_production_edge_evidence_artifact,
)
from .evidence_artifact import (
    ProductionEvidenceArtifact,
    generate_production_evidence_artifact,
    recorded_generation_parameters,
)
from .export_validation import (
    ExportValidationRecord,
    ReferenceBoard,
    run_candidate_export_validation,
)
from .production_edge_execution import ProductionEdgeExecutionRequest
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
    export_edge_validation_fixture,
    export_validation_fixture,
)
from .validation_lab import (
    CandidateRevision,
    candidate_identifier,
    sha256_file,
)

_POLICY_FIELDS = (
    "arm_width_mm",
    "board_clearance_mm",
    "engagement_depth_mm",
    "minimum_wall_mm",
    "vertical_overlap_mm",
)


# Every candidate generated before generation settings were recorded used
# this vertical margin; the corner keepout had no single value (see
# register_artifact_backed_revision).
_DEFAULT_VERTICAL_MARGIN_MM = 0.10
_DEFAULT_CORNER_KEEPOUT_MM = 4.0


@dataclass(frozen=True)
class ArtifactBackedRevisionResult:
    """Generated artifacts and immutable revision records."""

    registration: RevisionRegistrationResult
    evidence_artifact: ProductionEvidenceArtifact | ProductionEdgeEvidenceArtifact
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
    corner_keepout_mm: float | None = None,
    vertical_margin_mm: float | None = None,
) -> ArtifactBackedRevisionResult:
    """Generate and register one evidence-backed revision.

    Supports corner-capture and edge-clip parents. ``parameter_updates`` may
    be empty only when ``generator_version`` differs from the parent's, which
    regenerates the same policy with changed geometry code.

    The new candidate is export-validated immediately, with the embedded
    source board reported separately; a failing run is recorded and blocks
    promotion, not registration.

    ``corner_keepout_mm`` and ``vertical_margin_mm`` default to the values
    the parent's automated evidence recorded, so a revision is generated
    with the settings that chose its parent's capture locations. A
    corner-capture parent that predates that record must be given
    ``corner_keepout_mm`` explicitly: a default could select different
    corners or fail to find any (the XIAO ESP32-S3 needs 2.1 mm, not 4.0).
    """

    if parameter_updates:
        planned_candidate = derive_candidate_revision(
            parent_candidate=parent_candidate,
            revision=revision,
            parameter_updates=parameter_updates,
            automated_decision="artifact_generation_pending",
        )
    elif generator_version != parent_candidate.generator_version:
        # Regenerating the same policy with a changed generator is a real
        # revision: the geometry differs even though no parameter does.
        planned_candidate = replace(
            parent_candidate,
            candidate_id=candidate_identifier(
                target_id=parent_candidate.target_id,
                strategy=parent_candidate.strategy,
                revision=revision,
            ),
            revision=revision,
            automated_decision="artifact_generation_pending",
        )
    else:
        raise ValueError(
            "parameter_updates cannot be empty unless generator_version changes"
        )

    recorded = recorded_generation_parameters(
        Path(parent_candidate.automated_evidence_path)
    )

    if corner_keepout_mm is None:
        corner_keepout_mm = recorded.get("corner_keepout_mm")

    if corner_keepout_mm is None:
        if parent_candidate.strategy == "corner-capture":
            raise ValueError(
                f"{parent_candidate.candidate_id} does not record the corner "
                "keepout it was generated with; pass corner_keepout_mm "
                "explicitly"
            )

        corner_keepout_mm = _DEFAULT_CORNER_KEEPOUT_MM

    if vertical_margin_mm is None:
        vertical_margin_mm = recorded.get(
            "vertical_margin_mm", _DEFAULT_VERTICAL_MARGIN_MM
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

    policy_fields = {
        name: float(planned_candidate.retention_policy[name]) for name in _POLICY_FIELDS
    }
    fixture_policy = fixture_policy or ValidationFixturePolicy()

    evidence_artifact: ProductionEvidenceArtifact | ProductionEdgeEvidenceArtifact
    parameters: CornerCaptureParameters | EdgeCaptureParameters

    if planned_candidate.strategy == "corner-capture":
        evidence_artifact = generate_production_evidence_artifact(
            ProductionCornerExecutionRequest(
                source_step=source_step,
                pcb_solid_index=pcb_solid_index,
                output_step=retention_step,
                policy=CornerCapturePolicy(**policy_fields),
                corner_keepout_mm=corner_keepout_mm,
                vertical_margin_mm=vertical_margin_mm,
            ),
            report_path=evidence_path,
        )
        fixture_artifact = export_validation_fixture(
            evidence_artifact.execution,
            output_path=fixture_path,
            policy=fixture_policy,
        )
        parameters = as_corner_capture_parameters(
            evidence_artifact.execution.execution.parameters
        )
        selected = tuple(
            corner.value
            for corner in evidence_artifact.execution.derivation.selected_corners
        )
    elif planned_candidate.strategy == "edge-clip":
        edge_policy = EdgeCapturePolicy(**policy_fields)
        edge_artifact = generate_production_edge_evidence_artifact(
            ProductionEdgeExecutionRequest(
                source_step=source_step,
                pcb_solid_index=pcb_solid_index,
                output_step=retention_step,
                policy=edge_policy,
                engagement_depth_mm=edge_policy.engagement_depth_mm,
                vertical_margin_mm=vertical_margin_mm,
            ),
            report_path=evidence_path,
        )
        evidence_artifact = edge_artifact
        fixture_artifact = export_edge_validation_fixture(
            edge_artifact.execution,
            output_path=fixture_path,
            policy=fixture_policy,
        )
        parameters = as_edge_capture_parameters(
            edge_artifact.execution.execution.parameters
        )
        selected = (edge_artifact.execution.derivation.selected_edge.value,)
    else:
        raise ValueError(
            f"Artifact-backed revisions do not support strategy: "
            f"{planned_candidate.strategy}"
        )

    retention_policy = {name: getattr(parameters, name) for name in _POLICY_FIELDS}

    candidate = replace(
        planned_candidate,
        source_sha256=sha256_file(source_step),
        output_sha256=sha256_file(retention_step),
        git_commit=git_commit,
        generator_version=generator_version,
        retention_policy=retention_policy,
        derived_parameters={
            **retention_policy,
            "board_thickness_mm": parameters.board_thickness_mm,
        },
        selected_corners=selected,
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
