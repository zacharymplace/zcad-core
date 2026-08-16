"""Validation Lab command-line interface.

Thin argparse wrapper over the already-tested ``zcad_core.retention``
lifecycle functions. Every command reads and writes explicit file paths;
none of them infer a directory layout beyond what a caller passes in,
except ``status`` and ``candidate promote``, which read (never write) a
``--target-root`` to discover existing candidates and promotions.
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
    CandidateRevision,
    PhysicalTrialManifest,
    PhysicalValidationCheck,
    PhysicalValidationDisposition,
    PhysicalValidationObservation,
    PromotionDecision,
    PromotionRecord,
    RevisionRelationshipType,
    ValidationTarget,
    candidate_identifier,
    compare_candidate_revisions,
    complete_physical_validation_record,
    create_pending_physical_validation_record,
    load_candidate_revision,
    load_manifest,
    promote_preferred_revision,
    recommend_revision,
    register_candidate_revision,
    select_preferred_revision,
    sha256_file,
    write_immutable_manifest,
    write_physical_validation_record,
    write_revision_comparison_report,
    write_revision_recommendation,
)


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

    return PhysicalTrialManifest(
        schema_version=str(payload["schema_version"]),
        trial_id=str(payload["trial_id"]),
        candidate_id=str(payload["candidate_id"]),
        physical_validation_path=str(payload["physical_validation_path"]),
        fixture_artifact_path=str(payload["fixture_artifact_path"]),
        printer_profile=str(payload["printer_profile"]),
        material_profile=str(payload["material_profile"]),
        slicer_profile=str(payload["slicer_profile"]),
        disposition=str(payload["disposition"]),
        complete=bool(payload["complete"]),
        passed=bool(payload["passed"]),
        created_at_utc=str(payload["created_at_utc"]),
    )


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
        relationship_path=str(payload["relationship_path"]),
        parameter_delta_path=str(payload["parameter_delta_path"]),
        physical_trial_path=str(payload["physical_trial_path"]),
        created_at_utc=str(payload["created_at_utc"]),
        supersedes_candidate_id=(
            str(payload["supersedes_candidate_id"])
            if payload.get("supersedes_candidate_id") is not None
            else None
        ),
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


# --- candidate ----------------------------------------------------------------


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
            strategy="corner-capture",
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
    )

    write_immutable_manifest(
        candidate,
        output_path=args.output,
    )

    _emit(
        {
            "candidate_id": candidate.candidate_id,
            "automated_decision": candidate.automated_decision,
            "manifest": str(args.output),
        }
    )

    return 0


def _candidate_derive(args: argparse.Namespace) -> int:
    parent = load_candidate_revision(args.parent)

    parameter_updates: dict[str, float] = {}

    for assignment in args.set:
        key, separator, value = assignment.partition("=")

        if not separator:
            raise ValueError(f"--set must be KEY=VALUE, got: {assignment}")

        parameter_updates[key] = float(value)

    result = register_candidate_revision(
        parent_candidate=parent,
        revision=args.revision,
        parameter_updates=parameter_updates,
        relationship=RevisionRelationshipType(args.relationship),
        reason=args.reason,
        output_directory=args.output_directory,
        automated_decision=args.automated_decision,
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
        }
    )

    return 0


def _candidate_inspect(args: argparse.Namespace) -> int:
    payload = load_manifest(args.manifest)

    print(json.dumps(payload, indent=2, sort_keys=True))

    return 0


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
        automated_validation_passed=args.automated_validation_passed,
        physical_validation_passed=args.physical_validation_passed,
        candidate_manifest_path=str(args.candidate_manifest),
        relationship_path=str(args.relationship_path),
        parameter_delta_path=str(args.parameter_delta_path),
        physical_trial_path=str(args.physical_trial_path),
        created_at_utc=_now(),
        supersedes_candidate_id=args.supersedes_candidate_id,
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
            "complete": record.complete,
            "record": str(args.output),
        }
    )

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    observations_payload = json.loads(args.observations.read_text(encoding="utf-8"))

    if not isinstance(observations_payload, dict):
        raise TypeError("--observations file must contain a JSON object")

    observations = tuple(
        PhysicalValidationObservation(
            check=check,
            passed=bool(observations_payload[check.value]["passed"]),
            notes=str(observations_payload[check.value].get("notes", "")),
        )
        for check in PhysicalValidationCheck
    )

    record = complete_physical_validation_record(
        candidate_report_path=args.candidate_report,
        fixture_stl_path=args.fixture_stl,
        printer_profile=args.printer_profile,
        material_profile=args.material_profile,
        slicer_profile=args.slicer_profile,
        observations=observations,
        disposition=PhysicalValidationDisposition(args.disposition),
        operator_notes=args.operator_notes,
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
            "record": str(args.output),
        }
    )

    return 0


def _trial_register(args: argparse.Namespace) -> int:
    candidate = load_candidate_revision(args.candidate_manifest)
    physical = load_manifest(args.physical_validation_record)

    trial = PhysicalTrialManifest(
        schema_version="1.0.0",
        trial_id=args.trial_id,
        candidate_id=candidate.candidate_id,
        physical_validation_path=str(args.physical_validation_record),
        fixture_artifact_path=str(args.fixture),
        printer_profile=str(physical["printer_profile"]),
        material_profile=str(physical["material_profile"]),
        slicer_profile=str(physical["slicer_profile"]),
        disposition=str(physical["disposition"]),
        complete=bool(physical["complete"]),
        passed=bool(physical["passed"]),
        created_at_utc=(str(physical.get("completed_at_utc") or "").strip() or _now()),
    )

    write_immutable_manifest(
        trial,
        output_path=args.output,
    )

    _emit(
        {
            "trial_id": trial.trial_id,
            "candidate_id": trial.candidate_id,
            "passed": trial.passed,
            "manifest": str(args.output),
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


# --- parser -------------------------------------------------------------------


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

    candidate_register = candidate_commands.add_parser("register")
    candidate_register.add_argument("--target-manifest", required=True, type=Path)
    candidate_register.add_argument("--automated-evidence", required=True, type=Path)
    candidate_register.add_argument("--retention-step", required=True, type=Path)
    candidate_register.add_argument("--fixture", required=True, type=Path)
    candidate_register.add_argument("--revision", required=True)
    candidate_register.add_argument("--git-commit", required=True)
    candidate_register.add_argument("--generator-version", default="1.0.0")
    candidate_register.add_argument("--created-at-utc")
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
    candidate_derive.set_defaults(handler=_candidate_derive)

    candidate_inspect = candidate_commands.add_parser("inspect")
    candidate_inspect.add_argument("--manifest", required=True, type=Path)
    candidate_inspect.set_defaults(handler=_candidate_inspect)

    candidate_promote = candidate_commands.add_parser("promote")
    candidate_promote.add_argument("--candidate-manifest", required=True, type=Path)
    candidate_promote.add_argument("--relationship-path", required=True, type=Path)
    candidate_promote.add_argument("--parameter-delta-path", required=True, type=Path)
    candidate_promote.add_argument("--physical-trial-path", required=True, type=Path)
    candidate_promote.add_argument("--target-root", required=True, type=Path)
    candidate_promote.add_argument("--reviewer", required=True)
    candidate_promote.add_argument("--reason", required=True)
    candidate_promote.add_argument(
        "--decision",
        default="promoted",
        choices=[member.value for member in PromotionDecision],
    )
    candidate_promote.add_argument("--automated-validation-passed", action="store_true")
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
        choices=[member.value for member in PhysicalValidationDisposition],
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
