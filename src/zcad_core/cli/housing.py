"""zcad-validation housing template, check and build: wearable housings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from zcad_core.cli._common import add_compensation_profile_argument, emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.housing import (
    build_housing,
    print_oriented,
    require_fits_bed,
)
from zcad_core.features.housing_file import (
    STYLES,
    check_housing_file,
    housing_template,
    load_housing,
)
from zcad_core.features.housing_trial import BUILD_RECORD as HOUSING_RECORD
from zcad_core.features.housing_trial import (
    complete_housing_trial,
    start_housing_trial,
    write_housing_record,
)
from zcad_core.features.housing_wear import WEAR_KINDS
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _housing_template(args: argparse.Namespace) -> int:
    """Print a valid example housing file to copy and edit, or write it."""

    template = housing_template(args.style, args.input_file, tuple(args.wear))

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _housing_check(args: argparse.Namespace) -> int:
    """Check a housing file and what it houses; exits 1 if it cannot be built."""

    profile = load_printer_profile(args.printer_profile)
    report = check_housing_file(args.file, profile)
    emit(
        {
            "file": str(args.file),
            "valid": report.valid,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            "housing": report.summary,
        }
    )

    return 0 if report.valid else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _housing_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a housing's parts."""

    profile = load_printer_profile(args.printer_profile)
    report = check_housing_file(args.housing_file, profile)

    if not report.valid:
        raise ValueError(
            "The housing cannot be built:\n- " + "\n- ".join(report.errors)
        )

    spec = load_housing(args.housing_file)
    housing = build_housing(spec, profile)

    if not housing.passed:
        failed = sorted(name for name, ok in housing.checks.items() if not ok)
        raise ValueError(f"The housing fails its checks: {failed}")

    require_fits_bed(housing, profile)
    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="housing",
            build_record_name=HOUSING_RECORD,
            parts=print_oriented(housing),
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "style": spec.style,
                "input_sha256": spec.input_sha256,
                "wall_mm": spec.wall_mm,
            },
        )
    )
    files = {
        exported.part_name: {
            "step_path": str(exported.step_path),
            "stl_path": str(exported.stl_path),
            "stl_sha256": _sha256(exported.stl_path),
            "bounds_mm": list(exported.bounds_mm),
        }
        for exported in result.parts
    }
    record = write_housing_record(
        args.output_directory,
        housing=housing,
        design_name=name,
        printer_profile_id=str(profile.get("profile_id", "")),
        part_stls={e.part_name: e.stl_path for e in result.parts},
    )
    emit(
        {
            "design_name": name,
            "build_record": str(record),
            "warnings": list(report.warnings),
            "housing": housing.summary,
            "checks": housing.checks,
            "not_claimed": list(housing.notes),
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "parts": files,
        }
    )

    return 0


def _trial_start(args: argparse.Namespace) -> int:
    trial = start_housing_trial(args.build_record)
    emit(
        {
            "trial": str(trial),
            "observations": str(trial / "observations.json"),
            "measurements": str(trial / "measurements.json"),
            "wear": str(trial / "wear.json"),
        }
    )

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    record = complete_housing_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit(
        {
            "trial_record": str(record),
            "passed": json.loads(record.read_text(encoding="utf-8"))["passed"],
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the housing commands to the zcad-validation parser."""

    housing = subcommands.add_parser(
        "housing",
        help="build a wearable housing: a cradle for a sealed device, a case for a board",
    )
    commands = housing.add_subparsers(dest="housing_command", required=True)
    template = commands.add_parser(
        "template", help="print a valid example housing file to edit"
    )
    template.add_argument("--style", required=True, choices=STYLES)
    template.add_argument(
        "--input-file",
        type=Path,
        help="the wearable file (a cradle) or board file (a case) to name, with its hash",
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.add_argument(
        "--wear",
        action="append",
        default=[],
        choices=WEAR_KINDS,
        help="a way of wearing to add, with example figures to replace; repeatable",
    )
    template.set_defaults(handler=_housing_template)
    check = commands.add_parser(
        "check", help="check a housing file and what it houses; exits 1 if it cannot"
    )
    check.add_argument("file", type=Path)
    check.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(check)
    check.set_defaults(handler=_housing_check)
    build = commands.add_parser(
        "build", help="build, validate, and export a housing's parts"
    )
    build.add_argument("--housing-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(build)
    build.set_defaults(handler=_housing_build)
    trial = commands.add_parser("trial", help="record a print and wear of a housing")
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    start = trial_commands.add_parser(
        "start",
        help="write the next trial's observation, measurement and wear templates",
    )
    start.add_argument("--build-record", required=True, type=Path)
    start.set_defaults(handler=_trial_start)
    complete = trial_commands.add_parser(
        "complete", help="validate a filled-in trial and write its record"
    )
    complete.add_argument("--trial-directory", required=True, type=Path)
    complete.add_argument(
        "--disposition",
        required=True,
        choices=[disposition.value for disposition in EnclosureTrialDisposition],
    )
    complete.add_argument("--material-profile", default="petg")
    complete.add_argument("--notes", default="")
    complete.set_defaults(handler=_trial_complete)
