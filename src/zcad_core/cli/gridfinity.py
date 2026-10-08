"""zcad-validation gridfinity bin, baseplate, fitted and trial: parts that keep to the Gridfinity
figures, bins with a pocket for one measured object, and the record of printing them."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.cli._common import add_compensation_profile_argument, emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.gridfinity import (
    DEFAULT_WALL_MM,
    BinSpec,
    build_bin,
    write_gridfinity_record,
)
from zcad_core.features.gridfinity_baseplate import BaseplateSpec, build_baseplate
from zcad_core.features.gridfinity_fitted import (
    FittedSpec,
    Footprint,
    build_fitted_bin,
    capture_footprint,
    model_footprint,
)
from zcad_core.features.gridfinity_shapes import GridfinityPart, require_fits_bed
from zcad_core.features.gridfinity_trial import (
    GRIDFINITY_BUILD_RECORD,
    complete_gridfinity_trial,
    gridfinity_verification,
    start_gridfinity_trial,
)
from zcad_core.features.holder_model import AXES, load_holder_model
from zcad_core.hardware.wearables.capture import load_capture
from zcad_core.printing import SliceError, slice_models
from zcad_core.profiles import load_compensation_profile, load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")
DEFAULT_SLICER_PROFILE = Path(
    "profiles/slicers/bambu-studio-a1-mini-petg-validation.json"
)


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

    if args.copies < 1:
        raise ValueError("--copies must be 1 or more")

    if args.copies > 1 and not args.slice:
        raise ValueError("--copies says how many go on the sliced plate; add --slice")

    if args.slice and part.pieces:
        raise ValueError(
            "--slice puts every part on one plate, and a baseplate in pieces needs a "
            "plate for each; slice its pieces one at a time"
        )

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
    record = write_gridfinity_record(part, files, args.output_directory, name)
    payload: dict[str, Any] = {
        "design_name": name,
        "settings": part.settings,
        "size_mm": [round(v, 3) for v in part.size_mm],
        "checks": part.checks,
        "warnings": list(part.warnings),
        "verified": False,
        "validation_status": (result.validation_report or {}).get("evaluated_status"),
        "build_record": str(record),
        "parts": files,
    }

    if args.slice:
        payload["print"] = _slice(name, files, record, args.slicer_profile, args.copies)

    emit(payload)

    return 0


def _slice(
    name: str,
    files: dict[str, dict[str, Any]],
    record: Path,
    slicer_profile: Path,
    copies: int,
) -> dict[str, Any]:
    """Slice the exported parts onto one plate, as they print, and open the
    first trial of what was sliced. More than one copy is for a check that
    needs a pair, such as a bin stacking on another."""

    try:
        sliced = slice_models(
            [Path(entry["stl_path"]) for entry in files.values()] * copies,
            record.parent / "slice",
            slicer_profile_path=slicer_profile,
            summary_fields={
                "design_name": name,
                "build_record_sha256": _sha256(record),
                "copies": copies,
            },
        )
    except SliceError as error:
        raise ValueError(str(error)) from error

    summary = sliced.summary

    return {
        "copies": copies,
        "gcode": str(sliced.gcode_path),
        "estimated_print_minutes": round(summary["estimated_print_time_seconds"] / 60),
        "filament_used_g": round(summary["filament_used_g"], 1),
        "slicer_warning": summary["slicer_warning"],
        "trial": str(start_gridfinity_trial(record)),
    }


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
        half_grid=args.half_grid,
    )
    part = build_bin(spec, profile, side_shortfall_mm=shortfall)
    grid = "half-" if args.half_grid else ""

    return _export(part, f"gridfinity-bin-{grid}{x}x{y}x{args.height}", args, profile)


def _footprint(args: argparse.Namespace) -> Footprint:
    if args.capture is not None:
        return capture_footprint(load_capture(args.capture))

    return model_footprint(
        load_holder_model(
            args.model, _sha256(args.model), args.solid_index, args.up, args.out
        )
    )


def _gridfinity_fitted(args: argparse.Namespace) -> int:
    """Build, validate, and export a bin with a pocket for one object, with its record."""

    profile = load_printer_profile(args.printer_profile)

    if (args.clearance_mm is None) != (not args.clearance_source):
        raise ValueError(
            "--clearance-mm and --clearance-source go together: a clearance with no source "
            "is a guess"
        )

    shortfall = (
        load_compensation_profile(args.compensation_profile).mean(
            "side_gap_shortfall_mm"
        )
        if args.compensation_profile is not None
        else None
    )
    item = _footprint(args)
    spec = FittedSpec(
        depth_mm=args.depth,
        lip=not args.no_lip,
        magnets=args.magnets,
        screws=args.screws,
        units=args.units,
        clearance_mm=args.clearance_mm,
        clearance_source=args.clearance_source or "",
        half_grid=args.half_grid,
    )
    part = build_fitted_bin(item, spec, profile, side_shortfall_mm=shortfall)
    x, y = part.settings["units"]
    stem = (args.capture or args.model).stem.lower().replace("_", "-")

    grid = "half-" if args.half_grid else ""

    return _export(part, f"gridfinity-fitted-{stem}-{grid}{x}x{y}", args, profile)


def _gridfinity_baseplate(args: argparse.Namespace) -> int:
    """Build, validate, and export a Gridfinity baseplate, in pieces if it outgrows the bed,
    with its record."""

    profile = load_printer_profile(args.printer_profile)
    x, y = args.units
    part = build_baseplate(
        BaseplateSpec(x, y, magnets=args.magnets, screws=args.screws), profile
    )

    return _export(part, f"gridfinity-baseplate-{x}x{y}", args, profile)


def _trial_start(args: argparse.Namespace) -> int:
    trial = start_gridfinity_trial(args.build_record)
    emit(
        {
            "trial": str(trial),
            "observations": str(trial / "observations.json"),
            "measurements": str(trial / "measurements.json"),
            "fit": str(trial / "fit.json"),
        }
    )

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    record = complete_gridfinity_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit(
        {
            "trial_record": str(record),
            "passed": json.loads(record.read_text(encoding="utf-8"))["passed"],
            "verification": gridfinity_verification(
                args.trial_directory.parent.parent / GRIDFINITY_BUILD_RECORD
            ),
        }
    )

    return 0


def _trial_status(args: argparse.Namespace) -> int:
    emit(gridfinity_verification(args.build_record))

    return 0


def _add_slice_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--slice",
        action="store_true",
        help="slice the parts onto one plate with Bambu Studio and open the first trial",
    )
    parser.add_argument("--slicer-profile", type=Path, default=DEFAULT_SLICER_PROFILE)
    parser.add_argument(
        "--copies",
        type=int,
        default=1,
        help="how many of the part go on the sliced plate, e.g. 2 to try one bin "
        "stacked on another",
    )


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
    bin_.add_argument(
        "--half-grid",
        action="store_true",
        help="bases on Gridfinity Rebuilt's 21 mm half grid; --units then counts half units",
    )
    bin_.add_argument("--wall-mm", type=float, default=DEFAULT_WALL_MM)
    bin_.add_argument("--output-directory", required=True, type=Path)
    bin_.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(bin_)
    _add_slice_arguments(bin_)
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
    _add_slice_arguments(plate)
    plate.set_defaults(handler=_gridfinity_baseplate)
    fitted = commands.add_parser(
        "fitted", help="build a bin with a pocket cut for one measured object"
    )
    named = fitted.add_mutually_exclusive_group(required=True)
    named.add_argument("--capture", type=Path, help="the object's caliper capture")
    named.add_argument("--model", type=Path, help="or its STEP model")
    fitted.add_argument(
        "--up", choices=sorted(AXES), default="+z", help="a model's axis that points up"
    )
    fitted.add_argument(
        "--out",
        choices=sorted(AXES),
        default="+y",
        help="a model's axis that points to the bin's back",
    )
    fitted.add_argument("--solid-index", type=int, help="a model's solid, from 1")
    fitted.add_argument(
        "--depth",
        type=float,
        help="how far the object sinks into the pocket, in mm; default its whole height",
    )
    fitted.add_argument(
        "--units",
        type=_units,
        help="units across, e.g. 3x1; default the fewest that fit",
    )
    fitted.add_argument(
        "--clearance-mm", type=float, help="a clearance per side of your own"
    )
    fitted.add_argument("--clearance-source", help="why that clearance")
    fitted.add_argument(
        "--no-lip", action="store_true", help="leave off the stacking lip"
    )
    fitted.add_argument(
        "--half-grid",
        action="store_true",
        help="units on Gridfinity Rebuilt's 21 mm half grid; --units then counts half units",
    )
    fitted.add_argument("--magnets", action="store_true")
    fitted.add_argument("--screws", action="store_true")
    fitted.add_argument("--output-directory", required=True, type=Path)
    fitted.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(fitted)
    _add_slice_arguments(fitted)
    fitted.set_defaults(handler=_gridfinity_fitted)

    trial = commands.add_parser(
        "trial", help="record a print of a bin or baseplate and how it fitted"
    )
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    start = trial_commands.add_parser(
        "start",
        help="write the next trial's observation, measurement and fit templates",
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
    status = trial_commands.add_parser(
        "status",
        help="whether a part is verified, and how many trials passed with another "
        "generator's part",
    )
    status.add_argument("--build-record", required=True, type=Path)
    status.set_defaults(handler=_trial_status)
