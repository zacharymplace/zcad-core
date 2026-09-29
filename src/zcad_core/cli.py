"""Validation Lab command-line interface.

Thin argparse wrapper over the already-tested ``zcad_core.retention``
lifecycle functions. Every command reads and writes explicit file paths;
none of them infer a directory layout beyond what a caller passes in,
except ``status``, ``report``, and ``candidate promote``, which read (never
write) a ``--target-root`` to discover existing candidates, promotions, and
visual reviews (``report`` looks for ``visual-review.json`` beside each
candidate manifest), and
``candidate register``, which writes its export-validation run beside the
candidate manifest in ``export-validation/``; ``candidate derive`` does the
same inside ``--output-directory``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.retention import (
    UNRECORDED_SLICER_PROFILE,
    CandidateRevision,
    CornerCapturePolicy,
    EdgeCapturePolicy,
    PhysicalMeasurement,
    PhysicalTrialManifest,
    PhysicalValidationCheck,
    PhysicalValidationDisposition,
    PhysicalValidationObservation,
    ProductionCornerExecutionRequest,
    ProductionEdgeExecutionRequest,
    PromotionDecision,
    PromotionRecord,
    ReferenceBoard,
    RevisionRelationshipType,
    ValidationFixturePolicy,
    ValidationTarget,
    VisualReviewCheck,
    VisualReviewDisposition,
    VisualReviewObservation,
    candidate_identifier,
    compare_candidate_revisions,
    complete_physical_validation_record,
    complete_visual_review_record,
    create_pending_physical_validation_record,
    execute_production_corner_capture,
    execute_production_edge_capture,
    export_edge_validation_fixture,
    export_validation_fixture,
    generate_production_edge_evidence_artifact,
    generate_production_evidence_artifact,
    load_candidate_revision,
    load_manifest,
    load_physical_validation_record,
    load_visual_review_record,
    promote_preferred_revision,
    recommend_revision,
    register_candidate_revision,
    run_candidate_export_validation,
    select_preferred_revision,
    sha256_file,
    write_immutable_manifest,
    write_physical_validation_record,
    write_revision_comparison_report,
    write_revision_recommendation,
    write_visual_review_record,
)

_STRATEGIES = ("corner-capture", "edge-clip")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_validation_target(path: Path) -> ValidationTarget:
    payload = load_manifest(path)

    return ValidationTarget(
        schema_version=str(payload["schema_version"]),
        target_id=str(payload["target_id"]),
        display_name=str(payload["display_name"]),
        manufacturer=str(payload["manufacturer"]),
        product_family=str(payload["product_family"]),
        source_model_path=str(payload["source_model_path"]),
        source_model_sha256=str(payload["source_model_sha256"]),
        pcb_solid_index=int(payload["pcb_solid_index"]),
        created_at_utc=str(payload["created_at_utc"]),
    )


def _load_physical_trial_manifest(path: Path) -> PhysicalTrialManifest:
    payload = load_manifest(path)

    disposition = str(payload["disposition"])
    complete = bool(payload["complete"])
    passed = bool(payload["passed"])

    # Trials registered before the explicit pending disposition copied a
    # placeholder "revise" from an unprinted record. The manifest is
    # immutable, so read the referenced record to tell them apart.
    if (
        disposition == PhysicalValidationDisposition.REVISE.value
        and _references_pending_record(
            manifest_path=path,
            record_path=Path(str(payload["physical_validation_path"])),
        )
    ):
        disposition = PhysicalValidationDisposition.PENDING.value
        complete = False
        passed = False

    return PhysicalTrialManifest(
        schema_version=str(payload["schema_version"]),
        trial_id=str(payload["trial_id"]),
        candidate_id=str(payload["candidate_id"]),
        physical_validation_path=str(payload["physical_validation_path"]),
        fixture_artifact_path=str(payload["fixture_artifact_path"]),
        printer_profile=str(payload["printer_profile"]),
        material_profile=str(payload["material_profile"]),
        slicer_profile=str(payload.get("slicer_profile", UNRECORDED_SLICER_PROFILE)),
        disposition=disposition,
        complete=complete,
        passed=passed,
        created_at_utc=str(payload["created_at_utc"]),
    )


def _references_pending_record(*, manifest_path: Path, record_path: Path) -> bool:
    """Whether a trial manifest points at a still-pending validation record.

    Recorded paths are repository-relative, so when the working directory
    is not the repository root, resolve against the manifest's ancestors.
    A record that cannot be found leaves the manifest as recorded.
    """

    candidates = [record_path]

    if not record_path.is_absolute():
        candidates.extend(
            parent / record_path for parent in manifest_path.resolve().parents
        )

    for candidate in candidates:
        if candidate.is_file():
            return load_physical_validation_record(candidate).pending

    return False


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)

    return str(value) if value is not None else None


def _load_promotion_record(path: Path) -> PromotionRecord:
    payload = load_manifest(path)

    return PromotionRecord(
        schema_version=str(payload["schema_version"]),
        target_id=str(payload["target_id"]),
        candidate_id=str(payload["candidate_id"]),
        decision=PromotionDecision(payload["decision"]),
        reason=str(payload["reason"]),
        reviewer=str(payload["reviewer"]),
        automated_validation_passed=bool(payload["automated_validation_passed"]),
        physical_validation_passed=bool(payload["physical_validation_passed"]),
        candidate_manifest_path=str(payload["candidate_manifest_path"]),
        physical_trial_path=str(payload["physical_trial_path"]),
        created_at_utc=str(payload["created_at_utc"]),
        relationship_path=_optional_str(payload, "relationship_path"),
        parameter_delta_path=_optional_str(payload, "parameter_delta_path"),
        supersedes_candidate_id=_optional_str(payload, "supersedes_candidate_id"),
        export_validation_path=_optional_str(payload, "export_validation_path"),
        visual_review_path=_optional_str(payload, "visual_review_path"),
    )


def _scan_target_promotions(
    target_root: Path,
) -> tuple[PromotionRecord, ...]:
    """Discover existing promotion records under a target root.

    Deliberately does not look at ``relationship.json`` files: those record
    derive-time revision lineage, not promotion supersession. See
    ``PromotionRecord.supersedes_candidate_id`` and
    ``select_preferred_revision`` in ``zcad_core.retention.promotion``.
    """

    candidates_root = target_root / "candidates"

    if not candidates_root.is_dir():
        return ()

    return tuple(
        _load_promotion_record(path)
        for path in sorted(candidates_root.glob("*/promotion.json"))
    )


# --- target -----------------------------------------------------------------


def _target_register(args: argparse.Namespace) -> int:
    target = ValidationTarget(
        schema_version="1.0.0",
        target_id=args.target_id,
        display_name=args.display_name,
        manufacturer=args.manufacturer,
        product_family=args.product_family,
        source_model_path=str(args.source_model_path),
        source_model_sha256=sha256_file(args.source_model_path),
        pcb_solid_index=args.pcb_solid_index,
        created_at_utc=(args.created_at_utc or _now()),
    )

    write_immutable_manifest(
        target,
        output_path=args.output,
    )

    _emit(
        {
            "target_id": target.target_id,
            "source_model_sha256": target.source_model_sha256,
            "manifest": str(args.output),
        }
    )

    return 0


def _build_capture_policy(
    args: argparse.Namespace,
) -> CornerCapturePolicy | EdgeCapturePolicy:
    """Build the geometry policy for whichever strategy was requested.

    CornerCapturePolicy and EdgeCapturePolicy share the same five field
    names by design (see edge_capture.py), so both strategies read from
    one set of CLI flags rather than needing strategy-specific ones.
    """

    fields = {
        "arm_width_mm": args.arm_width_mm,
        "engagement_depth_mm": args.engagement_depth_mm,
        "board_clearance_mm": args.board_clearance_mm,
        "vertical_overlap_mm": args.vertical_overlap_mm,
        "minimum_wall_mm": args.minimum_wall_mm,
    }
    fields = {key: value for key, value in fields.items() if value is not None}

    if args.strategy == "corner-capture":
        return CornerCapturePolicy(**fields)

    return EdgeCapturePolicy(**fields)


# --- candidate ----------------------------------------------------------------


def _candidate_create(args: argparse.Namespace) -> int:
    """Execute retention geometry generation and write automated evidence."""

    policy = _build_capture_policy(args)

    if args.strategy == "corner-capture":
        assert isinstance(policy, CornerCapturePolicy)
        corner_artifact = generate_production_evidence_artifact(
            ProductionCornerExecutionRequest(
                source_step=args.source_step,
                pcb_solid_index=args.pcb_solid_index,
                output_step=args.output_step,
                policy=policy,
            ),
            report_path=args.report_output,
        )

        _emit(
            {
                "passed": corner_artifact.passed,
                "strategy": args.strategy,
                "selected": [
                    corner.value
                    for corner in (
                        corner_artifact.execution.derivation.selected_corners
                    )
                ],
                "step": str(corner_artifact.step_path),
                "report": str(corner_artifact.report_path),
            }
        )

        return 0

    assert isinstance(policy, EdgeCapturePolicy)
    edge_artifact = generate_production_edge_evidence_artifact(
        ProductionEdgeExecutionRequest(
            source_step=args.source_step,
            pcb_solid_index=args.pcb_solid_index,
            output_step=args.output_step,
            policy=policy,
        ),
        report_path=args.report_output,
    )

    _emit(
        {
            "passed": edge_artifact.passed,
            "strategy": args.strategy,
            "selected": [edge_artifact.execution.derivation.selected_edge.value],
            "step": str(edge_artifact.step_path),
            "report": str(edge_artifact.report_path),
        }
    )

    return 0


def _candidate_register(args: argparse.Namespace) -> int:
    """Register the first (root) candidate revision from generated evidence."""

    target = _load_validation_target(args.target_manifest)
    evidence = load_manifest(args.automated_evidence)

    policy = evidence["policy"]
    pcb = evidence["pcb"]
    selected = evidence["selected_corners"]

    if not isinstance(policy, dict) or not isinstance(pcb, dict):
        raise TypeError("Automated evidence policy and pcb sections must be objects")

    if not isinstance(selected, list):
        raise TypeError("Automated evidence selected_corners must be a list")

    retention_policy = {str(key): float(value) for key, value in policy.items()}
    derived_parameters: dict[str, Any] = {
        "board_thickness_mm": float(pcb["z_length_mm"]),
        **retention_policy,
    }

    candidate = CandidateRevision(
        schema_version="1.0.0",
        candidate_id=candidate_identifier(
            target_id=target.target_id,
            strategy=args.strategy,
            revision=args.revision,
        ),
        target_id=target.target_id,
        revision=args.revision,
        source_sha256=target.source_model_sha256,
        output_sha256=sha256_file(args.retention_step),
        git_commit=args.git_commit,
        generator_version=args.generator_version,
        retention_policy=retention_policy,
        derived_parameters=derived_parameters,
        selected_corners=tuple(str(value) for value in selected),
        automated_decision=str(evidence["decision"]),
        automated_evidence_path=str(args.automated_evidence),
        fixture_artifact_path=str(args.fixture),
        created_at_utc=(args.created_at_utc or _now()),
        strategy=args.strategy,
    )

    write_immutable_manifest(
        candidate,
        output_path=args.output,
    )

    # Every registered candidate carries export-validation evidence; a failing
    # run is still recorded and blocks promotion rather than registration.
    record, record_path = run_candidate_export_validation(
        candidate=candidate,
        retention_step=args.retention_step,
        validation_root=args.output.parent / "export-validation",
        printer_profile=load_manifest(args.printer_profile),
        repository_root=args.repository_root,
        validated_at_utc=_now(),
        reference_board=(
            None if args.no_embedded_board else ReferenceBoard.from_target(target)
        ),
    )

    _emit(
        {
            "candidate_id": candidate.candidate_id,
            "automated_decision": candidate.automated_decision,
            "manifest": str(args.output),
            "export_validation_status": record.evaluated_status,
            "export_validation_record": str(record_path),
        }
    )

    return 0 if record.evaluated_status == "PASS" else 1


def _candidate_derive(args: argparse.Namespace) -> int:
    parent = load_candidate_revision(args.parent)

    parameter_updates: dict[str, float] = {}

    for assignment in args.set:
        key, separator, value = assignment.partition("=")

        if not separator:
            raise ValueError(f"--set must be KEY=VALUE, got: {assignment}")

        parameter_updates[key] = float(value)

    # Check before registering so a wrong STEP leaves no unvalidated candidate.
    if sha256_file(args.retention_step) != parent.output_sha256:
        raise ValueError(
            "Retention STEP does not match candidate output_sha256: "
            f"{args.retention_step}"
        )

    result = register_candidate_revision(
        parent_candidate=parent,
        revision=args.revision,
        parameter_updates=parameter_updates,
        relationship=RevisionRelationshipType(args.relationship),
        reason=args.reason,
        output_directory=args.output_directory,
        automated_decision=args.automated_decision,
    )

    # Derived revisions reuse the parent's retention STEP; the hash check in
    # export validation confirms it is that exact file.
    record, record_path = run_candidate_export_validation(
        candidate=result.candidate,
        retention_step=args.retention_step,
        validation_root=args.output_directory / "export-validation",
        printer_profile=load_manifest(args.printer_profile),
        repository_root=args.repository_root,
        validated_at_utc=_now(),
        reference_board=_reference_board(args.target_manifest, result.candidate),
    )

    _emit(
        {
            "candidate_id": result.candidate.candidate_id,
            "relationship": result.relationship.relationship.value,
            "changed_parameters": [
                change.parameter for change in result.delta_report.changes
            ],
            "candidate_manifest": str(result.candidate_path),
            "relationship_manifest": str(result.relationship_path),
            "parameter_delta_report": str(result.delta_report_path),
            "export_validation_status": record.evaluated_status,
            "export_validation_record": str(record_path),
        }
    )

    return 0 if record.evaluated_status == "PASS" else 1


def _candidate_inspect(args: argparse.Namespace) -> int:
    payload = load_manifest(args.manifest)

    print(json.dumps(payload, indent=2, sort_keys=True))

    return 0


def _reference_board(
    target_manifest: Path | None,
    candidate: CandidateRevision,
) -> ReferenceBoard | None:
    if target_manifest is None:
        return None

    target = _load_validation_target(target_manifest)

    if target.target_id != candidate.target_id:
        raise ValueError("Target manifest does not match candidate target_id")

    return ReferenceBoard.from_target(target)


def _candidate_revalidate(args: argparse.Namespace) -> int:
    """Run the export pipeline on a candidate without altering prior evidence."""

    candidate = load_candidate_revision(args.candidate_manifest)

    record, record_path = run_candidate_export_validation(
        candidate=candidate,
        retention_step=args.retention_step,
        validation_root=args.validation_root,
        printer_profile=load_manifest(args.printer_profile),
        repository_root=args.repository_root,
        validated_at_utc=_now(),
        reference_board=_reference_board(args.target_manifest, candidate),
    )

    _emit(
        {
            "candidate_id": record.candidate_id,
            "run_id": record.run_id,
            "evaluated_status": record.evaluated_status,
            "artifacts": {
                artifact.role: artifact.evaluated_status
                for artifact in record.artifacts
            },
            "non_gating_roles": [
                artifact.role for artifact in record.artifacts if not artifact.gating
            ],
            "export_validation_record": str(record_path),
        }
    )

    return 0 if record.evaluated_status == "PASS" else 1


def _candidate_promote(args: argparse.Namespace) -> int:
    existing_promotions = _scan_target_promotions(args.target_root)

    candidate = load_candidate_revision(args.candidate_manifest)

    record = PromotionRecord(
        schema_version="1.0.0",
        target_id=candidate.target_id,
        candidate_id=candidate.candidate_id,
        decision=PromotionDecision(args.decision),
        reason=args.reason,
        reviewer=args.reviewer,
        # Derived from recorded evidence, never asserted by the operator; the
        # export-validation record is verified separately at registration.
        automated_validation_passed=(
            candidate.automated_decision == "verified_candidate"
        ),
        physical_validation_passed=args.physical_validation_passed,
        candidate_manifest_path=str(args.candidate_manifest),
        relationship_path=(
            str(args.relationship_path) if args.relationship_path is not None else None
        ),
        parameter_delta_path=(
            str(args.parameter_delta_path)
            if args.parameter_delta_path is not None
            else None
        ),
        physical_trial_path=str(args.physical_trial_path),
        created_at_utc=_now(),
        supersedes_candidate_id=args.supersedes_candidate_id,
        export_validation_path=(
            str(args.export_validation) if args.export_validation is not None else None
        ),
        visual_review_path=(
            str(args.visual_review) if args.visual_review is not None else None
        ),
    )

    result = promote_preferred_revision(
        record=record,
        output_path=args.output,
        existing_promotion_records=existing_promotions,
    )

    _emit(
        {
            "candidate_id": result.candidate_id,
            "decision": result.decision.value,
            "promotion_manifest": str(args.output),
            "superseded": result.supersedes_candidate_id,
        }
    )

    return 0


# --- fixture ------------------------------------------------------------------


def _fixture_export(args: argparse.Namespace) -> int:
    """Re-execute retention geometry and export a printable STL fixture.

    Retention execution results (board model, derivation, geometry) are
    not persisted artifacts on their own - only the STEP and JSON evidence
    ``candidate create`` writes are. Exporting a fixture re-runs the same
    deterministic execution from ``--source-step`` rather than reading
    those files back in, mirroring how the existing per-board generation
    scripts (e.g. scripts/generate-*-physical-validation.py) work.
    """

    policy = _build_capture_policy(args)
    fixture_policy = ValidationFixturePolicy(
        base_thickness_mm=args.base_thickness_mm,
        perimeter_margin_mm=args.perimeter_margin_mm,
    )

    if args.strategy == "corner-capture":
        assert isinstance(policy, CornerCapturePolicy)
        execution = execute_production_corner_capture(
            ProductionCornerExecutionRequest(
                source_step=args.source_step,
                pcb_solid_index=args.pcb_solid_index,
                output_step=args.output_step,
                policy=policy,
            )
        )
        fixture = export_validation_fixture(
            execution,
            output_path=args.output,
            policy=fixture_policy,
        )
    else:
        assert isinstance(policy, EdgeCapturePolicy)
        edge_execution = execute_production_edge_capture(
            ProductionEdgeExecutionRequest(
                source_step=args.source_step,
                pcb_solid_index=args.pcb_solid_index,
                output_step=args.output_step,
                policy=policy,
            )
        )
        fixture = export_edge_validation_fixture(
            edge_execution,
            output_path=args.output,
            policy=fixture_policy,
        )

    _emit(
        {
            "strategy": args.strategy,
            "fixture": str(fixture.stl_path),
        }
    )

    return 0


# --- trial --------------------------------------------------------------------


def _trial_start(args: argparse.Namespace) -> int:
    record = create_pending_physical_validation_record(
        candidate_report_path=args.candidate_report,
        fixture_stl_path=args.fixture_stl,
        printer_profile=args.printer_profile,
        material_profile=args.material_profile,
        slicer_profile=args.slicer_profile,
    )

    write_physical_validation_record(
        record,
        output_path=args.output,
    )

    _emit(
        {
            "disposition": record.disposition.value,
            "pending": record.pending,
            "complete": record.complete,
            "record": str(args.output),
        }
    )

    return 0


def _load_measurements(path: Path | None) -> tuple[PhysicalMeasurement, ...]:
    """Read ``{"<name>": {"value_mm": 0.8, "nominal_mm": 0.85, "notes": ""}}``.

    A template entry left at ``"value_mm": null`` is refused rather than
    skipped, so an unmeasured quantity cannot pass as recorded.
    """

    if path is None:
        return ()

    payload = load_manifest(path)
    measurements = []

    for name, entry in payload.items():
        if not isinstance(entry, dict) or entry.get("value_mm") is None:
            raise ValueError(
                f"Measurement {name} has no value_mm; fill it in or remove it"
            )

        nominal = entry.get("nominal_mm")
        measurements.append(
            PhysicalMeasurement(
                name=name,
                value_mm=float(entry["value_mm"]),
                nominal_mm=None if nominal is None else float(nominal),
                notes=str(entry.get("notes", "")),
            )
        )

    return tuple(measurements)


def _trial_complete(args: argparse.Namespace) -> int:
    answers = load_manifest(args.observations)
    expected = {check.value for check in PhysicalValidationCheck}
    missing = sorted(expected - set(answers))
    unknown = sorted(set(answers) - expected)

    if missing or unknown:
        raise ValueError(
            "--observations must answer every physical check exactly; "
            f"missing: {missing or 'none'}, unknown: {unknown or 'none'}"
        )

    observations = []

    for check in PhysicalValidationCheck:
        answer = answers[check.value]

        if not isinstance(answer, dict) or not isinstance(answer.get("passed"), bool):
            raise TypeError(f"{check.value} needs a boolean 'passed' field")

        observations.append(
            PhysicalValidationObservation(
                check=check,
                passed=answer["passed"],
                notes=str(answer.get("notes", "")),
            )
        )

    record = complete_physical_validation_record(
        candidate_report_path=args.candidate_report,
        fixture_stl_path=args.fixture_stl,
        printer_profile=args.printer_profile,
        material_profile=args.material_profile,
        slicer_profile=args.slicer_profile,
        observations=tuple(observations),
        disposition=PhysicalValidationDisposition(args.disposition),
        operator_notes=args.operator_notes,
        measurements=_load_measurements(args.measurements),
    )

    write_physical_validation_record(
        record,
        output_path=args.output,
    )

    _emit(
        {
            "disposition": record.disposition.value,
            "complete": record.complete,
            "passed": record.passed,
            "measurements": {
                measurement.name: {
                    "value_mm": measurement.value_mm,
                    "deviation_mm": measurement.deviation_mm,
                }
                for measurement in record.measurements
            },
            "record": str(args.output),
        }
    )

    return 0


def _trial_register(args: argparse.Namespace) -> int:
    candidate = load_candidate_revision(args.candidate_manifest)
    physical = load_physical_validation_record(args.physical_validation_record)

    trial = PhysicalTrialManifest(
        schema_version="1.0.0",
        trial_id=args.trial_id,
        candidate_id=candidate.candidate_id,
        physical_validation_path=str(args.physical_validation_record),
        fixture_artifact_path=str(args.fixture),
        printer_profile=physical.printer_profile,
        material_profile=physical.material_profile,
        slicer_profile=physical.slicer_profile,
        disposition=physical.disposition.value,
        complete=physical.complete,
        passed=physical.passed,
        created_at_utc=physical.completed_at_utc.strip() or _now(),
    )

    write_immutable_manifest(
        trial,
        output_path=args.output,
    )

    _emit(
        {
            "trial_id": trial.trial_id,
            "candidate_id": trial.candidate_id,
            "pending": trial.pending,
            "passed": trial.passed,
            "manifest": str(args.output),
        }
    )

    return 0


# --- review -------------------------------------------------------------------


def _review_complete(args: argparse.Namespace) -> int:
    """Record a human visual review of a candidate's design-review package.

    Every check must be answered, so a review cannot skip the fused-feature
    check that would have caught floating ledges. A passing disposition is
    refused when any check failed or the design review's own geometry checks
    did not pass.
    """

    candidate = load_candidate_revision(args.candidate_manifest)
    disposition = VisualReviewDisposition(args.disposition)

    design_review = load_manifest(args.design_review)
    installation = load_manifest(args.installation_path_report)

    if str(installation.get("candidate_id")) != candidate.candidate_id:
        raise ValueError(
            "Installation-path report belongs to "
            f"{installation.get('candidate_id')}, not {candidate.candidate_id}"
        )

    if disposition in {
        VisualReviewDisposition.PASS,
        VisualReviewDisposition.PASS_WITH_RESERVATIONS,
    } and (design_review.get("passed") is not True):
        raise ValueError(
            "The design review's geometry checks did not pass, so a visual "
            f"review cannot record {disposition.value}"
        )

    answers = load_manifest(args.observations)
    expected = {check.value for check in VisualReviewCheck}
    missing = sorted(expected - set(answers))
    unknown = sorted(set(answers) - expected)

    if missing or unknown:
        raise ValueError(
            "--observations must answer every visual-review check exactly; "
            f"missing: {missing or 'none'}, unknown: {unknown or 'none'}"
        )

    observations = []

    for check in VisualReviewCheck:
        answer = answers[check.value]

        if not isinstance(answer, dict) or not isinstance(answer.get("passed"), bool):
            raise TypeError(f"{check.value} needs a boolean 'passed' field")

        observations.append(
            VisualReviewObservation(
                check=check,
                passed=answer["passed"],
                notes=str(answer.get("notes", "")),
            )
        )

    record = complete_visual_review_record(
        candidate_id=candidate.candidate_id,
        design_review_path=args.design_review,
        installation_path_report_path=args.installation_path_report,
        reviewer=args.reviewer,
        observations=tuple(observations),
        disposition=disposition,
        reviewer_notes=args.reviewer_notes,
    )

    write_visual_review_record(
        record,
        output_path=args.output,
    )

    _emit(
        {
            "candidate_id": record.candidate_id,
            "disposition": record.disposition.value,
            "passed": record.passed,
            "conditional": record.conditional,
            "record": str(args.output),
        }
    )

    return 0


# --- revision -------------------------------------------------------------------


def _revision_compare(args: argparse.Namespace) -> int:
    source = load_candidate_revision(args.source_candidate)
    target = load_candidate_revision(args.target_candidate)

    source_trial = (
        _load_physical_trial_manifest(args.source_trial)
        if args.source_trial is not None
        else None
    )
    target_trial = (
        _load_physical_trial_manifest(args.target_trial)
        if args.target_trial is not None
        else None
    )

    report = compare_candidate_revisions(
        source=source,
        target=target,
        source_trial=source_trial,
        target_trial=target_trial,
    )
    recommendation = recommend_revision(report)

    write_revision_comparison_report(
        report,
        output_path=args.report_output,
    )
    write_revision_recommendation(
        recommendation,
        output_path=args.recommendation_output,
    )

    _emit(
        {
            "decision": recommendation.decision.value,
            "rationale": recommendation.rationale,
            "report": str(args.report_output),
            "recommendation": str(args.recommendation_output),
        }
    )

    return 0


# --- status -----------------------------------------------------------------


def _status(args: argparse.Namespace) -> int:
    target = _load_validation_target(args.target_root / "target.json")

    candidate_paths = sorted((args.target_root / "candidates").glob("*/candidate.json"))
    candidates = tuple(load_candidate_revision(path) for path in candidate_paths)

    promotions = _scan_target_promotions(args.target_root)

    preferred = select_preferred_revision(
        target_id=target.target_id,
        promotion_records=promotions,
    )

    _emit(
        {
            "target_id": target.target_id,
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "revision": candidate.revision,
                    "automated_decision": candidate.automated_decision,
                }
                for candidate in candidates
            ],
            "preferred_candidate_id": (
                preferred.candidate_id if preferred is not None else None
            ),
            "publication_eligible": (
                preferred is not None
                and preferred.decision is PromotionDecision.PROMOTED
            ),
        }
    )

    return 0


# --- report -------------------------------------------------------------------


def _report(args: argparse.Namespace) -> int:
    """Aggregate a target's full recorded history into one view.

    Unlike ``status`` (current preference and eligibility only), this
    walks every candidate's trials and promotion record too - a rollup
    for human review, not a decision input.
    """

    target = _load_validation_target(args.target_root / "target.json")

    candidates_root = args.target_root / "candidates"
    candidate_paths = sorted(candidates_root.glob("*/candidate.json"))
    candidates = tuple(load_candidate_revision(path) for path in candidate_paths)
    review_paths = {
        candidate.candidate_id: path.parent / "visual-review.json"
        for candidate, path in zip(candidates, candidate_paths, strict=True)
    }

    trial_paths = sorted(candidates_root.glob("*/trials/*/trial.json"))
    trials = tuple(_load_physical_trial_manifest(path) for path in trial_paths)

    trials_by_candidate: dict[str, list[PhysicalTrialManifest]] = {}

    for trial in trials:
        trials_by_candidate.setdefault(trial.candidate_id, []).append(trial)

    promotions = _scan_target_promotions(args.target_root)
    promotion_by_candidate = {
        promotion.candidate_id: promotion for promotion in promotions
    }

    preferred = select_preferred_revision(
        target_id=target.target_id,
        promotion_records=promotions,
    )

    candidate_reports = []

    for candidate in candidates:
        candidate_trials = trials_by_candidate.get(candidate.candidate_id, [])
        promotion = promotion_by_candidate.get(candidate.candidate_id)
        # Pending trials have no outcome yet; only completed trials count.
        completed_trials = [trial for trial in candidate_trials if trial.complete]

        review_path = review_paths[candidate.candidate_id]
        review = (
            load_visual_review_record(review_path) if review_path.is_file() else None
        )

        candidate_reports.append(
            {
                "candidate_id": candidate.candidate_id,
                "revision": candidate.revision,
                "strategy": candidate.strategy,
                "automated_decision": candidate.automated_decision,
                "trial_count": len(candidate_trials),
                "trials_pending": sum(1 for trial in candidate_trials if trial.pending),
                "trials_completed": len(completed_trials),
                "trials_passed": sum(1 for trial in completed_trials if trial.passed),
                "trial_outcomes": {
                    disposition.value: sum(
                        1
                        for trial in completed_trials
                        if trial.disposition == disposition.value
                    )
                    for disposition in PhysicalValidationDisposition
                    if disposition is not PhysicalValidationDisposition.PENDING
                },
                "visual_review": (
                    None
                    if review is None
                    else {
                        "disposition": review.disposition.value,
                        "passed": review.passed,
                        "schema_version": review.schema_version,
                        "reviewer": review.reviewer,
                    }
                ),
                "promotion": (
                    None
                    if promotion is None
                    else {
                        "decision": promotion.decision.value,
                        "reviewer": promotion.reviewer,
                        "reason": promotion.reason,
                        "supersedes_candidate_id": (promotion.supersedes_candidate_id),
                    }
                ),
            }
        )

    _emit(
        {
            "target_id": target.target_id,
            "display_name": target.display_name,
            "candidate_count": len(candidates),
            "candidates": candidate_reports,
            "preferred_candidate_id": (
                preferred.candidate_id if preferred is not None else None
            ),
            "publication_eligible": (
                preferred is not None
                and preferred.decision is PromotionDecision.PROMOTED
            ),
        }
    )

    return 0


# --- parser -------------------------------------------------------------------


def _add_capture_policy_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Add the flags shared by ``candidate create`` and ``fixture export``.

    CornerCapturePolicy and EdgeCapturePolicy share these five field
    names; the target strategy decides which dataclass they build. All
    default to None so omitting a flag falls back to that policy's own
    default rather than a CLI-level duplicate of it.
    """

    parser.add_argument(
        "--strategy",
        default="corner-capture",
        choices=_STRATEGIES,
    )
    parser.add_argument("--source-step", required=True, type=Path)
    parser.add_argument("--pcb-solid-index", required=True, type=int)
    parser.add_argument("--output-step", required=True, type=Path)
    parser.add_argument("--arm-width-mm", type=float)
    parser.add_argument("--engagement-depth-mm", type=float)
    parser.add_argument("--board-clearance-mm", type=float)
    parser.add_argument("--vertical-overlap-mm", type=float)
    parser.add_argument("--minimum-wall-mm", type=float)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zcad-validation")
    subcommands = parser.add_subparsers(dest="command", required=True)

    target = subcommands.add_parser("target")
    target_commands = target.add_subparsers(dest="subcommand", required=True)

    target_register = target_commands.add_parser("register")
    target_register.add_argument("--target-id", required=True)
    target_register.add_argument("--display-name", required=True)
    target_register.add_argument("--manufacturer", required=True)
    target_register.add_argument("--product-family", required=True)
    target_register.add_argument("--source-model-path", required=True, type=Path)
    target_register.add_argument("--pcb-solid-index", required=True, type=int)
    target_register.add_argument("--created-at-utc")
    target_register.add_argument("--output", required=True, type=Path)
    target_register.set_defaults(handler=_target_register)

    candidate = subcommands.add_parser("candidate")
    candidate_commands = candidate.add_subparsers(dest="subcommand", required=True)

    candidate_create = candidate_commands.add_parser("create")
    _add_capture_policy_arguments(candidate_create)
    candidate_create.add_argument("--report-output", required=True, type=Path)
    candidate_create.set_defaults(handler=_candidate_create)

    candidate_register = candidate_commands.add_parser("register")
    candidate_register.add_argument("--target-manifest", required=True, type=Path)
    candidate_register.add_argument("--automated-evidence", required=True, type=Path)
    candidate_register.add_argument("--retention-step", required=True, type=Path)
    candidate_register.add_argument("--fixture", required=True, type=Path)
    candidate_register.add_argument("--revision", required=True)
    candidate_register.add_argument(
        "--strategy",
        default="corner-capture",
        help=(
            "Retention strategy that produced this candidate's evidence "
            "(e.g. corner-capture, edge-clip). Part of the candidate id."
        ),
    )
    candidate_register.add_argument("--git-commit", required=True)
    candidate_register.add_argument("--generator-version", default="1.0.0")
    candidate_register.add_argument("--created-at-utc")
    candidate_register.add_argument("--printer-profile", required=True, type=Path)
    candidate_register.add_argument(
        "--no-embedded-board",
        action="store_true",
        help=(
            "The retention STEP does not embed the target PCB (e.g. snap-shell "
            "wearables), so all of its geometry gates export validation."
        ),
    )
    candidate_register.add_argument("--repository-root", default=Path("."), type=Path)
    candidate_register.add_argument("--output", required=True, type=Path)
    candidate_register.set_defaults(handler=_candidate_register)

    candidate_derive = candidate_commands.add_parser("derive")
    candidate_derive.add_argument("--parent", required=True, type=Path)
    candidate_derive.add_argument("--revision", required=True)
    candidate_derive.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        dest="set",
    )
    candidate_derive.add_argument(
        "--relationship",
        required=True,
        choices=[member.value for member in RevisionRelationshipType],
    )
    candidate_derive.add_argument("--reason", required=True)
    candidate_derive.add_argument("--automated-decision", required=True)
    candidate_derive.add_argument("--output-directory", required=True, type=Path)
    candidate_derive.add_argument(
        "--retention-step",
        required=True,
        type=Path,
        help="The parent's retention STEP; must match its output_sha256.",
    )
    candidate_derive.add_argument("--printer-profile", required=True, type=Path)
    candidate_derive.add_argument(
        "--target-manifest",
        type=Path,
        help="Separate the embedded target PCB, as in 'candidate revalidate'.",
    )
    candidate_derive.add_argument("--repository-root", default=Path("."), type=Path)
    candidate_derive.set_defaults(handler=_candidate_derive)

    candidate_inspect = candidate_commands.add_parser("inspect")
    candidate_inspect.add_argument("--manifest", required=True, type=Path)
    candidate_inspect.set_defaults(handler=_candidate_inspect)

    candidate_revalidate = candidate_commands.add_parser("revalidate")
    candidate_revalidate.add_argument("--candidate-manifest", required=True, type=Path)
    candidate_revalidate.add_argument(
        "--retention-step",
        required=True,
        type=Path,
        help="Must match the candidate's output_sha256.",
    )
    candidate_revalidate.add_argument("--printer-profile", required=True, type=Path)
    candidate_revalidate.add_argument(
        "--target-manifest",
        type=Path,
        help=(
            "Separate the embedded target PCB from generated retention geometry; "
            "the board is reported but does not gate the record."
        ),
    )
    candidate_revalidate.add_argument(
        "--validation-root",
        required=True,
        type=Path,
        help="Directory receiving a new vNNN run; existing runs are never modified.",
    )
    candidate_revalidate.add_argument("--repository-root", default=Path("."), type=Path)
    candidate_revalidate.set_defaults(handler=_candidate_revalidate)

    candidate_promote = candidate_commands.add_parser("promote")
    candidate_promote.add_argument("--candidate-manifest", required=True, type=Path)
    candidate_promote.add_argument(
        "--relationship-path",
        type=Path,
        help="Omit for a root candidate with no parent revision.",
    )
    candidate_promote.add_argument(
        "--parameter-delta-path",
        type=Path,
        help="Omit for a root candidate with no parent revision.",
    )
    candidate_promote.add_argument("--physical-trial-path", required=True, type=Path)
    candidate_promote.add_argument("--target-root", required=True, type=Path)
    candidate_promote.add_argument("--reviewer", required=True)
    candidate_promote.add_argument("--reason", required=True)
    candidate_promote.add_argument(
        "--decision",
        default="promoted",
        choices=[member.value for member in PromotionDecision],
    )
    candidate_promote.add_argument(
        "--export-validation",
        type=Path,
        help="Passing export-validation record from 'candidate revalidate'.",
    )
    candidate_promote.add_argument(
        "--visual-review",
        type=Path,
        help="Passing visual-review record from 'review complete'.",
    )
    candidate_promote.add_argument("--physical-validation-passed", action="store_true")
    candidate_promote.add_argument(
        "--supersedes-candidate-id",
        help=(
            "Candidate id of the currently preferred revision this "
            "promotion replaces. Required whenever a different candidate "
            "is already preferred for the same target."
        ),
    )
    candidate_promote.add_argument("--output", required=True, type=Path)
    candidate_promote.set_defaults(handler=_candidate_promote)

    fixture = subcommands.add_parser("fixture")
    fixture_commands = fixture.add_subparsers(dest="subcommand", required=True)

    fixture_export = fixture_commands.add_parser("export")
    _add_capture_policy_arguments(fixture_export)
    fixture_export.add_argument("--base-thickness-mm", type=float, default=2.0)
    fixture_export.add_argument("--perimeter-margin-mm", type=float, default=2.0)
    fixture_export.add_argument("--output", required=True, type=Path)
    fixture_export.set_defaults(handler=_fixture_export)

    trial = subcommands.add_parser("trial")
    trial_commands = trial.add_subparsers(dest="subcommand", required=True)

    trial_start = trial_commands.add_parser("start")
    trial_start.add_argument("--candidate-report", required=True, type=Path)
    trial_start.add_argument("--fixture-stl", required=True, type=Path)
    trial_start.add_argument("--printer-profile", required=True)
    trial_start.add_argument("--material-profile", required=True)
    trial_start.add_argument("--slicer-profile", required=True)
    trial_start.add_argument("--output", required=True, type=Path)
    trial_start.set_defaults(handler=_trial_start)

    trial_complete = trial_commands.add_parser("complete")
    trial_complete.add_argument("--candidate-report", required=True, type=Path)
    trial_complete.add_argument("--fixture-stl", required=True, type=Path)
    trial_complete.add_argument("--printer-profile", required=True)
    trial_complete.add_argument("--material-profile", required=True)
    trial_complete.add_argument("--slicer-profile", required=True)
    trial_complete.add_argument("--observations", required=True, type=Path)
    trial_complete.add_argument(
        "--disposition",
        required=True,
        choices=[
            member.value
            for member in PhysicalValidationDisposition
            if member is not PhysicalValidationDisposition.PENDING
        ],
    )
    trial_complete.add_argument(
        "--measurements",
        type=Path,
        help=(
            "JSON object of measurements in mm: "
            '{"<name>": {"value_mm": 0.8, "nominal_mm": 0.85, "notes": "..."}}. '
            "Required for pass and revise."
        ),
    )
    trial_complete.add_argument("--operator-notes", default="")
    trial_complete.add_argument("--output", required=True, type=Path)
    trial_complete.set_defaults(handler=_trial_complete)

    trial_register = trial_commands.add_parser("register")
    trial_register.add_argument("--candidate-manifest", required=True, type=Path)
    trial_register.add_argument(
        "--physical-validation-record", required=True, type=Path
    )
    trial_register.add_argument("--fixture", required=True, type=Path)
    trial_register.add_argument("--trial-id", required=True)
    trial_register.add_argument("--output", required=True, type=Path)
    trial_register.set_defaults(handler=_trial_register)

    review = subcommands.add_parser("review")
    review_commands = review.add_subparsers(dest="subcommand", required=True)

    review_complete = review_commands.add_parser("complete")
    review_complete.add_argument("--candidate-manifest", required=True, type=Path)
    review_complete.add_argument("--design-review", required=True, type=Path)
    review_complete.add_argument("--installation-path-report", required=True, type=Path)
    review_complete.add_argument(
        "--observations",
        required=True,
        type=Path,
        help=(
            "JSON object answering every check: "
            '{"<check>": {"passed": true, "notes": "..."}}. Checks: '
            + ", ".join(check.value for check in VisualReviewCheck)
        ),
    )
    review_complete.add_argument("--reviewer", required=True)
    review_complete.add_argument(
        "--disposition",
        required=True,
        choices=[member.value for member in VisualReviewDisposition],
    )
    review_complete.add_argument("--reviewer-notes", default="")
    review_complete.add_argument("--output", required=True, type=Path)
    review_complete.set_defaults(handler=_review_complete)

    revision = subcommands.add_parser("revision")
    revision_commands = revision.add_subparsers(dest="subcommand", required=True)

    revision_compare = revision_commands.add_parser("compare")
    revision_compare.add_argument("--source-candidate", required=True, type=Path)
    revision_compare.add_argument("--target-candidate", required=True, type=Path)
    revision_compare.add_argument("--source-trial", type=Path)
    revision_compare.add_argument("--target-trial", type=Path)
    revision_compare.add_argument("--report-output", required=True, type=Path)
    revision_compare.add_argument("--recommendation-output", required=True, type=Path)
    revision_compare.set_defaults(handler=_revision_compare)

    status = subcommands.add_parser("status")
    status.add_argument("--target-root", required=True, type=Path)
    status.set_defaults(handler=_status)

    report = subcommands.add_parser("report")
    report.add_argument("--target-root", required=True, type=Path)
    report.set_defaults(handler=_report)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return int(args.handler(args))
    except (
        ValueError,
        TypeError,
        FileNotFoundError,
        FileExistsError,
        KeyError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
