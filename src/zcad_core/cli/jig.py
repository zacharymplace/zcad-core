"""zcad-validation jig template, check and build: an insert jig for a part."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.cli._common import emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.jig import (
    build_jig,
    print_oriented,
    require_fits_bed,
    write_jig_record,
)
from zcad_core.features.jig_file import (
    check_jig_file,
    inspect_jig_file,
    jig_template,
)
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _jig_template(args: argparse.Namespace) -> int:
    """Print an example jig file to copy and edit, or write it."""

    template = jig_template(args.part)

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _jig_check(args: argparse.Namespace) -> int:
    """Check a jig file and the part it names; exits 1 if it cannot be built."""

    profile = load_printer_profile(args.printer_profile)
    report = check_jig_file(args.file, profile)
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


def _jig_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a jig, with its record."""

    profile = load_printer_profile(args.printer_profile)
    report, spec, part = inspect_jig_file(args.jig_file, profile)

    if not report.valid or spec is None or part is None:
        raise ValueError("The jig cannot be built:\n- " + "\n- ".join(report.errors))

    jig = build_jig(spec, part, profile)
    require_fits_bed(jig, profile)

    if not jig.passed:
        failed = sorted(name for name, ok in jig.checks.items() if not ok)
        raise ValueError(
            f"The jig fails its checks: {failed}"
            + "".join(f"\n- {problem}" for problem in jig.problems)
        )

    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="jig",
            parts={"jig": print_oriented(jig)},
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "depth_mm": jig.depth_mm,
                "wall_mm": spec.wall_mm,
                "plate_thickness_mm": jig.plate_thickness_mm,
                "insert": spec.insert_size,
                "inserts": len(jig.bores),
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
    record = write_jig_record(jig, files, args.output_directory)
    emit(
        {
            "design_name": name,
            "part": report.part,
            "warnings": list({*report.warnings, *jig.warnings}),
            "depth_mm": jig.depth_mm,
            "plate_thickness_mm": jig.plate_thickness_mm,
            "bores": [bore.to_dict() for bore in jig.bores],
            "checks": jig.checks,
            "tolerance_status": jig.tolerance_status,
            "clearance_per_side_mm": jig.clearance_mm,
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
    """Add the jig commands to the zcad-validation parser."""

    jig = subcommands.add_parser(
        "jig",
        help="build an insert jig: holds a part and a heat-set insert square for the iron",
    )
    commands = jig.add_subparsers(dest="jig_command", required=True)
    template = commands.add_parser("template", help="print an example jig file to edit")
    template.add_argument(
        "--part", type=Path, help="the STEP file to name, with its hash"
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_jig_template)
    check = commands.add_parser(
        "check", help="check a jig file and its part; exits 1 if it cannot be built"
    )
    check.add_argument("file", type=Path)
    check.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    check.set_defaults(handler=_jig_check)
    build = commands.add_parser("build", help="build, validate, and export a jig")
    build.add_argument("--jig-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.set_defaults(handler=_jig_build)
