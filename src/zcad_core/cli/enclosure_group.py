"""zcad-validation enclosure-group build: a row of Raspberry Pi 5 bays."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.cli._common import emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.enclosure_group import (
    BAY_KINDS,
    Bay,
    GroupDesign,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")
_REVIEW_LID_LIFT_MM = 25.0


_BAY_OPTIONS = {"standoff": "standoff_height_mm", "headroom": "headroom_mm"}


def _bay(text: str) -> Bay:
    """One bay from ``kind`` or ``kind:standoff=10:headroom=30``."""

    kind, *options = (part.strip() for part in text.split(":"))
    kinds = [known for known in BAY_KINDS if known == kind]

    if not kinds:
        raise ValueError(f"bay kind must be one of {BAY_KINDS}; got '{kind}'")

    heights: dict[str, float] = {}

    for option in options:
        name, _, value = option.partition("=")

        if name not in _BAY_OPTIONS or not value:
            raise ValueError(
                f"bay option must be standoff=<mm> or headroom=<mm>; got '{option}'"
            )

        try:
            heights[_BAY_OPTIONS[name]] = float(value)
        except ValueError:
            raise ValueError(f"bay option '{option}' needs a number") from None

    return Bay(kind=kinds[0], **heights)


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
        }
        for layout in group.bays
    ]


def _write_review(group: GroupEnclosure, directory: Path, name: str) -> Path:
    """The enclosure with its lid lifted, and each Pi's envelope, as STEP."""

    directory.mkdir(parents=True, exist_ok=True)
    lid = group.lid.translate((0, 0, _REVIEW_LID_LIFT_MM))
    assembly = cq.Assembly()
    assembly.add(group.base, name="base", color=cq.Color(0.6, 0.6, 0.65))
    assembly.add(lid, name="lid", color=cq.Color(0.3, 0.5, 0.8, 0.5))

    for identifier, shape in group.hardware.items():
        assembly.add(shape, name=identifier, color=cq.Color(0.1, 0.6, 0.3))

    path = directory / f"{name}-review.step"
    assembly.export(str(path))

    return path


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
    )
    group = build_group_enclosure(bays, design=design)
    name = args.name or f"pi5-group-{len(bays)}bay"
    profile = load_printer_profile(args.printer_profile)
    _require_fits_bed(group, profile)
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="enclosure",
            parts={"base": group.base, "lid": group.lid},
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
    review_path = _write_review(group, args.output_directory / "review", name)
    join = (
        f"{group.fastener.identifier} x {group.recommended_join_screw_mm} mm, "
        f"{len(group.join_positions)} per joint"
        if group.recommended_join_screw_mm
        else None
    )
    emit(
        {
            "design_name": name,
            "bays": [bay.kind for bay in bays],
            "bay_heights": _bay_summary(group),
            "outer_size_mm": list(group.outer_size_mm),
            "checks": group.checks,
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "screws": {
                "lid": f"{group.fastener.identifier} x "
                f"{group.recommended_lid_screw_mm} mm, "
                f"{len(group.lid_boss_positions)} per unit",
                "join": join,
                "pi_mount": "M2.5 self-tapping, 4 per Pi",
            },
            "review_step": str(review_path),
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
            "a bay can set its own heights, as pi5:standoff=10:headroom=30"
        ),
    )
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--name")
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.add_argument("--wall-mm", type=float, default=2.0)
    build.add_argument("--floor-mm", type=float, default=2.0)
    build.add_argument("--lid-mm", type=float, default=3.0)
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
        "--no-join-bolts",
        dest="join_bolts",
        action="store_false",
        help="omit the bolt features that join a second unit",
    )
    build.set_defaults(handler=_group_build)
