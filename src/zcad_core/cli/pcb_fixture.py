"""zcad-validation fixture template and check: PCB test fixtures.

These join the ``fixture`` group beside ``fixture export``, which is the
Validation Lab's print fixture; the two share a name and nothing else.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.pcb_fixture import (
    build_fixture,
    print_oriented,
    require_fits_bed,
    write_fixture_record,
)
from zcad_core.features.pcb_fixture_file import (
    check_fixture_file,
    fixture_template,
    load_fixture,
    load_fixture_board,
    probed_points,
)
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _fixture_template(args: argparse.Namespace) -> int:
    """Print a valid example fixture file to copy and edit, or write it."""

    template = fixture_template(args.board_file)

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _fixture_check(args: argparse.Namespace) -> int:
    """Check a fixture file, its board, and whether the pins can reach the
    points; exits 1 if the fixture cannot be built."""

    profile = load_printer_profile(args.printer_profile)
    report = check_fixture_file(args.file, profile)
    emit(
        {
            "file": str(args.file),
            "valid": report.valid,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            "fixture": report.summary,
        }
    )

    return 0 if report.valid else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a fixture's nest and plate, with its record."""

    profile = load_printer_profile(args.printer_profile)
    report = check_fixture_file(args.fixture_file, profile)

    if not report.valid:
        raise ValueError(
            "The fixture cannot be built:\n- " + "\n- ".join(report.errors)
        )

    spec = load_fixture(args.fixture_file)
    board = load_fixture_board(spec)
    fixture = build_fixture(spec, board, probed_points(spec, board), profile)

    if not fixture.passed:
        failed = sorted(name for name, ok in fixture.checks.items() if not ok)
        raise ValueError(f"The fixture fails its checks: {failed}")

    require_fits_bed(fixture, profile)
    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="fixture",
            parts=print_oriented(fixture),
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "board_sha256": spec.board_sha256,
                "pins": len(fixture.plan.points),
                "plate_thickness_mm": fixture.plan.plate_thickness_mm,
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
    record = write_fixture_record(fixture, files, args.output_directory)
    emit(
        {
            "design_name": name,
            "warnings": list(report.warnings),
            "plan": fixture.plan.to_dict(),
            "checks": fixture.checks,
            "closure": "not built: the plate is held by hand",
            "tolerance_status": fixture.tolerance_status,
            "verified": False,
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "build_record": str(record),
            "parts": files,
        }
    )

    return 0


def add_commands(
    fixture_commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the PCB test fixture commands to the ``fixture`` group."""

    template = fixture_commands.add_parser(
        "template", help="print a valid example PCB test fixture file to edit"
    )
    template.add_argument(
        "--board-file", type=Path, help="a board file to name, with its real hash"
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_fixture_template)
    check = fixture_commands.add_parser(
        "check",
        help="check a PCB test fixture file and its board; exits 1 if it cannot be built",
    )
    check.add_argument("file", type=Path)
    check.add_argument(
        "--printer-profile",
        type=Path,
        default=DEFAULT_PRINTER_PROFILE,
        help="the printer whose wall the pins' pitch is checked against",
    )
    check.set_defaults(handler=_fixture_check)
    build = fixture_commands.add_parser(
        "build", help="build, validate, and export a PCB test fixture's nest and plate"
    )
    build.add_argument("--fixture-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.set_defaults(handler=_fixture_build)
