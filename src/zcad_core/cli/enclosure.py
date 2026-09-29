"""zcad-validation enclosure build and enclosure hardware."""

from __future__ import annotations

import argparse
from pathlib import Path

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    analyze_board_display_assembly,
    build_board_assembly,
    build_board_display_assembly,
)
from zcad_core.cli._common import emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features import (
    EnclosureDesign,
    build_enclosure,
    export_enclosure_review,
)
from zcad_core.hardware import (
    DisplaySpec,
    get_board,
    get_display,
    list_boards,
    list_displays,
    list_fasteners,
)
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _assembly(args: argparse.Namespace, display: DisplaySpec | None) -> DeviceAssembly:
    board = get_board(args.board)

    if display is None:
        return build_board_assembly(
            board=board,
            board_placement=Placement(),
            connector_access_clearance_mm=args.connector_access_clearance_mm,
        )

    assembly = build_board_display_assembly(
        board=board,
        display=display,
        board_placement=Placement(),
        display_placement=Placement(z_mm=args.display_height_mm),
        board_display_clearance_mm=args.board_display_clearance_mm,
        connector_access_clearance_mm=args.connector_access_clearance_mm,
    )
    report = analyze_board_display_assembly(
        assembly,
        minimum_board_display_clearance_mm=args.board_display_clearance_mm,
    )

    if report.has_findings:
        raise ValueError(
            "The display is too close to the board or its parts; raise "
            "--display-height-mm: "
            f"{report.findings}"
        )

    return assembly


def _enclosure_build(args: argparse.Namespace) -> int:
    """Build, validate, and export an enclosure, and optionally review it."""

    board = get_board(args.board)
    display = get_display(args.display) if args.display else None
    assembly = _assembly(args, display)
    design = EnclosureDesign(
        wall_mm=args.wall_mm,
        floor_mm=args.floor_mm,
        lid_mm=args.lid_mm,
        fastener=args.fastener,
        side_clearance_mm=args.side_clearance_mm,
        bottom_clearance_mm=args.bottom_clearance_mm,
        top_clearance_mm=args.top_clearance_mm,
        cable_plug_width_mm=args.cable_plug_width_mm,
        cable_plug_height_mm=args.cable_plug_height_mm,
        display_retainer=args.display_retainer,
        display_fastener=args.display_fastener,
    )
    enclosure = build_enclosure(assembly, board=board, display=display, design=design)
    name = args.name or f"{board.identifier.lower().replace('_', '-')}-enclosure"
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="enclosure",
            parts={"base": enclosure.base, "lid": enclosure.lid},
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=load_printer_profile(args.printer_profile),
            parameters={
                "board": board.identifier,
                "display": display.identifier if display else None,
                "side_clearance_mm": list(enclosure.side_clearance_mm),
                "bottom_clearance_mm": design.bottom_clearance_mm,
                "top_clearance_mm": design.top_clearance_mm,
                "wall_mm": design.wall_mm,
                "fastener": design.fastener,
            },
        )
    )
    payload: dict[str, object] = {
        "design_name": name,
        "board_support": enclosure.board_support,
        "side_clearance_mm": list(enclosure.side_clearance_mm),
        "validation_status": (result.validation_report or {}).get("evaluated_status"),
        "parts": {
            part.part_name: {
                "step": str(part.step_path),
                "stl": str(part.stl_path),
                "metadata": str(part.metadata_path),
                "bounds_mm": list(part.bounds_mm),
            }
            for part in result.parts
        },
    }

    passed = True

    if args.review:
        review = export_enclosure_review(
            enclosure, assembly, output_directory=args.output_directory / "review"
        )
        passed = review.passed
        payload["review"] = {
            "passed": review.passed,
            "report": str(review.report_path),
            "glb": str(review.glb_path),
            "recommended_screw": (
                f"{enclosure.fastener.identifier} x "
                f"{review.report['fasteners']['recommended_screw_length_mm']} mm"
            ),
            "display_screws": review.report["display_fasteners"],
            "failed_checks": sorted(
                name
                for name, check in review.report["checks"].items()
                if not check["passed"]
            ),
        }

    emit(payload)

    return 0 if passed else 1


def _enclosure_hardware(args: argparse.Namespace) -> int:
    emit(
        {
            "boards": list(list_boards()),
            "displays": list(list_displays()),
            "fasteners": list(list_fasteners()),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the enclosure commands to the zcad-validation parser."""

    enclosure = subcommands.add_parser(
        "enclosure", help="build printable enclosures around catalogued hardware"
    )
    enclosure_commands = enclosure.add_subparsers(dest="subcommand", required=True)

    hardware = enclosure_commands.add_parser(
        "hardware", help="list the boards, displays, and fasteners available"
    )
    hardware.set_defaults(handler=_enclosure_hardware)

    build = enclosure_commands.add_parser(
        "build", help="build, validate, and export a base and lid"
    )
    build.add_argument("--board", required=True, help="catalogued board identifier")
    build.add_argument("--display", help="catalogued display identifier")
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--name", help="design name; defaults to <board>-enclosure")
    build.add_argument(
        "--review",
        action="store_true",
        help="also write a review package to <output-directory>/review",
    )
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.add_argument(
        "--display-height-mm",
        type=float,
        default=8.0,
        help="height of the display's underside above the board's underside",
    )
    build.add_argument("--board-display-clearance-mm", type=float, default=1.0)
    build.add_argument("--connector-access-clearance-mm", type=float, default=2.0)
    build.add_argument("--wall-mm", type=float, default=2.0)
    build.add_argument("--floor-mm", type=float, default=2.0)
    build.add_argument("--lid-mm", type=float, default=2.0)
    build.add_argument("--fastener", default="M3")
    build.add_argument(
        "--display-fastener",
        default="M2",
        help="self-tapping screws into the display posts",
    )
    build.add_argument(
        "--side-clearance-mm",
        type=float,
        help="gap around the hardware; automatic when omitted",
    )
    build.add_argument("--bottom-clearance-mm", type=float, default=2.0)
    build.add_argument("--top-clearance-mm", type=float, default=2.0)
    build.add_argument("--cable-plug-width-mm", type=float, default=12.5)
    build.add_argument("--cable-plug-height-mm", type=float, default=7.5)
    build.add_argument(
        "--no-display-retainer",
        dest="display_retainer",
        action="store_false",
        help="leave the display loose under its window",
    )
    build.set_defaults(handler=_enclosure_build)
