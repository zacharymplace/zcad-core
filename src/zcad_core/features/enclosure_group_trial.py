"""Print records for group enclosures: what was built, and how the print fitted.

``enclosure-group build`` writes an ``enclosure-group.json`` build record beside
the exported parts: the design, each bay as placed (its kind, where its slot and its
board's centre are, its heights, the board file by hash, the fan, the divider), the
joint, the lid, the temperature estimate, each part's STL hash, and the dimensions a
trial measures. A trial then records one print of exactly those parts, in the style
of :mod:`zcad_core.features.enclosure_trial`:

1. :func:`start_group_trial` writes ``trials/trial-NNN/`` with ``observations.json``
   and ``measurements.json`` listing only the checks and dimensions that apply to
   this group, ``thermal.json``, and, for a hinged or sliding lid, ``lid.json``.
2. Fill them in after printing and assembling.
3. :func:`complete_group_trial` validates them and writes
   ``enclosure-group-trial.json``. A completed trial is never overwritten.

The checks are one set for the box (clean print, the lid), and, for each bay, what
its kind asks: a board seats and is held and its plugs reach it, a fan seats and
turns, a divider fits. A pair of units has one more reading, the gap measured where
their walls meet. The thermal and lid readings are the single-board enclosure's,
read by the same code, and the engine states no limit for any of them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.features.enclosure_group_model import (
    Bay,
    BayLayout,
    GroupDesign,
    GroupEnclosure,
)
from zcad_core.features.enclosure_trial import (
    LID,
    MEASUREMENTS,
    OBSERVATIONS,
    THERMAL,
    EnclosureTrialDisposition,
    _lid,
    _lid_template,
    _measurements,
    _observations,
    _read,
    _thermal,
    _thermal_template,
    lid_summary_of,
    sha256,
)

GROUP_BUILD_SCHEMA_VERSION = "1.0.0"
GROUP_TRIAL_SCHEMA_VERSION = "1.0.0"
BUILD_RECORD = "enclosure-group.json"
TRIAL_RECORD = "enclosure-group-trial.json"

_BOX_GUIDANCE = {
    "parts_printed_cleanly": (
        "The base and lid printed without warping, stringing into openings, or "
        "failed features"
    ),
    "inserts_installed": (
        "Every heat-set insert (the lid's and the join's) went in square and sits "
        "flush with its boss"
    ),
    "lid_closes_flush": (
        "The lid sits flat on the walls and stays shut: screws draw it down without "
        "cracking a boss, the catch clicks home, or the slide lid runs home"
    ),
    "hinge_swings_free": (
        "With the pin in, the lid swings from shut to fully open without catching "
        "the base, a board, a fan, or a divider, and turns on the pin without binding"
    ),
    "catch_holds_lid": (
        "The catch clicks home as the lid closes, holds it shut when the box is "
        "shaken, and releases when you lift its lip"
    ),
    "lid_slides_free": (
        "The lid pushes in along its grooves and out over the entry wall without "
        "binding or scraping, and stops against the far wall"
    ),
    "detent_holds_lid": (
        "The detent clicks as the lid reaches home and holds it shut when the box "
        "is shaken"
    ),
    "nothing_rattles": "Nothing moves or rattles when the box is shaken",
}
_BAY_GUIDANCE = {
    "board_seats": (
        "The board sits level on its standoffs or in its cradle, and no part meets "
        "the base or the lid"
    ),
    "board_retained": (
        "The board is held without rocking: screwed to its standoffs, or clipped "
        "into its cradle"
    ),
    "ports_reach": (
        "A real plug goes fully into each connector through its opening in the "
        "wall, or through the service space and out of the front opening"
    ),
    "fan_fits": (
        "The fan sits flat against the lid, its four screws draw it down, the "
        "blades turn freely behind the guard, and it blows the way the design says"
    ),
    "divider_fits": (
        "The divider stands square between its bays, and its notch, vents and tie "
        "slots are open"
    ),
}


def box_checks(design: GroupDesign, hinge: bool, slide: bool) -> list[str]:
    """The checks for the box as a whole."""

    checks = ["parts_printed_cleanly"]

    if design.lid_attachment == "screws" or design.join_bolts:
        checks.append("inserts_installed")

    checks.append("lid_closes_flush")

    if hinge:
        checks += ["hinge_swings_free", "catch_holds_lid"]

    if slide:
        checks += ["lid_slides_free", "detent_holds_lid"]

    return [*checks, "nothing_rattles"]


def bay_checks(bays: tuple[Bay, ...]) -> list[str]:
    """The checks each bay's kind asks, named ``bay-<n>-<check>``."""

    checks = []

    for index, bay in enumerate(bays):
        if bay.kind in ("pi5", "reserved", "board"):
            checks += [
                f"bay-{index}-board_seats",
                f"bay-{index}-board_retained",
                f"bay-{index}-ports_reach",
            ]
        elif bay.kind == "fan":
            checks.append(f"bay-{index}-fan_fits")

        if bay.divider is not None:
            checks.append(f"bay-{index}-divider_fits")

    return checks


def check_guidance(name: str) -> str:
    """What to do and look for in one check."""

    if name in _BOX_GUIDANCE:
        return _BOX_GUIDANCE[name]

    kind = name.split("-", 2)[2]

    return _BAY_GUIDANCE[kind]


def nominal_measurements(group: GroupEnclosure) -> dict[str, float]:
    """The designed dimensions a trial measures with calipers, in mm."""

    design = group.design
    width, depth, _ = group.outer_size_mm
    nominals = {
        "base_outer_width_mm": width,
        "base_outer_depth_mm": depth,
        "base_height_mm": group.cavity_top_z_mm,
        "wall_thickness_mm": design.wall_mm,
        "lid_thickness_mm": design.lid_mm,
    }

    for layout in group.bays:
        nominals[f"bay_{layout.index}_slot_width_mm"] = (
            layout.slot_end_mm - layout.slot_start_mm
        )

        if layout.holds_board:
            nominals[f"bay_{layout.index}_standoff_height_mm"] = (
                layout.standoff_height_mm
            )

    if design.join_bolts:
        # Two units bolted together: their walls meet with no gap.
        nominals["joint_gap_mm"] = 0.0

    return {name: round(value, 3) for name, value in nominals.items()}


def _bay_record(bay: Bay, layout: BayLayout, wall: float) -> dict[str, Any]:
    record: dict[str, Any] = {
        "index": layout.index,
        "kind": layout.kind,
        "slot_mm": [round(layout.slot_start_mm, 3), round(layout.slot_end_mm, 3)],
        "gap_mm": [round(layout.gap_start_mm, 3), round(layout.gap_end_mm, 3)],
        "left_space_mm": layout.left_space_mm,
        "center_mm": [
            round(wall + layout.center_x_mm, 3),
            round(layout.center_y_mm, 3),
        ],
        "standoff_height_mm": layout.standoff_height_mm,
        "headroom_mm": layout.headroom_mm,
        "board_top_z_mm": round(layout.board_top_z_mm, 3),
        "divider": None if layout.divider is None else asdict(layout.divider),
    }

    if bay.board is not None:
        record["board"] = {
            "identifier": bay.board.identifier,
            "path": bay.board.origin.path,
            "sha256": bay.board.origin.sha256,
            "rotate": bay.rotate,
            "align": bay.align,
            "screw": bay.screw,
        }

    if bay.fan is not None:
        record["fan"] = {"identifier": bay.fan, "direction": bay.fan_direction}

    return record


def write_group_record(
    output_directory: Path,
    *,
    group: GroupEnclosure,
    bays: tuple[Bay, ...],
    design_name: str,
    printer_profile_id: str,
    part_stls: dict[str, Path],
    thermal: dict[str, Any] | None,
) -> Path:
    """Write ``enclosure-group.json``; refuses to replace one."""

    path = output_directory / BUILD_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    design = group.design
    checks = [
        *box_checks(design, group.hinge is not None, group.slide is not None),
        *bay_checks(bays),
    ]
    record = {
        "schema_version": GROUP_BUILD_SCHEMA_VERSION,
        "design_name": design_name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "design": asdict(design),
        "bays": [
            _bay_record(bay, layout, design.wall_mm)
            for bay, layout in zip(bays, group.bays, strict=True)
        ],
        "outer_size_mm": [round(v, 3) for v in group.outer_size_mm],
        "joint": {
            "face": design.joint_face,
            "bolts_y_z_mm": [list(p) for p in group.join_positions],
            "pass_through_mm": design.pass_through_mm,
            "pass_through_sides": design.pass_through_sides,
            "fastener": group.fastener.identifier,
        },
        "lid": lid_summary_of(group.hinge, group.slide),
        "fans": [fan.to_dict() for fan in group.fans],
        "thermal": thermal,
        "printer_profile_id": printer_profile_id,
        "parts": {
            name: {"stl_path": str(stl), "stl_sha256": sha256(stl)}
            for name, stl in part_stls.items()
        },
        "fit_checks": group.checks,
        "checks": checks,
        "nominal_measurements_mm": nominal_measurements(group),
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")

    return path


def start_group_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation and measurement templates."""

    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)
    observations = {
        check: {"result": "pending", "guidance": check_guidance(check), "notes": ""}
        for check in build["checks"]
    }
    measurements = {
        name: {"nominal_mm": nominal, "value_mm": None, "notes": ""}
        for name, nominal in build["nominal_measurements_mm"].items()
    }
    (trial / THERMAL).write_text(
        json.dumps(_thermal_template(build), indent=2) + "\n", encoding="utf-8"
    )
    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )
    (trial / MEASUREMENTS).write_text(
        json.dumps(measurements, indent=2) + "\n", encoding="utf-8"
    )

    if build.get("lid"):
        (trial / LID).write_text(
            json.dumps(_lid_template(build["lid"]), indent=2) + "\n", encoding="utf-8"
        )

    return trial


def complete_group_trial(
    trial: Path,
    *,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str = "",
) -> Path:
    """Validate a filled-in trial and write its record."""

    record_path = trial / TRIAL_RECORD

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as "
            "the next trial"
        )

    build_path = trial.parent.parent / BUILD_RECORD
    build = _read(build_path)
    changed = [
        name
        for name, part in build["parts"].items()
        if not Path(part["stl_path"]).is_file()
        or sha256(Path(part["stl_path"])) != part["stl_sha256"]
    ]

    if changed:
        raise ValueError(
            f"The printed parts no longer match the build record: {changed}"
        )

    observations = _observations(trial, build["checks"])
    measurements = _measurements(trial)
    thermal = _thermal(trial, build)
    lid = _lid(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]

    if (
        disposition is not EnclosureTrialDisposition.FAIL
        and not measurements
        and thermal is None
        and lid is None
    ):
        raise ValueError(
            f"A {disposition.value} trial needs at least one measurement, a "
            "recorded temperature, or a lid reading"
        )

    if disposition is EnclosureTrialDisposition.PASS and failed:
        raise ValueError(f"A passing trial cannot have failed checks: {failed}")

    record = {
        "schema_version": GROUP_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": hashlib.sha256(build_path.read_bytes()).hexdigest(),
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "disposition": disposition.value,
        "passed": disposition is EnclosureTrialDisposition.PASS,
        "failed_checks": failed,
        "observations": observations,
        "measurements": [
            {
                "name": m.name,
                "value_mm": m.value_mm,
                "nominal_mm": m.nominal_mm,
                "notes": m.notes,
                "deviation_mm": m.deviation_mm,
            }
            for m in measurements
        ],
        "thermal": thermal,
        "lid": lid,
        "notes": notes,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path
