"""zcad-validation revision compare and revision propose."""

from __future__ import annotations

import argparse
from pathlib import Path

from zcad_core.cli._common import (
    emit,
    load_physical_trial_manifest,
)
from zcad_core.retention import (
    compare_candidate_revisions,
    load_candidate_revision,
    propose_fixture_revision,
    recommend_revision,
    write_revision_comparison_report,
    write_revision_recommendation,
)


def _revision_compare(args: argparse.Namespace) -> int:
    source = load_candidate_revision(args.source_candidate)
    target = load_candidate_revision(args.target_candidate)

    source_trial = (
        load_physical_trial_manifest(args.source_trial)
        if args.source_trial is not None
        else None
    )
    target_trial = (
        load_physical_trial_manifest(args.target_trial)
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

    emit(
        {
            "decision": recommendation.decision.value,
            "rationale": recommendation.rationale,
            "report": str(args.report_output),
            "recommendation": str(args.recommendation_output),
        }
    )

    return 0


def _revision_propose(args: argparse.Namespace) -> int:
    """Propose the next revision's policy from a recorded fixture trial."""

    proposal = propose_fixture_revision(args.candidate_directory, trial_id=args.trial)
    payload = proposal.record()

    if proposal.changes:
        payload["regenerate"] = " ".join(
            [
                "python scripts/regenerate-candidate.py",
                str(args.candidate_directory),
                "--revision <next>",
                f"--from-trial {args.trial}",
            ]
        )

    emit(payload)

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the revision commands to the zcad-validation parser."""

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

    revision_propose = revision_commands.add_parser(
        "propose",
        help="propose the next revision's policy from a recorded fixture trial",
    )
    revision_propose.add_argument("--candidate-directory", required=True, type=Path)
    revision_propose.add_argument("--trial", default="trial-001")
    revision_propose.set_defaults(handler=_revision_propose)
