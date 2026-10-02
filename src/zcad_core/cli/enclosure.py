"""zcad-validation enclosure build, hardware, and trial."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    analyze_board_display_assembly,
    build_board_assembly,
    build_board_display_assembly,
    lowest_display_height_mm,
)
from zcad_core.cli._common import emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features import (
    Enclosure,
    EnclosureDesign,
    EnclosureReview,
    build_enclosure,
    export_enclosure_review,
)
from zcad_core.features.connector_cutouts import MINIMUM_OPENING_WEB_MM
from zcad_core.features.enclosure import HOLE_COMPENSATION_RANGE_MM, LID_ATTACHMENTS
from zcad_core.features.enclosure_revision import propose_revision, revised_name
from zcad_core.features.enclosure_thermal import (
    CONVECTION_W_M2K,
    DEFAULT_AMBIENT_C,
    DEFAULT_SERVICE_LIMIT_C,
)
from zcad_core.features.enclosure_trial import (
    EnclosureTrialDisposition,
    complete_enclosure_trial,
    print_oriented_parts,
    sha256,
    start_enclosure_trial,
    write_build_record,
)
from zcad_core.features.fan_bay import FAN_DIRECTIONS, FAN_POSITIONS
from zcad_core.features.lid_hinge import HingeReport
from zcad_core.features.lid_slide import SlideReport
from zcad_core.features.mount_stack import require_plate_fits_bed
from zcad_core.features.mounts import MOUNTS, flexure_payload
from zcad_core.features.vent_patterns import PATTERNS
from zcad_core.hardware import (
    BoardFileSpec,
    BoardSpec,
    DisplaySpec,
    RaspberryPi5Spec,
    get_board,
    get_display,
    list_boards,
    list_displays,
    list_fans,
    list_fasteners,
    load_board,
)
from zcad_core.printing import SliceError, slice_freshness, slice_models
from zcad_core.profiles import (
    load_compensation_profile,
    load_printer_profile,
    load_thermal_profile,
    material_service_limit_c,
)

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")


def _board(args: argparse.Namespace) -> BoardSpec:
    board_file = getattr(args, "board_file", None)

    if (args.board is None) == (board_file is None):
        raise ValueError("Give one of --board (a catalogued board) and --board-file")

    board = load_board(board_file) if board_file is not None else get_board(args.board)

    if not getattr(args, "active_cooler", False):
        return board

    cooled = board.with_active_cooler() if isinstance(board, RaspberryPi5Spec) else None

    if cooled is None:
        raise ValueError(f"{board.identifier} takes no Active Cooler")

    return cooled


def _board_source(board: BoardSpec) -> dict[str, object]:
    """Where the board came from: the catalog, or a file the user supplied."""

    if isinstance(board, BoardFileSpec):
        return board.provenance()

    return {"kind": "catalog", "identifier": board.identifier}


# A display sits this high unless the board's parts need it higher, which
# leaves room for its wiring; pass a number to set it lower.
DEFAULT_DISPLAY_HEIGHT_MM = 8.0


def _height_or_auto(value: str) -> float | None:
    """A height in mm, or None for ``auto``."""

    if value.strip().lower() == "auto":
        return None

    try:
        return float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected a height in mm or auto, not {value!r}"
        ) from error


def _display_height_mm(
    args: argparse.Namespace, board: BoardSpec, display: DisplaySpec | None
) -> float | None:
    """The height asked for, or with ``auto`` the lowest that clears the
    board's parts; None without a display."""

    if display is None:
        return None

    if args.display_height_mm is not None:
        return float(args.display_height_mm)

    return lowest_display_height_mm(
        board=board,
        display=display,
        board_placement=Placement(),
        display_placement=Placement(),
        board_display_clearance_mm=args.board_display_clearance_mm,
        connector_access_clearance_mm=args.connector_access_clearance_mm,
        minimum_mm=DEFAULT_DISPLAY_HEIGHT_MM,
    )


def _assembly(
    args: argparse.Namespace, display: DisplaySpec | None, display_height: float | None
) -> DeviceAssembly:
    board = _board(args)

    if display is None or display_height is None:
        return build_board_assembly(
            board=board,
            board_placement=Placement(),
            connector_access_clearance_mm=args.connector_access_clearance_mm,
        )

    assembly = build_board_display_assembly(
        board=board,
        display=display,
        board_placement=Placement(),
        display_placement=Placement(z_mm=display_height),
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
            "--display-height-mm, or leave it at auto: "
            f"{report.findings}"
        )

    return assembly


def _design(args: argparse.Namespace) -> EnclosureDesign:
    compensation = args.hole_compensation_mm

    if args.compensation_profile is not None:
        if compensation:
            raise ValueError(
                "Pass --hole-compensation-mm or --compensation-profile, not both"
            )

        mean = load_compensation_profile(args.compensation_profile).mean(
            "hole_shortfall_mm"
        )

        if mean is None:
            raise ValueError(f"{args.compensation_profile} has no hole figure")

        low, high = HOLE_COMPENSATION_RANGE_MM
        compensation = round(min(max(mean, low), high), 2)

    return EnclosureDesign(
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
        hole_compensation_mm=compensation,
        lid_attachment=args.lid,
        hinge_pin=args.hinge_pin,
        slide_clearance_mm=args.slide_clearance_mm,
        declared_power_w=args.power_w,
        ambient_c=args.ambient_c,
        service_limit_c=_service_limit(args.material_profile),
        convection_w_m2k=_convection(args)[0],
        convection_source=_convection(args)[1],
        allow_hot=args.allow_hot,
        countersunk_screws=args.countersunk,
        locating_lip=args.locating_lip,
        vent_slots=args.vent_slots,
        vent_pattern=args.vent_pattern,
        vent_area_mm2=args.vent_area_mm2,
        fan=args.fan,
        fan_position=args.fan_position,
        fan_direction=args.fan_direction,
        fan_offset_x_mm=args.fan_offset_x_mm,
        fan_offset_y_mm=args.fan_offset_y_mm,
        minimum_opening_web_mm=args.minimum_opening_web_mm,
        mount=args.mount,
        mount_plate_mm=args.mount_plate_mm,
        stack_profile=str(args.stack_profile) if args.stack_profile else None,
    )


def _parts(enclosure: Enclosure) -> dict[str, cq.Workplane]:
    parts = {"base": enclosure.base, "lid": enclosure.lid}

    if enclosure.mount is not None:
        parts["mount"] = enclosure.mount.plate

    return parts


def _mount_payload(enclosure: Enclosure) -> dict[str, object] | None:
    if enclosure.mount is None or enclosure.mount_pads is None:
        return None

    return {
        "kind": enclosure.design.mount,
        "screws": f"{enclosure.fastener.identifier} "
        f"{'in a head recess' if enclosure.mount.stack else 'countersunk'} x "
        f"{enclosure.mount.recommended_screw_mm} mm, "
        f"{len(enclosure.mount_pads.positions)} per plate",
        "device_screws": enclosure.mount.device_screws,
        "attachment": enclosure.mount.attachment,
        "flexure": flexure_payload(enclosure.mount.flexure),
        "pad_height_mm": enclosure.mount_pads.height_mm,
        "plate_size_mm": list(enclosure.mount.size_mm),
        "stack": enclosure.mount.stack,
    }


def _slide_payload(enclosure: Enclosure) -> dict[str, object] | None:
    return slide_payload(enclosure.slide)


def slide_payload(slide: SlideReport | None) -> dict[str, object] | None:
    if slide is None:
        return None

    return {
        "entry_wall": slide.entry_edge,
        "clearance_mm": slide.clearance_mm,
        "lid_length_mm": round(slide.lid_length_mm, 1),
        "wall_top_above_cavity_mm": round(slide.wall_top_above_cavity_mm, 1),
        "detent": flexure_payload(slide.detent),
    }


def _hinge_payload(enclosure: Enclosure) -> dict[str, object] | None:
    return hinge_payload(enclosure.hinge)


def hinge_payload(hinge: HingeReport | None) -> dict[str, object] | None:
    if hinge is None:
        return None

    return {
        "hinge_wall": hinge.hinge_edge,
        "catch_wall": hinge.closure_edge,
        "knuckles": hinge.knuckles,
        "pin": hinge.pin_description,
        "swing_degrees": hinge.swing_degrees,
        "catch": flexure_payload(hinge.catch),
        "wall_needed_mm": round(hinge.wall_needed_mm, 1),
    }


def _convection(args: argparse.Namespace) -> tuple[float, str]:
    """The coefficient for the estimate: a measured profile's, or the default."""

    if getattr(args, "thermal_profile", None) is None:
        return CONVECTION_W_M2K, "the default, an assumption"

    profile = load_thermal_profile(args.thermal_profile)

    return profile.coefficient_w_m2k, profile.describe()


def _service_limit(material_profile_id: str) -> float:
    """The material's continuous-air limit, or the PETG default."""

    return material_service_limit_c(material_profile_id) or DEFAULT_SERVICE_LIMIT_C


def _revision_board_file(build: dict[str, Any]) -> Path | None:
    """The board file a revision rebuilds from, refused if it has changed
    since the build: a revision is meant to change the design, not the board."""

    source = build.get("board_source") or {}

    if source.get("kind") == "catalog" and source.get("sha256"):
        current = getattr(get_board(source["identifier"]), "origin", None)

        if current is None or current.sha256 != source["sha256"]:
            raise ValueError(
                f"The catalog's {source['identifier']} has changed since the "
                "build; build again rather than revising"
            )

    if source.get("kind") != "file":
        return None

    path = Path(source["path"])

    if not path.is_file() or sha256(path) != source["sha256"]:
        raise ValueError(
            f"The board file {path} is missing or has changed since the build; "
            "restore it, or build again from the changed file"
        )

    return path


def _enclosure_build(args: argparse.Namespace) -> int:
    """Build, validate, and export an enclosure and its build record, and
    optionally review it and slice it ready to print."""

    payload, passed = _build(args, _design(args))
    emit(payload)

    return 0 if passed else 1


def _build(
    args: argparse.Namespace,
    design: EnclosureDesign,
    revision_of: dict[str, object] | None = None,
) -> tuple[dict[str, object], bool]:
    board = _board(args)
    display = get_display(args.display) if args.display else None
    display_height = _display_height_mm(args, board, display)
    assembly = _assembly(args, display, display_height)
    enclosure = build_enclosure(assembly, board=board, display=display, design=design)
    name = args.name or f"{board.identifier.lower().replace('_', '-')}-enclosure"
    printer_profile = load_printer_profile(args.printer_profile)
    require_plate_fits_bed(enclosure.mount, printer_profile.get("build_volume_mm"))
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="enclosure",
            parts=_parts(enclosure),
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=printer_profile,
            parameters={
                "board": board.identifier,
                "display": display.identifier if display else None,
                "side_clearance_mm": list(enclosure.side_clearance_mm),
                "bottom_clearance_mm": design.bottom_clearance_mm,
                "top_clearance_mm": design.top_clearance_mm,
                "wall_mm": design.wall_mm,
                "fastener": design.fastener,
                **(
                    {"lid_clearance": design.slide_clearance_mm}
                    if design.lid_attachment == "slide"
                    else {}
                ),
            },
        )
    )
    build_record = write_build_record(
        args.output_directory,
        enclosure=enclosure,
        design_name=name,
        board_identifier=board.identifier,
        display=display,
        part_stls={part.part_name: part.stl_path for part in result.parts},
        printer_profile_id=str(printer_profile["profile_id"]),
        assembly_settings={
            # The height used, never "auto", so a revision rebuilds it exactly.
            "display_height_mm": display_height,
            "board_display_clearance_mm": args.board_display_clearance_mm,
            "connector_access_clearance_mm": args.connector_access_clearance_mm,
            "active_cooler": getattr(args, "active_cooler", False),
        },
        revision_of=revision_of,
        compensation_profile=(
            load_compensation_profile(args.compensation_profile).reference()
            if getattr(args, "compensation_profile", None) is not None
            else None
        ),
        thermal_profile=(
            load_thermal_profile(args.thermal_profile).reference()
            if getattr(args, "thermal_profile", None) is not None
            else None
        ),
        board_source=_board_source(board),
    )
    payload: dict[str, object] = {
        "board": _board_source(board),
        "design_name": name,
        "display_height_mm": display_height,
        "board_support": enclosure.board_support,
        "display_support": enclosure.display_support,
        "mount": _mount_payload(enclosure),
        "thermal": enclosure.thermal.to_dict() if enclosure.thermal else None,
        "vents": enclosure.vents.to_dict() if enclosure.vents else None,
        "fan": enclosure.fan.to_dict() if enclosure.fan else None,
        "hinge": _hinge_payload(enclosure),
        "slide": _slide_payload(enclosure),
        "side_clearance_mm": list(enclosure.side_clearance_mm),
        "validation_status": (result.validation_report or {}).get("evaluated_status"),
        "build_record": str(build_record),
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
        payload["review"] = _review_payload(enclosure, review)

    if args.slice:
        payload["print"] = _slice(args, enclosure, name, build_record)

    return payload, passed


def _enclosure_revise(args: argparse.Namespace) -> int:
    """Propose the next design from a completed trial, and optionally build it."""

    revision = propose_revision(args.trial_directory)
    payload: dict[str, object] = revision.summary()

    if args.output_directory is None:
        emit(payload)

        return 0

    build = revision.build_record
    assembly = build.get("assembly") or {}
    board_file = _revision_board_file(build)
    rebuild = argparse.Namespace(
        board=None if board_file else build["board"],
        board_file=board_file,
        display=build["display"],
        output_directory=args.output_directory,
        name=revised_name(build["design_name"]),
        review=args.review,
        slice=args.slice,
        slicer_profile=args.slicer_profile,
        printer_profile=Path("profiles/printers")
        / f"{build['printer_profile_id']}.json",
        display_height_mm=assembly.get("display_height_mm", 8.0),
        board_display_clearance_mm=assembly.get("board_display_clearance_mm", 1.0),
        connector_access_clearance_mm=assembly.get(
            "connector_access_clearance_mm", 2.0
        ),
        active_cooler=assembly.get("active_cooler", False),
    )
    payload["build"], passed = _build(
        rebuild,
        EnclosureDesign(**revision.design),
        revision_of={
            "build_record_path": str(revision.build_record_path),
            "build_record_sha256": sha256(revision.build_record_path),
            "trial_id": revision.trial["trial_id"],
            "changes": payload["changes"],
        },
    )
    emit(payload)

    return 0 if passed else 1


def _review_payload(enclosure: Enclosure, review: EnclosureReview) -> dict[str, object]:
    return {
        "passed": review.passed,
        "report": str(review.report_path),
        "glb": str(review.glb_path),
        "recommended_screw": (
            f"{enclosure.fastener.identifier} x "
            f"{review.report['fasteners']['recommended_screw_length_mm']} mm"
            if enclosure.fastener_positions
            else None
        ),
        "display_screws": review.report["display_fasteners"],
        "failed_checks": sorted(
            name
            for name, check in review.report["checks"].items()
            if not check["passed"]
        ),
    }


def _slice(
    args: argparse.Namespace, enclosure: Enclosure, name: str, build_record: Path
) -> dict[str, object]:
    """Write print-oriented STLs, slice them onto one plate, and open the
    first trial."""

    print_directory = args.output_directory / "print"
    print_directory.mkdir()
    models = []

    for part, shape in print_oriented_parts(enclosure).items():
        model = print_directory / f"{name}-{part}.stl"
        cq.exporters.export(shape, str(model))
        models.append(model)

    try:
        sliced = slice_models(
            models,
            args.output_directory / "slice",
            slicer_profile_path=args.slicer_profile,
            summary_fields={
                "design_name": name,
                "build_record_sha256": sha256(build_record),
            },
        )
    except SliceError as error:
        raise ValueError(str(error)) from error

    trial = start_enclosure_trial(build_record)
    summary = sliced.summary

    return {
        "gcode": str(sliced.gcode_path),
        "estimated_print_minutes": round(summary["estimated_print_time_seconds"] / 60),
        "filament_used_g": round(summary["filament_used_g"], 1),
        "slicer_warning": summary["slicer_warning"],
        "trial": str(trial),
    }


def _trial_start(args: argparse.Namespace) -> int:
    trial = start_enclosure_trial(args.build_record)
    payload: dict[str, object] = {
        "trial": str(trial),
        "observations": str(trial / "observations.json"),
        "measurements": str(trial / "measurements.json"),
    }

    if (trial / "lid.json").is_file():
        payload["lid"] = str(trial / "lid.json")

    # A slice beside the build record may predate a fix to the geometry.
    summary = args.build_record.parent / "slice" / "slice-summary.json"

    if summary.is_file():
        freshness = slice_freshness(json.loads(summary.read_text(encoding="utf-8")))
        payload["slice"] = {"summary": str(summary), **freshness.as_dict()}

    emit(payload)

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    record = complete_enclosure_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit({"trial_record": str(record)})

    return 0


def _enclosure_hardware(args: argparse.Namespace) -> int:
    emit(
        {
            "boards": list(list_boards()),
            "displays": list(list_displays()),
            "fans": list(list_fans()),
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
    build.add_argument("--board", help="catalogued board identifier")
    build.add_argument(
        "--board-file",
        type=Path,
        default=None,
        help=(
            "a board described in a JSON file, for a board the catalog lacks; see "
            "`zcad-validation board check` and `board template`"
        ),
    )
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
        type=_height_or_auto,
        default=None,
        help=(
            "height of the display's underside above the board's underside, or "
            "auto (the default): 8 mm, or the lowest above it, in 0.5 mm steps, "
            "that clears the board's parts by --board-display-clearance-mm"
        ),
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
        "--lid",
        choices=LID_ATTACHMENTS,
        default="screws",
        help=(
            "screw the lid into heat-set inserts, snap it on, hinge it on a "
            "pin and close it with a catch, or slide it in grooves"
        ),
    )
    build.add_argument(
        "--power-w",
        type=float,
        default=0.0,
        help="power, in watts, that the catalog lacks: a hat, an SSD, a peripheral",
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
        "--slide-clearance-mm",
        type=float,
        default=0.2,
        help="the gap per side around a sliding lid",
    )
    build.add_argument(
        "--hinge-pin",
        default="M3",
        help="the screw (with a nut) that is a hinged lid's pin",
    )
    build.add_argument(
        "--countersunk",
        action="store_true",
        help="sink flat-head lid screws flush",
    )
    build.add_argument(
        "--locating-lip",
        action="store_true",
        help="hang a lip under a screwed lid that keys it onto the base",
    )
    build.add_argument(
        "--active-cooler",
        action="store_true",
        help=(
            "fit a Raspberry Pi 5's Active Cooler: the enclosure clears it and "
            "vents the lid over its fan"
        ),
    )
    build.add_argument(
        "--mount",
        choices=MOUNTS,
        default=None,
        help="add four mount pads under the floor and a plate that bolts to them",
    )
    build.add_argument("--mount-plate-mm", type=float, default=4.0)
    build.add_argument(
        "--stack-profile",
        type=Path,
        default=None,
        help="the stack profile file a --mount stack plate is built to",
    )
    build.add_argument(
        "--vent-pattern",
        choices=PATTERNS,
        default="slots",
        help=(
            "the shape of the vents sized by --vent-area-mm2: slots, a hex grid, "
            "round holes, or louvers in the walls"
        ),
    )
    build.add_argument(
        "--vent-area-mm2",
        type=float,
        default=0.0,
        help=(
            "free area, in mm2, of the inlets low in the long walls; the outlets "
            "in the lid are at least as large"
        ),
    )
    build.add_argument(
        "--fan",
        choices=list_fans(),
        default=None,
        help=(
            "fit a catalogued fan inside the lid or against a long wall, screwed "
            "from outside through a guarded round opening"
        ),
    )
    build.add_argument(
        "--fan-position",
        choices=FAN_POSITIONS,
        default="lid",
        help="where the fan goes: in the lid, or against a long wall",
    )
    build.add_argument(
        "--fan-direction",
        choices=FAN_DIRECTIONS,
        default="out",
        help="which way it blows, into the box or out of it; recorded, not drawn",
    )
    build.add_argument(
        "--fan-offset-x-mm",
        type=float,
        default=0.0,
        help="move the fan from the middle: in X on the lid, along the wall on a wall",
    )
    build.add_argument(
        "--fan-offset-y-mm",
        type=float,
        default=0.0,
        help="move the fan from the middle: in Y on the lid, up the wall on a wall",
    )
    build.add_argument(
        "--vent-slots",
        type=int,
        default=0,
        help="vent slots in each long wall that carries no opening",
    )
    build.add_argument(
        "--minimum-opening-web-mm",
        type=float,
        default=MINIMUM_OPENING_WEB_MM,
        help=(
            "merge openings in one wall that would leave less wall than this "
            "between them; 0 keeps them apart"
        ),
    )
    build.add_argument(
        "--compensation-profile",
        type=Path,
        help="take hole compensation from this printer and material profile",
    )
    build.add_argument(
        "--hole-compensation-mm",
        type=float,
        default=0.0,
        help="widen every hole and opening by this much for an undersizing printer",
    )
    build.add_argument(
        "--no-display-retainer",
        dest="display_retainer",
        action="store_false",
        help="leave the display loose under its window",
    )
    build.add_argument(
        "--slice",
        action="store_true",
        help=(
            "also slice both parts onto one plate with Bambu Studio, in "
            "<output-directory>/slice, and open the first trial"
        ),
    )
    build.add_argument(
        "--slicer-profile",
        type=Path,
        default=Path("profiles/slicers/bambu-studio-a1-mini-petg-validation.json"),
    )
    build.set_defaults(handler=_enclosure_build)

    revise = enclosure_commands.add_parser(
        "revise",
        help="propose the next design from a completed trial, and optionally build it",
    )
    revise.add_argument("--trial-directory", required=True, type=Path)
    revise.add_argument(
        "--output-directory",
        type=Path,
        help="build the revised design here, recording what it revises",
    )
    revise.add_argument("--review", action="store_true")
    revise.add_argument("--slice", action="store_true")
    revise.add_argument(
        "--slicer-profile",
        type=Path,
        default=Path("profiles/slicers/bambu-studio-a1-mini-petg-validation.json"),
    )
    revise.set_defaults(handler=_enclosure_revise)

    trial = enclosure_commands.add_parser(
        "trial", help="record how a printed enclosure fitted"
    )
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    trial_start = trial_commands.add_parser(
        "start", help="write the next trial's observation and measurement templates"
    )
    trial_start.add_argument("--build-record", required=True, type=Path)
    trial_start.set_defaults(handler=_trial_start)
    trial_complete = trial_commands.add_parser(
        "complete", help="validate a filled-in trial and write its record"
    )
    trial_complete.add_argument("--trial-directory", required=True, type=Path)
    trial_complete.add_argument(
        "--disposition",
        required=True,
        choices=[disposition.value for disposition in EnclosureTrialDisposition],
    )
    trial_complete.add_argument("--material-profile", default="petg")
    trial_complete.add_argument("--notes", default="")
    trial_complete.set_defaults(handler=_trial_complete)
