"""zcad-validation status and report."""

from __future__ import annotations

import argparse
from pathlib import Path

from zcad_core.cli._common import (
    emit,
    load_physical_trial_manifest,
    load_validation_target,
    scan_target_promotions,
)
from zcad_core.retention import (
    PhysicalTrialManifest,
    PhysicalValidationDisposition,
    PromotionDecision,
    load_candidate_revision,
    load_visual_review_record,
    select_preferred_revision,
)


def _status(args: argparse.Namespace) -> int:
    target = load_validation_target(args.target_root / "target.json")

    candidate_paths = sorted((args.target_root / "candidates").glob("*/candidate.json"))
    candidates = tuple(load_candidate_revision(path) for path in candidate_paths)

    promotions = scan_target_promotions(args.target_root)

    preferred = select_preferred_revision(
        target_id=target.target_id,
        promotion_records=promotions,
    )

    emit(
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


def _report(args: argparse.Namespace) -> int:
    """Aggregate a target's full recorded history into one view.

    Unlike ``status`` (current preference and eligibility only), this
    walks every candidate's trials and promotion record too - a rollup
    for human review, not a decision input.
    """

    target = load_validation_target(args.target_root / "target.json")

    candidates_root = args.target_root / "candidates"
    candidate_paths = sorted(candidates_root.glob("*/candidate.json"))
    candidates = tuple(load_candidate_revision(path) for path in candidate_paths)
    review_paths = {
        candidate.candidate_id: path.parent / "visual-review.json"
        for candidate, path in zip(candidates, candidate_paths, strict=True)
    }

    trial_paths = sorted(candidates_root.glob("*/trials/*/trial.json"))
    trials = tuple(load_physical_trial_manifest(path) for path in trial_paths)

    trials_by_candidate: dict[str, list[PhysicalTrialManifest]] = {}

    for trial in trials:
        trials_by_candidate.setdefault(trial.candidate_id, []).append(trial)

    promotions = scan_target_promotions(args.target_root)
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

    emit(
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


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the status commands to the zcad-validation parser."""

    status = subcommands.add_parser("status")
    status.add_argument("--target-root", required=True, type=Path)
    status.set_defaults(handler=_status)

    report = subcommands.add_parser("report")
    report.add_argument("--target-root", required=True, type=Path)
    report.set_defaults(handler=_report)
