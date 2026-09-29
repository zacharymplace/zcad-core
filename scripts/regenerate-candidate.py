"""Generate a new revision of a Validation Lab candidate with fresh geometry.

For a corner-capture or edge-clip candidate directory this writes a new
revision beside it, rebuilt by the current code: retention STEP, automated
evidence, fixture STL, the revision manifests, and a first export-validation
run. Two reasons produce one:

- changed parameters (``--set``), such as a clearance a physical trial
  measured too tight; name the change with ``--relationship``
- a recorded trial's measurements (``--from-trial``), which set the policy
  changes, the relationship, and the reason, and write
  ``measurement-feedback.json`` beside the new revision tracing each change
  to its measurement
- changed generator code with the policy unchanged, which requires
  ``GENERATOR_VERSION`` to differ from the parent's

The geometry is attributed to the checked-out commit, so ``src/`` must have
no uncommitted changes. Nothing existing is overwritten.

The corner keepout is inherited from the parent's recorded generation
settings. A corner-capture parent generated before those were recorded needs
``--corner-keepout-mm`` (the XIAO ESP32-S3 candidates used 2.1).

Bring the new revision to the pre-print state with
``scripts/prepare-candidate-for-print.py`` and slice it with
``scripts/slice-candidate-fixture.py``.

Usage:
    python scripts/regenerate-candidate.py <candidate-directory> \\
        --revision r006 --reason "..." \\
        [--set board_clearance_mm=0.30 --relationship adjusts_clearance_from] \\
        [--from-trial trial-001] \\
        [--corner-keepout-mm 2.1] \\
        [--printer-profile profiles/printers/<id>.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from zcad_core.retention import (
    GENERATOR_VERSION,
    RevisionRelationshipType,
    load_candidate_revision,
    load_manifest,
    propose_fixture_revision,
    recorded_generation_parameters,
    register_artifact_backed_revision,
    write_measurement_feedback,
)


def checked_out_commit() -> str:
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "src"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout

    if dirty.strip():
        raise SystemExit(
            "src/ has uncommitted changes; commit them first so the new "
            "revision's git_commit names the code that generated it"
        )

    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidate_directory", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--reason", help="Required unless --from-trial writes one.")
    parser.add_argument(
        "--from-trial",
        metavar="TRIAL_ID",
        help="Derive the changes from this recorded trial's measurements.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        dest="updates",
        help="A retention-policy change, e.g. board_clearance_mm=0.30.",
    )
    parser.add_argument(
        "--relationship",
        choices=[member.value for member in RevisionRelationshipType],
        help="Required with --set; defaults to supersedes for a regeneration.",
    )
    parser.add_argument(
        "--corner-keepout-mm",
        type=float,
        help="Only for a corner-capture parent that does not record its keepout.",
    )
    parser.add_argument(
        "--printer-profile",
        type=Path,
        default=Path("profiles/printers/bambu-lab-a1-mini.json"),
    )
    args = parser.parse_args()

    updates: dict[str, float] = {}

    for assignment in args.updates:
        key, separator, value = assignment.partition("=")

        if not separator:
            raise SystemExit(f"--set must be KEY=VALUE, got: {assignment}")

        updates[key] = float(value)

    proposal = None

    if args.from_trial:
        if updates or args.relationship:
            raise SystemExit(
                "--from-trial sets the changes; drop --set and --relationship"
            )

        try:
            proposal = propose_fixture_revision(
                args.candidate_directory, trial_id=args.from_trial
            )
        except (ValueError, FileNotFoundError) as error:
            raise SystemExit(str(error)) from error

        if not proposal.changes:
            raise SystemExit(
                f"{args.from_trial} proposes no policy change: {list(proposal.notes)}"
            )

        updates = proposal.updates
        args.relationship = proposal.relationship.value
        args.reason = args.reason or proposal.reason

    if not args.reason:
        raise SystemExit("--reason is required")

    if updates and args.relationship is None:
        raise SystemExit(
            "--set needs --relationship naming the change, e.g. adjusts_clearance_from"
        )

    relationship = RevisionRelationshipType(args.relationship or "supersedes")
    parent_directory: Path = args.candidate_directory
    parent = load_candidate_revision(parent_directory / "candidate.json")
    target = load_manifest(parent_directory.parents[1] / "target.json")

    if not updates and parent.generator_version == GENERATOR_VERSION:
        raise SystemExit(
            f"{parent.candidate_id} was already generated by {GENERATOR_VERSION}. "
            "Pass --set to change its parameters, or regenerate after a geometry "
            "change bumps GENERATOR_VERSION in src/zcad_core/retention/generator.py."
        )

    if target["target_id"] != parent.target_id:
        raise SystemExit(
            f"{parent_directory} belongs to {parent.target_id}, "
            f"not {target['target_id']}"
        )

    result = register_artifact_backed_revision(
        parent_candidate=parent,
        revision=args.revision,
        parameter_updates=updates,
        relationship=relationship,
        reason=args.reason,
        output_directory=parent_directory.parent / args.revision,
        source_step=Path(target["source_model_path"]),
        pcb_solid_index=int(target["pcb_solid_index"]),
        git_commit=checked_out_commit(),
        created_at_utc=datetime.now(UTC).isoformat(),
        printer_profile=load_manifest(args.printer_profile),
        corner_keepout_mm=args.corner_keepout_mm,
    )

    candidate = result.registration.candidate
    feedback = (
        write_measurement_feedback(proposal, parent_directory.parent / args.revision)
        if proposal is not None
        else None
    )
    print(
        json.dumps(
            {
                "candidate_id": candidate.candidate_id,
                "parent": parent.candidate_id,
                "relationship": relationship.value,
                "changed": updates,
                "generator_version": GENERATOR_VERSION,
                "selected": list(candidate.selected_corners),
                "generation": recorded_generation_parameters(
                    result.evidence_artifact.report_path
                ),
                "export_validation_status": result.export_validation.evaluated_status,
                "export_validation_record": str(result.export_validation_path),
                "measurement_feedback": str(feedback) if feedback else None,
            },
            indent=2,
        )
    )

    return 0 if result.export_validation.evaluated_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
