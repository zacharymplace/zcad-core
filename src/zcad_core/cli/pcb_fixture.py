"""zcad-validation fixture template and check: PCB test fixtures.

These join the ``fixture`` group beside ``fixture export``, which is the
Validation Lab's print fixture; the two share a name and nothing else.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.features.pcb_fixture_file import check_fixture_file, fixture_template
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
