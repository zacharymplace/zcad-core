"""zcad-validation enclosure-group build: a row of Raspberry Pi 5 bays."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.cli._common import emit
from zcad_core.cli.enclosure import hinge_payload, slide_payload
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.connector_cutouts import MINIMUM_OPENING_WEB_MM
from zcad_core.features.enclosure_group import (
    BAY_KINDS,
    OPENING_WALLS,
    Bay,
    BayOpening,
    GroupDesign,
    GroupEnclosure,
    OpeningWall,
    build_group_enclosure,
    print_oriented_parts,
)
from zcad_core.features.enclosure_group_dividers import Divider
from zcad_core.features.enclosure_group_join import check_join, check_join_records
from zcad_core.features.enclosure_group_model import (
    GROUP_LID_ATTACHMENTS,
    GROUP_MOUNTS,
    JOINT_FACES,
    PASS_THROUGH_SIDES,
    SLIDE_ENTRIES,
)
from zcad_core.features.enclosure_group_trial import (
    complete_group_trial,
    start_group_trial,
    write_group_record,
)
from zcad_core.features.enclosure_group_viewer import (
    DATA_FILE,
    DEFAULT_CONFIGS,
    PAGE_FILE,
    ViewerConfig,
    viewer_data,
    viewer_page,
)
from zcad_core.features.enclosure_thermal import (
    CONVECTION_W_M2K,
    DEFAULT_AMBIENT_C,
    DEFAULT_SERVICE_LIMIT_C,
    ThermalEstimate,
    estimate_thermal,
    require_not_too_hot,
)
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.lid_hinge import swung_lid
from zcad_core.features.lid_slide import slid_lid
from zcad_core.features.mount_stack import (
    require_plate_fits_bed,
    require_top_fits_bed,
)
from zcad_core.features.mounts import MountPlate, flexure_payload
from zcad_core.features.vent_patterns import PATTERNS
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import load_board
from zcad_core.hardware.thermal import PowerFigure
from zcad_core.printing import SliceError, slice_models
from zcad_core.profiles import (
    load_printer_profile,
    load_thermal_profile,
    material_service_limit_c,
)

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")
DEFAULT_SLICER_PROFILE = Path(
    "profiles/slicers/bambu-studio-a1-mini-petg-validation.json"
)
_REVIEW_LID_LIFT_MM = 25.0


_BAY_OPTIONS = {"standoff": "standoff_height_mm", "headroom": "headroom_mm"}
_OPENING_SYNTAX = "front=<width>x<height>[@<offset>[/<bottom>]]"


def _opening(wall: OpeningWall, value: str) -> BayOpening:
    """An opening from ``20x10``, ``20x10@-5``, or ``20x10@-5/3``: width and
    height, the offset from the shelf's middle, and the height above the
    floor, all in millimetres."""

    size, _, placement = value.partition("@")
    width, _, height = size.partition("x")
    offset, _, bottom = placement.partition("/")

    try:
        return BayOpening(
            wall=wall,
            width_mm=float(width),
            height_mm=float(height),
            offset_mm=float(offset) if offset else 0.0,
            bottom_mm=float(bottom) if bottom else 0.0,
        )
    except ValueError:
        raise ValueError(
            f"an opening must be {wall}=<width>x<height>[@<offset>[/<bottom>]] "
            f"in millimetres; got '{wall}={value}'"
        ) from None


_DIVIDER_TOKENS = "solid, vents, notch, ties, h<height>"


def _divider(value: str) -> Divider:
    """A divider from tokens joined by ``+``: ``solid`` for a plain full-height
    wall, ``vents``, ``notch``, ``ties``, and ``h12`` for a low one 12 mm tall,
    as in ``vents+notch+ties`` or ``h12``."""

    flags = {"solid": False, "vents": False, "notch": False, "ties": False}
    height: float | None = None

    for token in (part.strip() for part in value.split("+")):
        if token in flags:
            flags[token] = True
        elif token.startswith("h") and token[1:]:
            try:
                height = float(token[1:])
            except ValueError:
                raise ValueError(
                    f"a divider is {_DIVIDER_TOKENS}, joined by +; got '{token}'"
                ) from None
        else:
            raise ValueError(
                f"a divider is {_DIVIDER_TOKENS}, joined by +; got '{token}'"
            )

    return Divider(
        height_mm=height,
        vents=flags["vents"],
        notch=flags["notch"],
        tie_slots=flags["ties"],
    )


_BOARD_OPTIONS = (
    "file=<board file>, rotate=<0|90|180|270>, align=<front|center|back>, "
    "screw=<M2.5>; for a fan bay, fan=<identifier>, direction=<in|out>"
)


def _board_option(name: str, value: str, settings: dict[str, Any]) -> bool:
    """Take a board bay's option into ``settings``; ``False`` if it is not one."""

    if name == "file":
        settings["board"] = load_board(Path(value))
    elif name == "rotate":
        try:
            settings["rotate"] = int(value)
        except ValueError:
            raise ValueError(
                f"rotate must be 0, 90, 180 or 270; got '{value}'"
            ) from None
    elif name in ("align", "screw"):
        settings[name] = value
    elif name == "fan":
        settings["fan"] = value
    elif name == "direction":
        settings["fan_direction"] = value
    else:
        return False

    return True


def _bay(text: str) -> Bay:
    """One bay from ``kind``, with any of ``:standoff=10``, ``:headroom=30``,
    ``:front=20x10``, ``:back=20x10@-5/3``, and ``:divider=vents+notch``; a board
    bay is ``board:file=PATH`` with ``:rotate=``, ``:align=`` and ``:screw=``."""

    kind, *options = (part.strip() for part in text.split(":"))
    kinds = [known for known in BAY_KINDS if known == kind]

    if not kinds:
        raise ValueError(f"bay kind must be one of {BAY_KINDS}; got '{kind}'")

    heights: dict[str, Any] = {}
    board: dict[str, Any] = {}
    openings: list[BayOpening] = []
    divider: Divider | None = None

    for option in options:
        name, _, value = option.partition("=")
        walls = [known for known in OPENING_WALLS if known == name]

        if walls and value:
            openings.append(_opening(walls[0], value))
            continue

        if name == "divider" and value:
            divider = _divider(value)
            continue

        if value and _board_option(name, value, board):
            continue

        if name not in _BAY_OPTIONS or not value:
            raise ValueError(
                "bay option must be standoff=<mm>, headroom=<mm>, "
                f"{_OPENING_SYNTAX}, divider=<{_DIVIDER_TOKENS}>, or, for a board "
                f"bay, {_BOARD_OPTIONS}; got '{option}'"
            )

        try:
            heights[_BAY_OPTIONS[name]] = float(value)
        except ValueError:
            raise ValueError(f"bay option '{option}' needs a number") from None

    return Bay(
        kind=kinds[0],
        openings=tuple(openings),
        divider=divider,
        **heights,
        **board,
    )


def _bays(text: str) -> tuple[Bay, ...]:
    return tuple(_bay(part) for part in text.split(",") if part.strip())


def _bay_summary(group: GroupEnclosure) -> list[dict[str, object]]:
    return [
        {
            "bay": layout.index,
            "kind": layout.kind,
            "standoff_mm": layout.standoff_height_mm,
            "board_top_z_mm": layout.board_top_z_mm,
            "room_above_board_mm": round(group.room_above_board_mm(layout), 2),
            "openings": [
                {
                    "wall": opening.wall,
                    "width_mm": opening.width_mm,
                    "height_mm": opening.height_mm,
                    "offset_mm": opening.offset_mm,
                    "bottom_mm": opening.bottom_mm,
                }
                for opening in layout.openings
            ],
            "divider": (
                None
                if layout.divider is None
                else {
                    "full_height": layout.divider.full_height,
                    "height_mm": layout.divider.height_mm,
                    "vents": layout.divider.vents,
                    "notch": layout.divider.notch,
                    "tie_slots": layout.divider.tie_slots,
                    "left_face_x_mm": layout.divider_start_mm + group.design.wall_mm,
                }
            ),
        }
        for layout in group.bays
    ]


def _review_pose(group: GroupEnclosure) -> tuple[Callable[[cq.Shape], cq.Shape], str]:
    """How the lid is shown, as a move for the lid and what it carries: open on
    its pin, slid out over its entry wall, or lifted straight up."""

    hinge, slide = group.hinge, group.slide

    if hinge is not None:
        return (
            lambda shape: swung_lid(shape, hinge, hinge.swing_degrees),
            f"open {hinge.swing_degrees:.0f} degrees on its pin",
        )

    if slide is not None:
        return (
            lambda shape: slid_lid(shape, slide, slide.travel_mm),
            (f"slid {slide.travel_mm:.0f} mm out over the {slide.entry_edge} wall"),
        )

    return (
        lambda shape: shape.translate(cq.Vector(0, 0, _REVIEW_LID_LIFT_MM)),
        "lifted",
    )


def _review_lid(group: GroupEnclosure) -> tuple[Any, str]:
    """The lid as the review shows it."""

    move, pose = _review_pose(group)
    lid = workplane_shape(group.lid)

    return move(lid), pose


def _write_review(
    group: GroupEnclosure, directory: Path, name: str
) -> tuple[Path, str]:
    """The enclosure with its lid open, slid out, or lifted, and each Pi's
    envelope, as STEP."""

    directory.mkdir(parents=True, exist_ok=True)
    move, pose = _review_pose(group)
    assembly = cq.Assembly()
    assembly.add(group.base, name="base", color=cq.Color(0.6, 0.6, 0.65))
    assembly.add(
        move(workplane_shape(group.lid)), name="lid", color=cq.Color(0.3, 0.5, 0.8, 0.5)
    )

    for identifier, shape in group.hardware.items():
        # A fan screwed to the lid goes where the lid does.
        placed = move(shape) if identifier in group.lid_carried else shape
        assembly.add(placed, name=identifier, color=cq.Color(0.1, 0.6, 0.3))

    path = directory / f"{name}-review.step"
    assembly.export(str(path))

    return path, pose


def _screw_style(mount: MountPlate) -> str:
    return "in a head recess" if mount.stack is not None else "countersunk"


def _require_fits_bed(group: GroupEnclosure, profile: dict[str, Any]) -> None:
    """Say how to split a row that will not lie flat on the bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, _ = group.outer_size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    fits_turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or fits_turned):
        raise ValueError(
            f"The {len(group.bays)}-bay row is {width:.0f} x {depth:.0f} mm; the "
            f"printer's bed is {volume['x']:.0f} x {volume['y']:.0f} mm. Build "
            "shorter units and bolt them together: each unit's left wall takes "
            "the join screws from the next unit's right wall."
        )

    _require_ears_fit_bed(group, volume)
    require_plate_fits_bed(group.mount, volume)
    require_top_fits_bed(group.stack_top, volume)


def _require_ears_fit_bed(group: GroupEnclosure, volume: dict[str, Any]) -> None:
    """Refuse rack ears longer than the bed: they are one piece each."""

    if group.mount is None or group.mount.pieces is None:
        return

    bed = sorted((volume["x"], volume["y"]))

    for name, piece in group.mount.pieces.items():
        bounds = workplane_shape(piece).BoundingBox()
        small, large = sorted((bounds.xlen, bounds.ylen, bounds.zlen))[1:]

        if large > bed[1] or small > bed[0]:
            raise ValueError(
                f"The {name} part is {large:.0f} x {small:.0f} mm; the "
                f"printer's bed is {bed[1]:.0f} x {bed[0]:.0f} mm. An ear "
                "reaches from the enclosure to the rack's edge, so a narrower "
                "enclosure needs longer ears; build a wider one or use another "
                "mount."
            )


def _slice(
    args: argparse.Namespace, group: GroupEnclosure, name: str
) -> dict[str, object]:
    """Write print-oriented STLs and slice the base and the lid, each on a
    plate of its own: together they would not fit the bed."""

    print_directory = args.output_directory / "print"
    print_directory.mkdir()
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
                summary_fields={"design_name": name, "part": part},
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


def _group_viewer(args: argparse.Namespace) -> int:
    """Write the 3D viewer page and its mesh data, for the default set of
    enclosures or the ``--bays`` rows given."""

    configs = (
        tuple(
            ViewerConfig(
                key=f"custom-{index}",
                name=spec,
                blurb="Built from --bays.",
                bays=_bays(spec),
            )
            for index, spec in enumerate(args.bays, 1)
        )
        if args.bays
        else DEFAULT_CONFIGS
    )
    directory = args.output_directory
    targets = {PAGE_FILE: directory / PAGE_FILE, DATA_FILE: directory / DATA_FILE}

    for target in targets.values():
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite {target}")

    data = viewer_data(configs)
    directory.mkdir(parents=True, exist_ok=True)
    targets[DATA_FILE].write_text(
        json.dumps(data, separators=(",", ":")), encoding="utf-8"
    )
    targets[PAGE_FILE].write_text(
        viewer_page(standalone=args.standalone), encoding="utf-8"
    )
    emit(
        {
            "page": str(targets[PAGE_FILE]),
            "data": str(targets[DATA_FILE]),
            "data_bytes": targets[DATA_FILE].stat().st_size,
            "standalone": args.standalone,
            "configurations": [
                {"key": entry["key"], "name": entry["name"], "size_mm": entry["size"]}
                for entry in data
            ],
            "view": f"python3 -m http.server --directory {directory}",
        }
    )

    return 0


def _parts(group: GroupEnclosure) -> dict[str, cq.Workplane]:
    parts = {"base": group.base, "lid": group.lid}

    if group.mount is not None:
        parts.update(group.mount.parts)

    if group.stack_top is not None:
        parts["stack_top"] = group.stack_top.plate

    return parts


def _stack_top_payload(group: GroupEnclosure) -> dict[str, object] | None:
    top = group.stack_top

    if top is None:
        return None

    return {
        "cells": list(top.cells),
        "size_mm": [round(top.size_mm[0], 3), round(top.size_mm[1], 3)],
        "thickness_mm": round(top.thickness_mm, 3),
        "floor_mm": round(top.floor_mm, 3),
        "screws": f"{group.fastener.identifier} x {top.recommended_screw_mm} mm, "
        f"{len(group.lid_boss_positions)} through the plate and the lid in place of the "
        "lid's own, in a head recess",
        "screw_reach_mm": round(top.screw_reach_mm, 3),
        "stack": top.stack,
    }


def _group_warnings(group: GroupEnclosure) -> list[str]:
    """What a fan's figures were not checked against."""

    return [
        f"{fan.model}: its figures were not read from the maker's own page; check "
        f"them{fan.unverified}"
        for fan in group.fans
        if not fan.datasheet_read
    ]


def _heat_sources(
    bays: tuple[Bay, ...],
) -> tuple[list[str], dict[str, PowerFigure]]:
    """The parts that give off heat, by catalog identifier, and the figures a
    board file brings of its own. A fitted Pi counts; a reserved bay is empty
    until a Pi goes in it. A board with no power section is counted as unknown, and
    the estimate says so."""

    parts: list[str] = []
    figures: dict[str, PowerFigure] = {}

    for bay in bays:
        if bay.kind == "pi5":
            parts.append("RASPBERRY_PI_5")
        elif bay.kind == "board" and bay.board is not None:
            parts.append(bay.board.identifier)

            if bay.board.power_figure is not None:
                figures[bay.board.identifier] = bay.board.power_figure
        elif bay.kind == "fan" and bay.fan is not None:
            parts.append(bay.fan)

    return parts, figures


def _moves_air(group: GroupEnclosure, bays: tuple[Bay, ...]) -> bool:
    """Whether anything lets air through: slots over a Pi's fan or a board's part,
    a vent pattern, or a fan."""

    slots = group.design.vents and any(
        bay.kind == "pi5"
        or (
            bay.kind == "board"
            and bay.board is not None
            and any(part.lid_vent for part in bay.board.components)
        )
        for bay in bays
    )

    return bool(
        slots or group.design.vent_area_mm2 or any(bay.kind == "fan" for bay in bays)
    )


def _group_thermal(
    group: GroupEnclosure, bays: tuple[Bay, ...], args: argparse.Namespace
) -> ThermalEstimate:
    """The temperature estimate for the row, counting each fitted Pi, each board
    that gives a power figure, and each fan; a reserved bay is empty until a Pi
    goes in it."""

    width, depth, _ = group.outer_size_mm
    height = group.cavity_top_z_mm + group.design.lid_mm
    parts, figures = _heat_sources(bays)
    coefficient, source = CONVECTION_W_M2K, "the default, an assumption"

    if args.thermal_profile is not None:
        profile = load_thermal_profile(args.thermal_profile)
        coefficient, source = profile.coefficient_w_m2k, profile.describe()

    estimate = estimate_thermal(
        parts,
        outer_size_mm=(width, depth, height),
        declared_power_w=args.power_w,
        ambient_c=args.ambient_c,
        coefficient_w_m2k=coefficient,
        coefficient_source=source,
        figures=figures,
        closed=not _moves_air(group, bays),
        limit_c=material_service_limit_c(args.material_profile)
        or DEFAULT_SERVICE_LIMIT_C,
    )
    require_not_too_hot(estimate, allow_hot=args.allow_hot)

    return estimate


def _trial_start(args: argparse.Namespace) -> int:
    trial = start_group_trial(args.build_record)
    payload: dict[str, object] = {
        "trial": str(trial),
        "observations": str(trial / "observations.json"),
        "measurements": str(trial / "measurements.json"),
        "thermal": str(trial / "thermal.json"),
    }

    if (trial / "lid.json").is_file():
        payload["lid"] = str(trial / "lid.json")

    emit(payload)

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    record = complete_group_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit(
        {
            "trial_record": str(record),
            "passed": json.loads(record.read_text(encoding="utf-8"))["passed"],
        }
    )

    return 0


def _size(text: str | None) -> tuple[float, float] | None:
    """A ``<width>x<height>`` in millimetres, or ``None``."""

    if text is None:
        return None

    width, _, height = text.partition("x")

    try:
        return float(width), float(height)
    except ValueError:
        raise ValueError(
            f"a pass-through is <width>x<height> in millimetres; got '{text}'"
        ) from None


def _add_joint_arguments(build: argparse.ArgumentParser) -> None:
    build.add_argument(
        "--joint",
        choices=JOINT_FACES,
        default="fractions",
        help=(
            "where the join bolts go: at fractions of the unit's depth (the "
            "default, which mates only units of the same depth), or on the "
            "standard joint face, which mates any two units"
        ),
    )
    build.add_argument(
        "--pass-through",
        help="a cable opening <width>x<height> in the join walls (standard joint)",
    )
    build.add_argument(
        "--pass-through-sides", choices=PASS_THROUGH_SIDES, default="both"
    )


def _check_join(args: argparse.Namespace) -> int:
    """Build two units and say whether the second bolts to the first's right
    wall; exits 1 if it does not."""

    if args.left_record is not None or args.right_record is not None:
        if args.left_record is None or args.right_record is None:
            raise ValueError("give both --left-record and --right-record")

        report = check_join_records(
            json.loads(args.left_record.read_text(encoding="utf-8")),
            json.loads(args.right_record.read_text(encoding="utf-8")),
        )
        emit(
            {
                "passed": report.passed,
                "checks": report.checks,
                "details": report.details,
                "notes": list(report.notes),
            }
        )

        return 0 if report.passed else 1

    if args.left_bays is None or args.right_bays is None:
        raise ValueError(
            "give both --left-bays and --right-bays, or both --left-record and "
            "--right-record"
        )

    units = []

    for side in ("left", "right"):
        design = GroupDesign(
            wall_mm=args.wall_mm,
            floor_mm=args.floor_mm,
            fastener=args.fastener,
            lid_attachment=args.lid,
            joint_face=getattr(args, f"{side}_joint"),
            pass_through_mm=_size(getattr(args, f"{side}_pass_through")),
            pass_through_sides=getattr(args, f"{side}_pass_through_sides"),
        )
        units.append(
            build_group_enclosure(_bays(getattr(args, f"{side}_bays")), design=design)
        )

    report = check_join(units[0], units[1])
    emit(
        {
            "passed": report.passed,
            "checks": report.checks,
            "details": report.details,
            "notes": list(report.notes),
        }
    )

    return 0 if report.passed else 1


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
    printed = _slice(args, group, name) if args.slice and group.passed else None
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
