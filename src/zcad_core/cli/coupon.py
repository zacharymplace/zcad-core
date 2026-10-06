"""zcad-validation coupon: build, slice and record a calibration coupon.

See :mod:`zcad_core.features.calibration_coupon` for what it measures and how a
trial feeds the compensation profile.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cadquery as cq

from zcad_core.cli._common import emit
from zcad_core.cli.slice_check import rebuild_recipe, write_print_copies
from zcad_core.features.calibration_coupon import (
    BUILD_RECORD,
    build_coupon,
    complete_coupon_trial,
    coupon_checks,
    sha256,
    start_coupon_trial,
    write_coupon_record,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import get_fastener
from zcad_core.printing import SliceError, slice_models
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")
DEFAULT_SLICER_PROFILE = Path(
    "profiles/slicers/bambu-studio-a1-mini-petg-validation.json"
)


def _coupon_build(args: argparse.Namespace) -> int:
    """Build the coupon, write its record, and slice it if asked."""

    if (args.output_directory / BUILD_RECORD).exists():
        raise FileExistsError(
            f"A coupon is already built in {args.output_directory}; build the next "
            "one in its own folder"
        )

    printer_profile = load_printer_profile(args.printer_profile)
    coupon = build_coupon(get_fastener(args.fastener))
    checks = coupon_checks(coupon, printer_profile.get("build_volume_mm"))
    failed = sorted(name for name, check in checks.items() if not check["passed"])

    if failed:
        raise ValueError(f"The coupon fails its checks: {', '.join(failed)}")

    args.output_directory.mkdir(parents=True, exist_ok=True)
    stl = args.output_directory / f"{args.name}.stl"
    shape = workplane_shape(coupon.solid)
    cq.exporters.export(shape, str(stl))
    record = write_coupon_record(
        coupon,
        name=args.name,
        stl_path=stl,
        output_directory=args.output_directory,
        printer_profile_id=str(printer_profile["profile_id"]),
        checks=checks,
    )
    payload: dict[str, object] = {
        "build_record": str(record),
        "parts": {"coupon": {"stl": str(stl)}},
        "size_mm": [round(value, 1) for value in coupon.size_mm],
        "features": len(coupon.features),
        "checks": checks,
    }
    # It prints as built: flat on the bed, top face up.
    shapes = {"coupon": shape}

    if args.print_copies and not args.slice:
        payload["print_copies"] = write_print_copies(
            args.output_directory / "print", args.name, shapes
        )

    if args.slice:
        models = write_print_copies(args.output_directory / "print", args.name, shapes)

        try:
            sliced = slice_models(
                [Path(path) for path in models.values()],
                args.output_directory / "slice",
                slicer_profile_path=args.slicer_profile,
                summary_fields={
                    "design_name": args.name,
                    "build_record_sha256": sha256(record),
                    "rebuild": rebuild_recipe(
                        getattr(args, "argv", None), {"coupon": stl}
                    ),
                },
            )
        except SliceError as error:
            raise ValueError(str(error)) from error

        summary = sliced.summary
        payload["print"] = {
            "gcode": str(sliced.gcode_path),
            "estimated_print_minutes": round(
                summary["estimated_print_time_seconds"] / 60
            ),
            "filament_used_g": round(summary["filament_used_g"], 1),
            "slicer_warning": summary["slicer_warning"],
            "trial": str(start_coupon_trial(record)),
        }

    emit(payload)

    return 0


def _coupon_trial_start(args: argparse.Namespace) -> int:
    trial = start_coupon_trial(args.build_record)
    emit(
        {
            "trial": str(trial),
            "observations": str(trial / "observations.json"),
            "measurements": str(trial / "measurements.json"),
        }
    )

    return 0


def _coupon_trial_complete(args: argparse.Namespace) -> int:
    record = complete_coupon_trial(
        args.trial_directory,
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit({"trial_record": str(record)})

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the coupon commands to the zcad-validation parser."""

    coupon = subcommands.add_parser(
        "coupon", help="build and record calibration coupons for a printer"
    )
    commands = coupon.add_subparsers(dest="subcommand", required=True)
    build = commands.add_parser(
        "build", help="build a calibration coupon and write its record"
    )
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--name", default="calibration-coupon")
    build.add_argument(
        "--fastener",
        default="M3",
        help="whose insert pocket and screw hole the coupon's holes are",
    )
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.add_argument(
        "--slice",
        action="store_true",
        help=(
            "also slice it with Bambu Studio, in <output-directory>/slice, and "
            "open the first trial"
        ),
    )
    build.add_argument(
        "--print-copies",
        action="store_true",
        help=(
            "write the STL the slicer would be given, in <output-directory>/print, "
            "without slicing; slice check --rebuild uses it"
        ),
    )
    build.add_argument("--slicer-profile", type=Path, default=DEFAULT_SLICER_PROFILE)
    build.set_defaults(handler=_coupon_build)

    trial = commands.add_parser("trial", help="record a print of a built coupon")
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    start = trial_commands.add_parser(
        "start", help="write the next trial's observation and measurement templates"
    )
    start.add_argument("--build-record", required=True, type=Path)
    start.set_defaults(handler=_coupon_trial_start)
    complete = trial_commands.add_parser(
        "complete", help="validate a filled-in trial and write its record"
    )
    complete.add_argument("--trial-directory", required=True, type=Path)
    complete.add_argument("--material-profile", default="petg")
    complete.add_argument("--notes", default="")
    complete.set_defaults(handler=_coupon_trial_complete)
