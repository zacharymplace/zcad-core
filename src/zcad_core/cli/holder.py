"""zcad-validation holder template, check and build: a holder that hangs an object on a wall."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.cli._common import add_compensation_profile_argument, emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.holder import (
    build_holder,
    print_oriented,
    require_fits_bed,
    write_holder_record,
)
from zcad_core.features.holder_file import holder_template, inspect_holder_file
from zcad_core.profiles import load_compensation_profile, load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _holder_template(args: argparse.Namespace) -> int:
    """Print a valid example holder file to copy and edit, or write it."""

    template = holder_template(args.capture)

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
    """Check a holder file and its capture, then try the build; exits 1 if it cannot be
    built."""

    profile = load_printer_profile(args.printer_profile)
    report, spec, capture = inspect_holder_file(args.file)
    errors = list(report.errors)
    holder: dict[str, Any] | None = None

    if spec is not None and capture is not None:
        try:
            built = build_holder(
                spec, capture, profile, side_shortfall_mm=_side_shortfall(args)
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
            "object": report.capture,
            "holder": holder,
        }
    )

    return 0 if not errors else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _holder_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a holder, with its record."""

    profile = load_printer_profile(args.printer_profile)
    report, spec, capture = inspect_holder_file(args.holder_file)

    if not report.valid or spec is None or capture is None:
        raise ValueError("The holder cannot be built:\n- " + "\n- ".join(report.errors))

    holder = build_holder(
        spec, capture, profile, side_shortfall_mm=_side_shortfall(args)
    )
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
                "down_edge": spec.down_edge,
                "face": spec.face,
                "front_mm": holder.front_mm,
                "mount": spec.mount,
                "capture_sha256": capture.sha256,
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
            "object": report.capture,
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
    template.add_argument(
        "--capture", type=Path, help="the object's capture file to name, with its hash"
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_holder_template)
    check = commands.add_parser(
        "check",
        help="check a holder file and its capture; exits 1 if it cannot be built",
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
