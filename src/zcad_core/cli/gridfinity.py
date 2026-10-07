"""zcad-validation gridfinity bin and baseplate: parts that keep to the Gridfinity figures."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

from zcad_core.cli._common import add_compensation_profile_argument, emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.gridfinity import (
    DEFAULT_WALL_MM,
    BinSpec,
    build_bin,
    write_gridfinity_record,
)
from zcad_core.features.gridfinity_baseplate import BaseplateSpec, build_baseplate
from zcad_core.features.gridfinity_shapes import GridfinityPart, require_fits_bed
from zcad_core.profiles import load_compensation_profile, load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _units(text: str) -> tuple[int, int]:
    """``2x3`` as (2, 3)."""

    try:
        x, y = (int(part) for part in text.lower().split("x"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected units as XxY, e.g. 2x3, not {text!r}"
        ) from error

    return x, y


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _export(
    part: GridfinityPart, name: str, args: argparse.Namespace, profile: dict[str, Any]
) -> int:
    require_fits_bed(part, profile)

    if not part.passed:
        failed = sorted(check for check, ok in part.checks.items() if not ok)
        raise ValueError(f"The {part.kind} fails its checks: {failed}")

    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type=f"gridfinity-{part.kind}",
            parts=part.printed,
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters=part.settings,
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
    record = write_gridfinity_record(part, files, args.output_directory)
    emit(
        {
            "design_name": name,
            "settings": part.settings,
            "size_mm": [round(v, 3) for v in part.size_mm],
            "checks": part.checks,
            "warnings": list(part.warnings),
            "verified": False,
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "build_record": str(record),
            "parts": files,
        }
    )

    return 0


def _gridfinity_bin(args: argparse.Namespace) -> int:
    """Build, validate, and export a Gridfinity bin, with its record."""

    profile = load_printer_profile(args.printer_profile)
    shortfall = (
        load_compensation_profile(args.compensation_profile).mean(
            "side_gap_shortfall_mm"
        )
        if args.compensation_profile is not None
        else None
    )
    x, y = args.units
    spec = BinSpec(
        units_x=x,
        units_y=y,
        height_units=args.height,
        lip=not args.no_lip,
        magnets=args.magnets,
        wall_mm=args.wall_mm,
        screws=args.screws,
        divisions=args.divisions,
        label_tabs=args.label_tabs,
    )
    part = build_bin(spec, profile, side_shortfall_mm=shortfall)

    return _export(part, f"gridfinity-bin-{x}x{y}x{args.height}", args, profile)


def _gridfinity_baseplate(args: argparse.Namespace) -> int:
    """Build, validate, and export a Gridfinity baseplate, in pieces if it outgrows the bed,
    with its record."""

    profile = load_printer_profile(args.printer_profile)
    x, y = args.units
    part = build_baseplate(
        BaseplateSpec(x, y, magnets=args.magnets, screws=args.screws), profile
    )

    return _export(part, f"gridfinity-baseplate-{x}x{y}", args, profile)


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the gridfinity commands to the zcad-validation parser."""

    gridfinity = subcommands.add_parser(
        "gridfinity",
        help="build Gridfinity bins and baseplates to the published figures",
    )
    commands = gridfinity.add_subparsers(dest="gridfinity_command", required=True)
    bin_ = commands.add_parser("bin", help="build, validate, and export a bin")
    bin_.add_argument(
        "--units", required=True, type=_units, help="units across, e.g. 2x3"
    )
    bin_.add_argument(
        "--height", required=True, type=int, help="height in 7 mm units, 2 or more"
    )
    bin_.add_argument(
        "--no-lip", action="store_true", help="leave off the stacking lip"
    )
    bin_.add_argument(
        "--magnets", action="store_true", help="magnet holes in every unit's corners"
    )
    bin_.add_argument(
        "--screws", action="store_true", help="M3 screw holes in every unit's corners"
    )
    bin_.add_argument(
        "--divisions",
        type=_units,
        default=(1, 1),
        help="compartments across and front to back, e.g. 3x1",
    )
    bin_.add_argument(
        "--label-tabs",
        action="store_true",
        help="a label shelf on the back wall of each back compartment",
    )
    bin_.add_argument("--wall-mm", type=float, default=DEFAULT_WALL_MM)
    bin_.add_argument("--output-directory", required=True, type=Path)
    bin_.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(bin_)
    bin_.set_defaults(handler=_gridfinity_bin)
    plate = commands.add_parser(
        "baseplate",
        help="build, validate, and export a baseplate, in pieces if it outgrows the bed",
    )
    plate.add_argument(
        "--units", required=True, type=_units, help="cells across, e.g. 4x4"
    )
    plate.add_argument(
        "--magnets",
        action="store_true",
        help="magnet pockets under every bin's magnets",
    )
    plate.add_argument(
        "--screws",
        action="store_true",
        help="countersunk M3 holes to screw the plate down, under the magnets",
    )
    plate.add_argument("--output-directory", required=True, type=Path)
    plate.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    plate.set_defaults(handler=_gridfinity_baseplate)
