"""zcad-validation guide template, check, and build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.cli._common import emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.guide import (
    build_guide,
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
from zcad_core.hardware.electronics.board_import import MINIMUM_HOLE_MM
from zcad_core.profiles import load_printer_profile

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
    record = write_guide_record(guide, files, args.output_directory)
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
    check.set_defaults(handler=_guide_check)
    build = commands.add_parser("build", help="build, validate, and export a guide")
    build.add_argument("--guide-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.set_defaults(handler=_guide_build)
