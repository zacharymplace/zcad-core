"""zcad-validation trial start, complete, and register."""

from __future__ import annotations

import argparse
from pathlib import Path

from zcad_core.cli._common import (
    emit,
    now,
)
from zcad_core.retention import (
    PhysicalMeasurement,
    PhysicalTrialManifest,
    PhysicalValidationCheck,
    PhysicalValidationDisposition,
    PhysicalValidationObservation,
    complete_physical_validation_record,
    create_pending_physical_validation_record,
    load_candidate_revision,
    load_manifest,
    load_physical_validation_record,
    write_immutable_manifest,
    write_physical_validation_record,
)


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

    emit(
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

    emit(
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
        created_at_utc=physical.completed_at_utc.strip() or now(),
    )

    write_immutable_manifest(
        trial,
        output_path=args.output,
    )

    emit(
        {
            "trial_id": trial.trial_id,
            "candidate_id": trial.candidate_id,
            "pending": trial.pending,
            "passed": trial.passed,
            "manifest": str(args.output),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the trial commands to the zcad-validation parser."""

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
