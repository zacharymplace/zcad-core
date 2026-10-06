"""zcad-validation holder template, check, build and trial: a holder that hangs an object on a
wall, and the record of printing it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.cli._common import add_compensation_profile_argument, emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.holder import (
    build_holder,
    print_oriented,
    require_fits_bed,
    write_holder_record,
)
from zcad_core.features.holder_file import holder_template, inspect_holder_file
from zcad_core.features.holder_trial import (
    complete_holder_trial,
    holder_verification,
    start_holder_trial,
)
from zcad_core.profiles import load_compensation_profile, load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _holder_template(args: argparse.Namespace) -> int:
    """Print a valid example holder file to copy and edit, or write it."""

    template = holder_template(args.capture, args.model)

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _side_shortfall(args: argparse.Namespace) -> float | None:
    """The measured side-gap shortfall of the compensation profile, if one was given."""

    if args.compensation_profile is None:
        return None

    return load_compensation_profile(args.compensation_profile).mean(
        "side_gap_shortfall_mm"
    )


def _holder_check(args: argparse.Namespace) -> int:
    """Check a holder file and its object, then try the build; exits 1 if it cannot be
    built."""

    profile = load_printer_profile(args.printer_profile)
    report, spec, item = inspect_holder_file(args.file)
    errors = list(report.errors)
    holder: dict[str, Any] | None = None

    if spec is not None and item is not None:
        try:
            built = build_holder(
                spec, item, profile, side_shortfall_mm=_side_shortfall(args)
            )
            require_fits_bed(built, profile)
        except ValueError as error:
            errors.append(str(error))
        else:
            failed = sorted(name for name, ok in built.checks.items() if not ok)
            errors.extend(f"check failed: {name}" for name in failed)
            holder = {
                "size_mm": [round(v, 3) for v in built.size_mm],
                "front_mm": round(built.front_mm, 3),
                "clearance_per_side_mm": round(built.clearance_mm, 3),
                "openings": [opening.identifier for opening in built.openings],
                "fixings": len(built.fixings),
            }

    emit(
        {
            "file": str(args.file),
            "valid": not errors,
            "errors": errors,
            "warnings": list(report.warnings),
            "object": report.item,
            "holder": holder,
        }
    )

    return 0 if not errors else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _holder_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a holder, with its record."""

    profile = load_printer_profile(args.printer_profile)
    report, spec, item = inspect_holder_file(args.holder_file)

    if not report.valid or spec is None or item is None:
        raise ValueError("The holder cannot be built:\n- " + "\n- ".join(report.errors))

    holder = build_holder(spec, item, profile, side_shortfall_mm=_side_shortfall(args))
    require_fits_bed(holder, profile)

    if not holder.passed:
        failed = sorted(name for name, ok in holder.checks.items() if not ok)
        raise ValueError(f"The holder fails its checks: {failed}")

    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="holder",
            parts={"holder": print_oriented(holder)},
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "object_kind": spec.object_kind,
                "down_edge": spec.down_edge or None,
                "face": spec.face or None,
                "front_mm": holder.front_mm,
                "mount": spec.mount,
                "object_sha256": item.sha256,
            },
        )
    )
    files: dict[str, dict[str, Any]] = {
        exported.part_name: {
            "step_path": str(exported.step_path),
            "stl_path": str(exported.stl_path),
            "stl_sha256": _sha256(exported.stl_path),
            "bounds_mm": list(exported.bounds_mm),
        }
        for exported in result.parts
    }
    record = write_holder_record(holder, files, args.output_directory)
    emit(
        {
            "design_name": name,
            "object": report.item,
            "warnings": list(report.warnings),
            "front_mm": round(holder.front_mm, 3),
            "clearance_per_side_mm": round(holder.clearance_mm, 3),
            "clearance_from": holder.clearance_from,
            "finger_notch": holder.notch,
            "openings": [opening.to_dict() for opening in holder.openings],
            "fixings": [fixing.to_dict() for fixing in holder.fixings],
            "checks": holder.checks,
            "tolerance_status": holder.tolerance_status,
            "verified": False,
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "build_record": str(record),
            "parts": files,
        }
    )

    return 0


def _holder_trial_start(args: argparse.Namespace) -> int:
    trial = start_holder_trial(args.build_record)
    emit(
        {
            "trial": str(trial),
            "observations": str(trial / "observations.json"),
            "measurements": str(trial / "measurements.json"),
            "use": str(trial / "use.json"),
        }
    )

    return 0


def _holder_trial_complete(args: argparse.Namespace) -> int:
    record = complete_holder_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit(
        {
            "trial_record": str(record),
            "passed": json.loads(record.read_text(encoding="utf-8"))["passed"],
            "verification": holder_verification(
                args.trial_directory.parent.parent / "holder.json"
            ),
        }
    )

    return 0


def _holder_trial_status(args: argparse.Namespace) -> int:
    emit(holder_verification(args.build_record))

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the holder commands to the zcad-validation parser."""

    holder = subcommands.add_parser(
        "holder",
        help="build a holder that hangs a measured object on a wall",
    )
    commands = holder.add_subparsers(dest="holder_command", required=True)
    template = commands.add_parser(
        "template", help="print a valid example holder file to edit"
    )
    named = template.add_mutually_exclusive_group()
    named.add_argument(
        "--capture", type=Path, help="the object's capture file to name, with its hash"
    )
    named.add_argument(
        "--model", type=Path, help="or the object's STEP model to name, with its hash"
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_holder_template)
    check = commands.add_parser(
        "check",
        help="check a holder file and its object; exits 1 if it cannot be built",
    )
    check.add_argument("file", type=Path)
    check.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(check)
    check.set_defaults(handler=_holder_check)
    build = commands.add_parser("build", help="build, validate, and export a holder")
    build.add_argument("--holder-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(build)
    build.set_defaults(handler=_holder_build)

    trial = commands.add_parser(
        "trial", help="record a print of a holder and how it held the object"
    )
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    trial_start = trial_commands.add_parser(
        "start",
        help="write the next trial's observation, measurement and use templates",
    )
    trial_start.add_argument("--build-record", required=True, type=Path)
    trial_start.set_defaults(handler=_holder_trial_start)
    trial_complete = trial_commands.add_parser(
        "complete", help="validate a filled-in trial and write its record"
    )
    trial_complete.add_argument("--trial-directory", required=True, type=Path)
    trial_complete.add_argument(
        "--disposition",
        required=True,
        choices=[disposition.value for disposition in EnclosureTrialDisposition],
    )
    trial_complete.add_argument("--material-profile", default="petg")
    trial_complete.add_argument("--notes", default="")
    trial_complete.set_defaults(handler=_holder_trial_complete)
    trial_status = trial_commands.add_parser(
        "status",
        help="whether a build is verified: two passing trials of that build record",
    )
    trial_status.add_argument("--build-record", required=True, type=Path)
    trial_status.set_defaults(handler=_holder_trial_status)
