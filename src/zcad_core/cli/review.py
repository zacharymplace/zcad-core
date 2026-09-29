"""zcad-validation review complete."""

from __future__ import annotations

import argparse
from pathlib import Path

from zcad_core.cli._common import (
    emit,
)
from zcad_core.retention import (
    VisualReviewCheck,
    VisualReviewDisposition,
    VisualReviewObservation,
    complete_visual_review_record,
    load_candidate_revision,
    load_manifest,
    write_visual_review_record,
)


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

    emit(
        {
            "candidate_id": record.candidate_id,
            "disposition": record.disposition.value,
            "passed": record.passed,
            "conditional": record.conditional,
            "record": str(args.output),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the review commands to the zcad-validation parser."""

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
