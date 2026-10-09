"""zcad-validation nest template, check and build: a holding nest for a part."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.cli._common import (
    add_compensation_profile_argument,
    add_joint_profile_argument,
    emit,
)
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.nest import (
    NEST_RECORD,
    build_nest,
    print_oriented,
    require_fits_bed,
    write_nest_record,
)
from zcad_core.features.nest_file import (
    check_nest_file,
    inspect_nest_file,
    nest_template,
)
from zcad_core.features.nest_trial import (
    complete_nest_trial,
    start_nest_trial,
)
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _nest_template(args: argparse.Namespace) -> int:
    """Print a valid example nest file to copy and edit, or write it."""

    template = nest_template(args.part)

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _nest_check(args: argparse.Namespace) -> int:
    """Check a nest file and the part it names; exits 1 if it cannot be built."""

    profile = load_printer_profile(args.printer_profile)
    report = check_nest_file(args.file, profile)
    emit(
        {
            "file": str(args.file),
            "valid": report.valid,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            "part": report.part,
        }
    )

    return 0 if report.valid else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nest_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a nest, with its record."""

    profile = load_printer_profile(args.printer_profile)
    report, spec, part = inspect_nest_file(args.nest_file, profile)

    if not report.valid or spec is None or part is None:
        raise ValueError("The nest cannot be built:\n- " + "\n- ".join(report.errors))

    nest = build_nest(spec, part, profile)
    require_fits_bed(nest, profile)

    if not nest.passed:
        failed = sorted(name for name, ok in nest.checks.items() if not ok)
        raise ValueError(
            f"The nest fails its checks: {failed}"
            + "".join(f"\n- {problem}" for problem in nest.problems)
        )

    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="nest",
            build_record_name=NEST_RECORD,
            parts={"nest": print_oriented(nest)},
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "depth_mm": nest.depth_mm,
                "wall_mm": spec.wall_mm,
                "floor_mm": spec.floor_mm,
                "finger_notches": len(nest.notches),
                "lip_tabs": len(nest.tabs),
                "strap_slots": len(nest.slots),
                "part_sha256": part.sha256,
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
    record = write_nest_record(nest, files, args.output_directory)
    emit(
        {
            "design_name": name,
            "part": report.part,
            "warnings": list({*report.warnings, *nest.warnings}),
            "depth_mm": nest.depth_mm,
            "notches": [notch.to_dict() for notch in nest.notches],
            "strap_slots": [slot.to_dict() for slot in nest.slots],
            "label": None if nest.label is None else nest.label.to_dict(),
            "lip_tabs": [tab.to_dict() for tab in nest.tabs],
            "checks": nest.checks,
            "tolerance_status": nest.tolerance_status,
            "clearance_per_side_mm": nest.clearance_mm,
            "verified": False,
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "build_record": str(record),
            "parts": files,
        }
    )

    return 0


def _nest_trial_start(args: argparse.Namespace) -> int:
    trial = start_nest_trial(args.build_record)
    emit(
        {
            "trial": str(trial),
            "observations": str(trial / "observations.json"),
            "measurements": str(trial / "measurements.json"),
            "use": str(trial / "use.json"),
        }
    )

    return 0


def _nest_trial_complete(args: argparse.Namespace) -> int:
    record = complete_nest_trial(
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
    """Add the nest commands to the zcad-validation parser."""

    nest = subcommands.add_parser(
        "nest",
        help="build a holding nest: a tray that holds a part for sanding or gluing",
    )
    commands = nest.add_subparsers(dest="nest_command", required=True)
    template = commands.add_parser(
        "template", help="print a valid example nest file to edit"
    )
    template.add_argument(
        "--part", type=Path, help="the STEP file to name, with its hash"
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_nest_template)
    check = commands.add_parser(
        "check", help="check a nest file and its part; exits 1 if it cannot be built"
    )
    check.add_argument("file", type=Path)
    check.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(check)
    add_joint_profile_argument(check)
    check.set_defaults(handler=_nest_check)
    build = commands.add_parser("build", help="build, validate, and export a nest")
    build.add_argument("--nest-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(build)
    add_joint_profile_argument(build)
    build.set_defaults(handler=_nest_build)

    trial = commands.add_parser(
        "trial", help="record a print of a nest and how it did its job"
    )
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    trial_start = trial_commands.add_parser(
        "start",
        help="write the next trial's observation, measurement and use templates",
    )
    trial_start.add_argument("--build-record", required=True, type=Path)
    trial_start.set_defaults(handler=_nest_trial_start)
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
    trial_complete.set_defaults(handler=_nest_trial_complete)
