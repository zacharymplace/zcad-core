"""zcad-validation guide template, check, and build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.cli._common import add_joint_profile_argument, emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.guide import (
    GUIDE_RECORD,
    build_guide,
    measured_accuracy,
    print_oriented,
    require_fits_bed,
    write_guide_record,
)
from zcad_core.features.guide_file import (
    check_guide_file,
    guide_template,
    inspect_guide_file,
)
from zcad_core.features.guide_import import import_guide
from zcad_core.features.guide_trial import (
    GuideTrialDisposition,
    complete_guide_trial,
    guide_verification,
    start_guide_trial,
)
from zcad_core.hardware.electronics.board_import import MINIMUM_HOLE_MM
from zcad_core.profiles import load_printer_profile
from zcad_core.profiles.guide_accuracy import (
    DEFAULT_MINIMUM_TRIALS,
    derive_guide_profile,
    load_guide_profile,
    write_guide_profile,
)

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _guide_template(args: argparse.Namespace) -> int:
    """Print a valid example guide file to copy and edit, or write it."""

    template = guide_template(args.part)

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _offset(text: str) -> tuple[float, float]:
    """``X,Y`` as a pair of numbers."""

    try:
        x, y = (float(part) for part in text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not X,Y: two numbers with a comma, as 2.5,-1"
        ) from error

    return x, y


def _guide_import(args: argparse.Namespace) -> int:
    """Write a guide file with a bore at each round through-hole of a master."""

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    imported = import_guide(
        args.holes_from,
        target=args.part,
        identifier=args.identifier,
        master_solid_index=args.master_solid_index,
        target_solid_index=args.part_solid_index,
        offset_mm=args.offset,
        minimum_hole_mm=args.minimum_hole_mm,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(imported.data, indent=2) + "\n", encoding="utf-8")
    emit(
        {
            "written": str(args.output),
            **imported.report,
            "needs_review": imported.data["needs_review"],
        }
    )

    return 0


def _guide_check(args: argparse.Namespace) -> int:
    """Check a guide file and the part it names; exits 1 if it cannot be built."""

    profile = load_printer_profile(args.printer_profile)
    report = check_guide_file(args.file, profile)
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


def _guide_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a guide's nest and plate, with its record."""

    profile = load_printer_profile(args.printer_profile)
    report, spec, part = inspect_guide_file(args.guide_file, profile)

    if not report.valid or spec is None or part is None:
        raise ValueError("The guide cannot be built:\n- " + "\n- ".join(report.errors))

    guide = build_guide(spec, part, profile)
    require_fits_bed(guide, profile)

    if not guide.passed:
        failed = sorted(name for name, ok in guide.checks.items() if not ok)
        raise ValueError(
            f"The guide fails its checks: {failed}"
            + "".join(f"\n- {problem}" for problem in guide.problems)
        )

    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="guide",
            build_record_name=GUIDE_RECORD,
            parts={"guide": print_oriented(guide)},
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "nest_depth_mm": spec.nest_depth_mm,
                "nest_wall_mm": spec.nest_wall_mm,
                "plate_thickness_mm": guide.plate_thickness_mm,
                "bores": len(guide.bores),
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
    accuracy = (
        measured_accuracy(
            guide, load_guide_profile(args.accuracy_profile), args.material_profile
        )
        if args.accuracy_profile is not None
        else None
    )
    record = write_guide_record(
        guide,
        files,
        args.output_directory,
        material_profile_id=args.material_profile,
        accuracy=accuracy,
    )
    emit(
        {
            "design_name": name,
            "part": report.part,
            "warnings": list({*report.warnings, *guide.warnings}),
            "plate_thickness_mm": guide.plate_thickness_mm,
            "bores": [
                {
                    **item.to_dict(),
                    "worst_case_entry_play_mm": guide.play[item.bore.identifier][0],
                    "worst_case_tip_play_mm": guide.play[item.bore.identifier][1],
                }
                for item in guide.bores
            ],
            "checks": guide.checks,
            "tolerance_status": guide.tolerance_status,
            "clearance_per_side_mm": guide.clearance_mm,
            "verified": False,
            "material_profile_id": args.material_profile,
            "measured_accuracy": accuracy,
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
    """Add the guide commands to the zcad-validation parser."""

    guide = subcommands.add_parser(
        "guide", help="build a drill guide's nest and plate around a part"
    )
    commands = guide.add_subparsers(dest="guide_command", required=True)
    template = commands.add_parser(
        "template", help="print a valid example guide file to copy and edit"
    )
    template.add_argument(
        "--part", type=Path, help="a STEP model to name, with its real hash"
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_guide_template)
    import_ = commands.add_parser(
        "import",
        help="write a guide file with a bore at each hole of a master part",
    )
    import_.add_argument(
        "--holes-from",
        required=True,
        type=Path,
        help="the master STEP model (+Z up) whose round through-holes become bores",
    )
    import_.add_argument(
        "--part",
        type=Path,
        help="the part the guide is built around; the master itself if left out",
    )
    import_.add_argument("--output", required=True, type=Path)
    import_.add_argument("--identifier", help="the guide's name; default: the part's")
    import_.add_argument(
        "--offset",
        type=_offset,
        default=(0.0, 0.0),
        metavar="X,Y",
        help="move every hole by this much, when the two parts do not share a centre",
    )
    import_.add_argument("--master-solid-index", type=int)
    import_.add_argument("--part-solid-index", type=int)
    import_.add_argument(
        "--minimum-hole-mm",
        type=float,
        default=MINIMUM_HOLE_MM,
        help="ignore holes narrower than this",
    )
    import_.set_defaults(handler=_guide_import)
    check = commands.add_parser(
        "check", help="check a guide file and its part; exits 1 if it cannot be built"
    )
    check.add_argument("file", type=Path)
    check.add_argument(
        "--printer-profile",
        type=Path,
        default=DEFAULT_PRINTER_PROFILE,
        help="the printer whose fits and walls the bores are checked against",
    )
    add_joint_profile_argument(check)
    check.set_defaults(handler=_guide_check)
    build = commands.add_parser("build", help="build, validate, and export a guide")
    build.add_argument("--guide-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.add_argument(
        "--material-profile",
        default="petg",
        help="the material the guide is printed in, recorded with the build",
    )
    build.add_argument(
        "--accuracy-profile",
        type=Path,
        help=(
            "a profile pooled from guide trials (guide derive): the build reports "
            "its measured offsets beside the clearance bound"
        ),
    )
    add_joint_profile_argument(build)
    build.set_defaults(handler=_guide_build)
    _register_trials(commands)


def _trial_start(args: argparse.Namespace) -> int:
    trial = start_guide_trial(args.build_record)
    emit(
        {
            "trial": str(trial),
            "observations": str(trial / "observations.json"),
            "measurements": str(trial / "measurements.json"),
        }
    )

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    record = complete_guide_trial(
        args.trial_directory,
        disposition=GuideTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    summary = json.loads(record.read_text(encoding="utf-8"))["summary"]
    emit({"trial_record": str(record), "summary": summary})

    return 0


def _guide_status(args: argparse.Namespace) -> int:
    """Whether a build is verified: two passing trials of this exact build."""

    status = guide_verification(args.build_record)
    emit(status)

    return 0 if status["verified"] else 1


def _guide_derive(args: argparse.Namespace) -> int:
    """Pool the passing guide trials into the next version of an accuracy
    profile for one printer and material."""

    output = args.output or Path("profiles/guides") / (
        f"{args.printer_profile_id}-{args.material_profile}.json"
    )
    previous = (
        json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    )
    profile = derive_guide_profile(
        args.evidence_root,
        printer_profile_id=args.printer_profile_id,
        material_profile_id=args.material_profile,
        minimum_trials=args.minimum_trials,
        previous=previous,
    )
    write_guide_profile(profile, output)
    emit(
        {
            "profile": str(output),
            "version": profile["version"],
            "figures": profile["figures"],
            "trials": profile["trials"],
        }
    )

    return 0


def _register_trials(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the guide trial, status, and derive commands."""

    status = commands.add_parser(
        "status",
        help="whether a build is verified; exits 1 if it is not",
    )
    status.add_argument("--build-record", required=True, type=Path)
    status.set_defaults(handler=_guide_status)
    derive = commands.add_parser(
        "derive", help="pool passing guide trials into a measured accuracy profile"
    )
    derive.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    derive.add_argument("--printer-profile-id", default="bambu-lab-a1-mini")
    derive.add_argument("--material-profile", default="petg")
    derive.add_argument("--minimum-trials", type=int, default=DEFAULT_MINIMUM_TRIALS)
    derive.add_argument(
        "--output",
        type=Path,
        help="defaults to profiles/guides/<printer>-<material>.json",
    )
    derive.set_defaults(handler=_guide_derive)
    trial = commands.add_parser("trial", help="record a print of a built guide")
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    start = trial_commands.add_parser(
        "start", help="write the next trial's observation and measurement templates"
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
        choices=[disposition.value for disposition in GuideTrialDisposition],
    )
    complete.add_argument("--material-profile", default="petg")
    complete.add_argument("--notes", default="")
    complete.set_defaults(handler=_trial_complete)
