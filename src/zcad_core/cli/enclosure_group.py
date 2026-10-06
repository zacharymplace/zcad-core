"""zcad-validation enclosure-group build: a row of Raspberry Pi 5 bays.

This module holds the build command, its parsers, and ``register``. The slicing
step stays here, so a test patches ``slice_models`` where it is used. What the
command reads and reports is in ``enclosure_group_bays`` (the bays on the command
line), ``enclosure_group_review`` (the review model and the viewer),
``enclosure_group_thermal`` (the thermal estimate and the print trial),
``enclosure_group_join`` (whether two units bolt together) and
``enclosure_group_report`` (screws, the bed, parts, the stack top and warnings).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cadquery as cq

from zcad_core.cli._common import add_compensation_profile_argument, emit
from zcad_core.cli.enclosure import hinge_payload, slide_payload
from zcad_core.cli.enclosure_group_bays import _bay_summary, _bays
from zcad_core.cli.enclosure_group_join import _add_joint_arguments, _check_join, _size
from zcad_core.cli.enclosure_group_report import (
    _group_warnings,
    _parts,
    _require_fits_bed,
    _screw_style,
    _stack_top_payload,
)
from zcad_core.cli.enclosure_group_review import _group_viewer, _write_review
from zcad_core.cli.enclosure_group_thermal import (
    _group_thermal,
    _trial_complete,
    _trial_start,
)
from zcad_core.cli.slice_check import rebuild_recipe, write_print_copies
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.connector_cutouts import MINIMUM_OPENING_WEB_MM
from zcad_core.features.enclosure_group import (
    BAY_KINDS,
    GroupDesign,
    GroupEnclosure,
    build_group_enclosure,
    print_oriented_parts,
)
from zcad_core.features.enclosure_group_model import (
    GROUP_LID_ATTACHMENTS,
    GROUP_MOUNTS,
    JOINT_FACES,
    PASS_THROUGH_SIDES,
    SLIDE_ENTRIES,
)
from zcad_core.features.enclosure_group_trial import write_group_record
from zcad_core.features.enclosure_thermal import DEFAULT_AMBIENT_C
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.mounts import flexure_payload
from zcad_core.features.vent_patterns import PATTERNS
from zcad_core.printing import SliceError, slice_models
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


DEFAULT_SLICER_PROFILE = Path(
    "profiles/slicers/bambu-studio-a1-mini-petg-validation.json"
)


def _slice(
    args: argparse.Namespace,
    group: GroupEnclosure,
    name: str,
    part_stls: dict[str, Path],
) -> dict[str, object]:
    """Write print-oriented STLs and slice the base and the lid, each on a
    plate of its own: together they would not fit the bed."""

    print_directory = args.output_directory / "print"
    print_directory.mkdir()
    recipe = rebuild_recipe(getattr(args, "argv", None), part_stls)
    plates: dict[str, dict[str, object]] = {}
    minutes = 0
    grams = 0.0

    for part, shape in print_oriented_parts(group).items():
        model = print_directory / f"{name}-{part}.stl"
        cq.exporters.export(shape, str(model))

        try:
            sliced = slice_models(
                [model],
                args.output_directory / "slice" / part,
                slicer_profile_path=args.slicer_profile,
                summary_fields={"design_name": name, "part": part, "rebuild": recipe},
            )
        except SliceError as error:
            raise ValueError(str(error)) from error

        summary = sliced.summary
        part_minutes = round(summary["estimated_print_time_seconds"] / 60)
        part_grams = round(summary["filament_used_g"], 1)
        minutes += part_minutes
        grams += part_grams
        plates[part] = {
            "gcode": str(sliced.gcode_path),
            "estimated_print_minutes": part_minutes,
            "filament_used_g": part_grams,
            "slicer_warning": summary["slicer_warning"],
        }

    return {
        "plates": plates,
        "total_print_minutes": minutes,
        "total_filament_g": round(grams, 1),
    }


def _group_build(args: argparse.Namespace) -> int:
    bays = _bays(args.bays)
    design = GroupDesign(
        wall_mm=args.wall_mm,
        floor_mm=args.floor_mm,
        lid_mm=args.lid_mm,
        fastener=args.fastener,
        standoff_height_mm=args.standoff_height_mm,
        headroom_mm=args.headroom_mm,
        service_gap_mm=args.service_gap_mm,
        open_bay_width_mm=args.open_bay_width_mm,
        vents=args.vents,
        join_bolts=args.join_bolts,
        joint_face=args.joint,
        pass_through_mm=_size(args.pass_through),
        pass_through_sides=args.pass_through_sides,
        minimum_opening_web_mm=args.minimum_opening_web_mm,
        mount=args.mount,
        mount_plate_mm=args.mount_plate_mm,
        stack_profile=str(args.stack_profile) if args.stack_profile else None,
        stack_top=getattr(args, "stack_top", False),
        stack_top_holding=getattr(args, "stack_top_holding", "lip"),
        stack_top_magnet=getattr(args, "stack_top_magnet", None),
        stack_top_latch=getattr(args, "stack_top_latch", ""),
        stack_top_engagement_mm=getattr(args, "stack_top_engagement_mm", None),
        vent_pattern=args.vent_pattern,
        vent_area_mm2=args.vent_area_mm2,
        lid_attachment=args.lid,
        slide_clearance_mm=args.slide_clearance_mm,
        slide_entry=args.slide_entry,
        hinge_pin=args.hinge_pin,
    )
    group = build_group_enclosure(bays, design=design)
    thermal = _group_thermal(group, bays, args)
    name = args.name or f"pi5-group-{len(bays)}bay"
    profile = load_printer_profile(args.printer_profile)
    _require_fits_bed(group, profile)
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="enclosure",
            parts=_parts(group),
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "bays": [bay.kind for bay in bays],
                "bay_heights": _bay_summary(group),
                "headroom_mm": design.headroom_mm,
                "service_gap_mm": design.service_gap_mm,
                "wall_mm": design.wall_mm,
                "fastener": design.fastener,
            },
        )
    )
    review_path, review_lid = _write_review(
        group, args.output_directory / "review", name
    )
    record = write_group_record(
        args.output_directory,
        group=group,
        bays=bays,
        design_name=name,
        printer_profile_id=str(profile.get("profile_id", "")),
        part_stls={part.part_name: part.stl_path for part in result.parts},
        thermal=thermal.to_dict(),
    )
    join = (
        f"{group.fastener.identifier} x {group.recommended_join_screw_mm} mm, "
        f"{len(group.join_positions)} per joint"
        if group.recommended_join_screw_mm
        else None
    )
    printed = (
        _slice(
            args, group, name, {part.part_name: part.stl_path for part in result.parts}
        )
        if args.slice and group.passed
        else None
    )
    print_copies = (
        write_print_copies(
            args.output_directory / "print", name, print_oriented_parts(group)
        )
        if args.print_copies and not args.slice
        else None
    )
    emit(
        {
            "design_name": name,
            "bays": [bay.kind for bay in bays],
            "bay_heights": _bay_summary(group),
            "outer_size_mm": list(group.outer_size_mm),
            "warnings": _group_warnings(group),
            "fans": [fan.to_dict() for fan in group.fans],
            "thermal": thermal.to_dict(),
            "vents": group.vents.to_dict() if group.vents else None,
            "stack_top": _stack_top_payload(group),
            "joint": {
                "face": design.joint_face,
                "bolts_y_z_mm": [list(p) for p in group.join_positions],
                "pass_through_mm": design.pass_through_mm,
            },
            "lid": design.lid_attachment,
            "hinge": hinge_payload(group.hinge),
            "slide": slide_payload(group.slide),
            "checks": group.checks,
            "part_collisions": list(group.part_collisions),
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "screws": {
                "lid": (
                    f"{group.fastener.identifier} x "
                    f"{group.recommended_lid_screw_mm} mm, "
                    f"{len(group.lid_boss_positions)} per unit"
                    if group.recommended_lid_screw_mm
                    else None
                ),
                "hinge_pin": group.hinge.pin_description if group.hinge else None,
                "join": join,
                "pi_mount": "M2.5 self-tapping, 4 per Pi",
                "mount": (
                    f"{group.fastener.identifier} {_screw_style(group.mount)} x "
                    f"{group.mount.recommended_screw_mm} mm, "
                    f"{len(group.mount_pads.positions)} per part"
                    if group.mount is not None and group.mount_pads is not None
                    else None
                ),
                "mount_stack": group.mount.stack if group.mount else None,
                "mount_device": group.mount.device_screws if group.mount else None,
                "mount_attachment": group.mount.attachment if group.mount else None,
                "mount_flexure": (
                    flexure_payload(group.mount.flexure) if group.mount else None
                ),
            },
            "build_record": str(record),
            "review_step": str(review_path),
            "review_lid": review_lid,
            "print": printed,
            "print_copies": print_copies,
            "parts": {
                part.part_name: {
                    "step": str(part.step_path),
                    "stl": str(part.stl_path),
                    "bounds_mm": list(part.bounds_mm),
                }
                for part in result.parts
            },
        }
    )

    return 0 if group.passed else 1


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the enclosure-group command to the zcad-validation parser."""

    group = subcommands.add_parser(
        "enclosure-group",
        help="build one enclosure around a row of Raspberry Pi 5 bays",
    )
    commands = group.add_subparsers(dest="subcommand", required=True)
    build = commands.add_parser("build", help="build, validate, and export")
    build.add_argument(
        "--bays",
        default="pi5,pi5",
        help=(
            f"comma-separated bays left to right, from {', '.join(BAY_KINDS)}; "
            "a bay can set its own heights, as pi5:standoff=10:headroom=30, "
            "and an open bay can cut wall openings, as "
            "open:back=20x10@-5/3 (width x height, offset from the shelf's "
            "middle, height above the floor); any bay after the first can "
            "have a divider on its left, as pi5:divider=vents+notch+ties or "
            "open:divider=h12 (a low one 12 mm tall)"
        ),
    )
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--name")
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.add_argument("--wall-mm", type=float, default=2.0)
    build.add_argument("--floor-mm", type=float, default=2.0)
    build.add_argument("--lid-mm", type=float, default=3.0)
    build.add_argument(
        "--vent-pattern",
        choices=PATTERNS,
        default="slots",
        help=(
            "the shape of the vents sized by --vent-area-mm2: slots, a hex grid, "
            "round holes, or louvers in the side walls"
        ),
    )
    build.add_argument(
        "--vent-area-mm2",
        type=float,
        default=0.0,
        help=(
            "free area, in mm2, of the inlets low in the two side walls; the "
            "outlets in the lid are at least as large"
        ),
    )
    build.add_argument(
        "--power-w",
        type=float,
        default=0.0,
        help="power, in watts, that the catalog lacks: an SSD, a switch, a supply",
    )
    build.add_argument(
        "--ambient-c",
        type=float,
        default=DEFAULT_AMBIENT_C,
        help="the room's temperature, for the temperature estimate",
    )
    build.add_argument(
        "--material-profile",
        default="petg",
        help="the material, whose profile sets the limit for the air inside",
    )
    build.add_argument(
        "--thermal-profile",
        type=Path,
        default=None,
        help=(
            "a profile pooled from measured thermal trials, whose coefficient "
            "replaces the 8 W/m2K the estimate assumes"
        ),
    )
    build.add_argument(
        "--allow-hot",
        action="store_true",
        help="build a box the temperature estimate says is too hot",
    )
    build.add_argument(
        "--mount",
        choices=GROUP_MOUNTS,
        default=None,
        help="add four mount pads under the floor and a plate that bolts to them",
    )
    build.add_argument("--mount-plate-mm", type=float, default=4.0)
    build.add_argument(
        "--stack-profile",
        type=Path,
        default=None,
        help="the stack profile file a --mount stack plate or a --stack-top is built to",
    )
    build.add_argument(
        "--stack-top",
        action="store_true",
        help="add a baseplate over a screwed lid, held by the lid's own screws, so things "
        "stack on the row; needs --stack-profile and --no-vents",
    )
    build.add_argument(
        "--stack-top-holding",
        choices=("lip", "magnet"),
        default="lip",
        help="what a --stack-top holds a bin by: the lip alone, or magnets in its pockets' floors",
    )
    build.add_argument(
        "--stack-top-magnet",
        default=None,
        help="the catalogued magnet for --stack-top-holding magnet",
    )
    build.add_argument(
        "--stack-top-latch",
        default="",
        help="comma-separated sides (front,back,left,right) whose pocket walls take a latch keeper",
    )
    build.add_argument(
        "--stack-top-engagement-mm",
        type=float,
        default=None,
        help="how far a latch's hook engages its keeper; the profile's, else 0.4",
    )
    build.add_argument(
        "--lid",
        choices=GROUP_LID_ATTACHMENTS,
        default="screws",
        help=(
            "screw the lid into heat-set inserts, hinge it along the back wall "
            "and close it with a catch on the front, or slide it along the row"
        ),
    )
    build.add_argument(
        "--slide-entry",
        choices=SLIDE_ENTRIES,
        default="positive_x",
        help="the end wall a sliding lid slides out over",
    )
    build.add_argument(
        "--slide-clearance-mm",
        type=float,
        default=0.2,
        help="the gap per side around a sliding lid",
    )
    build.add_argument(
        "--hinge-pin",
        default="M3",
        help="the screw or rod (with nuts) that is a hinged lid's pin",
    )
    build.add_argument("--fastener", default="M3")
    build.add_argument(
        "--standoff-height-mm",
        type=float,
        default=4.0,
        help="default standoff height for a bay that sets none",
    )
    build.add_argument(
        "--headroom-mm",
        type=float,
        default=18.0,
        help="default room above the PCB for a bay that sets none",
    )
    build.add_argument("--service-gap-mm", type=float, default=25.0)
    build.add_argument("--open-bay-width-mm", type=float, default=40.0)
    build.add_argument("--no-vents", dest="vents", action="store_false")
    build.add_argument(
        "--minimum-opening-web-mm",
        type=float,
        default=MINIMUM_OPENING_WEB_MM,
        help=(
            "merge a Pi's back-wall openings that would leave less wall than "
            "this between them; 0 keeps them apart"
        ),
    )
    build.add_argument(
        "--no-join-bolts",
        dest="join_bolts",
        action="store_false",
        help="omit the bolt features that join a second unit",
    )
    _add_joint_arguments(build)
    build.add_argument(
        "--slice",
        action="store_true",
        help=(
            "also slice the base and the lid with Bambu Studio, each on its own "
            "plate, into <output-directory>/slice/<part>, and report print time "
            "and filament"
        ),
    )
    build.add_argument("--slicer-profile", type=Path, default=DEFAULT_SLICER_PROFILE)
    build.add_argument(
        "--print-copies",
        action="store_true",
        help=(
            "write the print-oriented STLs the slicer would be given, in "
            "<output-directory>/print, without slicing; slice check --rebuild "
            "uses it to compare what was printed"
        ),
    )
    add_compensation_profile_argument(build)
    build.set_defaults(handler=_group_build)

    trial = commands.add_parser("trial", help="record a print of a built group")
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    start = trial_commands.add_parser(
        "start", help="write the next trial's observation and measurement templates"
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
    check_join = commands.add_parser(
        "check-join",
        help="build two units and check that they bolt together",
    )
    check_join.add_argument("--left-bays")
    check_join.add_argument("--right-bays")
    check_join.add_argument(
        "--left-record",
        type=Path,
        help="a unit's enclosure-group.json, instead of building it from its bays",
    )
    check_join.add_argument("--right-record", type=Path)
    check_join.add_argument("--wall-mm", type=float, default=2.0)
    check_join.add_argument("--floor-mm", type=float, default=2.0)
    check_join.add_argument("--fastener", default="M3")
    check_join.add_argument("--lid", choices=GROUP_LID_ATTACHMENTS, default="screws")
    for unit in ("left", "right"):
        check_join.add_argument(
            f"--{unit}-joint", choices=JOINT_FACES, default="standard"
        )
        check_join.add_argument(f"--{unit}-pass-through", help="<width>x<height>")
        check_join.add_argument(
            f"--{unit}-pass-through-sides", choices=PASS_THROUGH_SIDES, default="both"
        )
    check_join.set_defaults(handler=_check_join)

    viewer = commands.add_parser(
        "viewer",
        help="write an interactive 3D viewer of the enclosures",
    )
    viewer.add_argument("--output-directory", required=True, type=Path)
    viewer.add_argument(
        "--bays",
        action="append",
        help=(
            "a row to show, in the syntax of build --bays; repeat for several. "
            "Without it the viewer shows the five standard configurations."
        ),
    )
    viewer.add_argument(
        "--standalone",
        action="store_true",
        help=(
            "wrap the page in a document skeleton for a local web server; "
            "leave it off to publish the page with the Artifact tool"
        ),
    )
    viewer.set_defaults(handler=_group_viewer)
