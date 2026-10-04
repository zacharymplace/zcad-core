"""The review of a group enclosure: the pose of its lid, the review model, and the viewer page."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.cli._common import emit
from zcad_core.cli.enclosure_group_bays import _bays
from zcad_core.features.enclosure_group import GroupEnclosure
from zcad_core.features.enclosure_group_viewer import (
    DATA_FILE,
    DEFAULT_CONFIGS,
    PAGE_FILE,
    ViewerConfig,
    viewer_data,
    viewer_page,
)
from zcad_core.features.lid_hinge import swung_lid
from zcad_core.features.lid_slide import slid_lid
from zcad_core.geometry.cadquery_support import workplane_shape

_REVIEW_LID_LIFT_MM = 25.0


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
