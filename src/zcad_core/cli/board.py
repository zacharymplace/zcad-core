"""zcad-validation board check and template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.hardware import board_template, check_board_file, load_board


def _board_check(args: argparse.Namespace) -> int:
    """Check a board file: refuse what cannot be right, warn of what probably
    is not."""

    report, origin = check_board_file(args.file)
    payload: dict[str, object] = {
        "file": str(args.file),
        "sha256": origin.sha256,
        "valid": report.valid,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
    }

    if report.valid:
        board = load_board(args.file)
        payload["board"] = {
            "identifier": board.identifier,
            "size_mm": [board.board_width_mm, board.board_length_mm],
            "thickness_mm": board.board_thickness_mm,
            "outline": (
                "rectangle"
                if board.outline_points_mm is None
                else f"polygon, {len(board.outline_points_mm)} points"
            ),
            "mounting_holes": (
                None
                if board.mounting_hole_diameter_mm is None
                else board.mounting_hole_diameter_mm
            ),
            "cable_connector": {
                "identifier": board.usb_connector.identifier,
                "edge": board.usb_connector.board_edge,
            },
            "components": [part.identifier for part in board.components],
            "wall_openings": [opening.identifier for opening in board.wall_openings],
            "power": board.power_figure is not None,
            "verified": board.verified,
        }

    emit(payload)

    return 0 if report.valid else 1


def _board_template(args: argparse.Namespace) -> int:
    """Print a valid example board file to copy and edit, or write it."""

    template = board_template()

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _board_import(args: argparse.Namespace) -> int:
    """Read a board file from a vendor STEP model, to review and edit."""

    # Imported here: reading a model needs CadQuery's STEP reader.
    from zcad_core.hardware.electronics.board_import import import_step

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    imported = import_step(
        args.step,
        identifier=args.identifier,
        pcb_solid_index=args.pcb_solid_index,
        cable_connector=args.cable_connector,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(imported.data, indent=2) + "\n", encoding="utf-8")
    check, _ = check_board_file(args.output)
    emit(
        {
            "written": str(args.output),
            **imported.report,
            "needs_review": imported.data.get("needs_review", []),
            "errors": list(check.errors),
            "warnings": list(check.warnings),
        }
    )

    return 0


def _board_promote(args: argparse.Namespace) -> int:
    """Add a board file to the catalog, on the evidence of its trials."""

    from zcad_core.features.board_promotion import promote_board

    kwargs = (
        {} if args.catalog_directory is None else {"directory": args.catalog_directory}
    )
    target = promote_board(args.file, args.trial_record, **kwargs)
    emit(
        {
            "written": str(target),
            "next": "commit this file and open a pull request; the board joins "
            "the catalog when it is merged",
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the board commands to the zcad-validation parser."""

    board = subcommands.add_parser(
        "board", help="check a board file, or write an example to edit"
    )
    commands = board.add_subparsers(dest="board_command", required=True)
    check = commands.add_parser(
        "check", help="check a board file; exits 1 if it cannot be used"
    )
    check.add_argument("file", type=Path)
    check.set_defaults(handler=_board_check)
    template = commands.add_parser(
        "template", help="print a valid example board file to copy and edit"
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_board_template)
    import_ = commands.add_parser(
        "import",
        help="read a board file from a vendor STEP model (+Z up), to review",
    )
    import_.add_argument("--step", required=True, type=Path)
    import_.add_argument("--output", required=True, type=Path)
    import_.add_argument("--identifier", help="the board's name; default: the file's")
    import_.add_argument(
        "--pcb-solid-index",
        type=int,
        help="the PCB's solid, counting from 1, if the one found is wrong",
    )
    import_.add_argument(
        "--cable-connector",
        metavar="PART",
        help="the part the cable plugs into, from the candidates a first import lists",
    )
    import_.set_defaults(handler=_board_import)
    promote = commands.add_parser(
        "promote",
        help="add a board file to the catalog on two passing trials of it",
    )
    promote.add_argument("file", type=Path)
    promote.add_argument(
        "--trial-record",
        action="append",
        required=True,
        type=Path,
        help="a passing enclosure-trial.json of this file; give two or more",
    )
    promote.add_argument(
        "--catalog-directory",
        type=Path,
        help="write here instead of the catalog's own data directory",
    )
    promote.set_defaults(handler=_board_promote)
