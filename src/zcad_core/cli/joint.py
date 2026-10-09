"""zcad-validation joint: build, record and derive from joint coupons.

See :mod:`zcad_core.features.joint_coupon` for what a coupon sweeps and
:mod:`zcad_core.profiles.joints` for how its trials choose a profile's figures.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cadquery as cq

from zcad_core.cli._common import emit
from zcad_core.cli.slice_check import rebuild_recipe, write_print_copies
from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.joint_coupon import (
    BUILD_RECORD,
    REFERENCE_DIAMETER_MM,
    build_fit_coupon,
    complete_joint_trial,
    fit_coupon_checks,
    sha256,
    start_joint_trial,
    write_fit_coupon_record,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.printing import SliceError, slice_models
from zcad_core.profiles import load_printer_profile
from zcad_core.profiles.joints import (
    DEFAULT_MINIMUM_TRIALS,
    derive_joint_profile,
    write_joint_profile,
)

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")
DEFAULT_SLICER_PROFILE = Path(
    "profiles/slicers/bambu-studio-a1-mini-petg-validation.json"
)


def _joint_build_fit(args: argparse.Namespace) -> int:
    """Build the fit coupon, write its record, and slice it if asked."""

    if (args.output_directory / BUILD_RECORD).exists():
        raise FileExistsError(
            f"A joint coupon is already built in {args.output_directory}; build the "
            "next one in its own folder"
        )

    printer_profile = load_printer_profile(args.printer_profile)
    fits, _, _ = printer_numbers(printer_profile)
    coupon = build_fit_coupon(args.reference_mm, fits["hole_oversize"])
    checks = fit_coupon_checks(coupon, printer_profile.get("build_volume_mm"))
    failed = sorted(name for name, check in checks.items() if not check["passed"])

    if failed:
        raise ValueError(f"The coupon fails its checks: {', '.join(failed)}")

    args.output_directory.mkdir(parents=True, exist_ok=True)
    stl = args.output_directory / f"{args.name}.stl"
    shape = workplane_shape(coupon.solid)
    cq.exporters.export(shape, str(stl))
    record = write_fit_coupon_record(
        coupon,
        name=args.name,
        stl_path=stl,
        output_directory=args.output_directory,
        printer_profile_id=str(printer_profile["profile_id"]),
        reference_source=args.reference_source,
        checks=checks,
    )
    payload: dict[str, object] = {
        "build_record": str(record),
        "parts": {"coupon": {"stl": str(stl)}},
        "size_mm": [round(value, 1) for value in coupon.size_mm],
        "rungs": len(coupon.rungs),
        "hole_oversize_mm": coupon.hole_oversize_mm,
        "checks": checks,
    }
    # It prints as built: flat on the bed, the wall standing at the back.
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
            "trial": str(start_joint_trial(record)),
        }

    emit(payload)

    return 0


def _joint_trial_start(args: argparse.Namespace) -> int:
    trial = start_joint_trial(args.build_record)
    emit({"trial": str(trial), "observations": str(trial / "observations.json")})

    return 0


def _joint_trial_complete(args: argparse.Namespace) -> int:
    record = complete_joint_trial(
        args.trial_directory,
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit({"trial_record": str(record)})

    return 0


def _joint_derive(args: argparse.Namespace) -> int:
    """Choose each fit figure from the recorded trials, as the next version."""

    output = args.output or (
        Path("profiles/joints")
        / f"{args.printer_profile_id}-{args.material_profile_id}.json"
    )
    previous = (
        json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    )
    profile = derive_joint_profile(
        args.evidence_root,
        printer_profile_id=args.printer_profile_id,
        material_profile_id=args.material_profile_id,
        minimum_trials=args.minimum_trials,
        previous=previous,
    )
    write_joint_profile(profile, output)
    emit(
        {
            "profile": str(output),
            "version": profile["version"],
            "figures": profile["figures"],
            "trials": len(profile["sources"]),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the joint coupon commands to the zcad-validation parser."""

    joint = subcommands.add_parser(
        "joint", help="build and record joint coupons, and derive a joint profile"
    )
    commands = joint.add_subparsers(dest="subcommand", required=True)
    build = commands.add_parser("build", help="build a joint coupon")
    families = build.add_subparsers(dest="family", required=True)
    fit = families.add_parser(
        "fit",
        help="holes for a metal reference, 0 to 0.4 mm a side, in a layer and across layers",
    )
    fit.add_argument("--output-directory", required=True, type=Path)
    fit.add_argument("--name", default="fit-coupon")
    fit.add_argument(
        "--reference-mm",
        type=float,
        default=REFERENCE_DIAMETER_MM,
        help="the measured diameter of the rod each hole is tried with (default 6)",
    )
    fit.add_argument(
        "--reference-source",
        default="a 6 mm drill's shank, measured with calipers",
        help="what the reference is, for the record",
    )
    fit.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    fit.add_argument(
        "--slice",
        action="store_true",
        help=(
            "also slice it with Bambu Studio, in <output-directory>/slice, and "
            "open the first trial"
        ),
    )
    fit.add_argument(
        "--print-copies",
        action="store_true",
        help=(
            "write the STL the slicer would be given, in <output-directory>/print, "
            "without slicing; slice check --rebuild uses it"
        ),
    )
    fit.add_argument("--slicer-profile", type=Path, default=DEFAULT_SLICER_PROFILE)
    fit.set_defaults(handler=_joint_build_fit)

    trial = commands.add_parser("trial", help="record a print of a joint coupon")
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    start = trial_commands.add_parser(
        "start", help="write the next trial's observations template"
    )
    start.add_argument("--build-record", required=True, type=Path)
    start.set_defaults(handler=_joint_trial_start)
    complete = trial_commands.add_parser(
        "complete", help="validate a filled-in trial and write its record"
    )
    complete.add_argument("--trial-directory", required=True, type=Path)
    complete.add_argument("--material-profile", default="petg")
    complete.add_argument("--notes", default="")
    complete.set_defaults(handler=_joint_trial_complete)

    derive = commands.add_parser(
        "derive", help="write the next version of a joint profile"
    )
    derive.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    derive.add_argument("--printer-profile-id", default="bambu-lab-a1-mini")
    derive.add_argument("--material-profile-id", default="petg")
    derive.add_argument("--minimum-trials", type=int, default=DEFAULT_MINIMUM_TRIALS)
    derive.add_argument(
        "--output",
        type=Path,
        help="defaults to profiles/joints/<printer>-<material>.json",
    )
    derive.set_defaults(handler=_joint_derive)
