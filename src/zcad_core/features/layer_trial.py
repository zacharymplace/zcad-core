"""Print records for electronics layers: what was built, and how it fitted a board.

``stack layer build`` writes a ``layer-build.json`` build record beside the exported parts: the layer
file and the board it names by hash, the settings the layer was built with, what the build said of it
(the spacer's height, the holes, the openings), each part's STL hash, and the dimensions a trial
measures. A trial then records one print of exactly those parts, in the style of
:mod:`zcad_core.features.enclosure_trial`:

1. :func:`start_layer_trial` writes ``trials/trial-NNN/`` with ``observations.json`` and
   ``measurements.json`` listing the checks and dimensions that apply to this layer, and
   ``fitting.json`` for the readings of fitting it to a board.
2. Fill them in after printing and fitting it to the real board.
3. :func:`complete_layer_trial` validates them and writes ``layer-trial.json``. A completed trial is
   never overwritten.

``fitting.json`` holds the **air** a feeler gauge finds over the board's tallest part, whether the
**bolts pass** every hole, and a **count of assemblies** with whether anything wore. The engine states no
limit for any of them, and nothing about a board's function.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.features.enclosure_trial import (
    MEASUREMENTS,
    OBSERVATIONS,
    EnclosureTrialDisposition,
    _measurements,
    _observations,
    _read,
    sha256,
)
from zcad_core.features.stack_layers import LAYER_RECORD_KIND, NOT_CLAIMED, Layer
from zcad_core.geometry.cadquery_support import workplane_shape

LAYER_BUILD_SCHEMA_VERSION = "1.0.0"
LAYER_TRIAL_SCHEMA_VERSION = "1.0.0"
RECORD_KIND = LAYER_RECORD_KIND
BUILD_RECORD = "layer-build.json"
TRIAL_RECORD = "layer-trial.json"
FITTING = "fitting.json"

NO_LIMIT = (
    "The engine states no limit for any reading here, and no figure to compare one with: it "
    "records what was measured and what was seen, and says nothing about a board's function."
)
_GUIDANCE = {
    "printed_cleanly": (
        "The plate and the spacers printed without warping, stringing into a hole or an "
        "opening, or a failed wall"
    ),
    "spacers_stand_flat": (
        "Each spacer stands flat on the board's face at its hole, clear of every part, and a "
        "screw passes through its bore"
    ),
    "plate_seats": (
        "The plate sits on the spacers, level, and a screw passes the plate, the spacer and the "
        "board's hole at every position"
    ),
    "openings_line_up": (
        "Each opening in the plate lies over its part, and a part reached from an edge is "
        "reached through the notch"
    ),
    "clears_tallest_part": "The plate clears the board's tallest part, with air over it",
}


def layer_checks() -> list[str]:
    """The checks a trial asks of a layer. Every board has a cable connector, so the plate
    always has an opening to line up."""

    return [
        "printed_cleanly",
        "spacers_stand_flat",
        "plate_seats",
        "openings_line_up",
        "clears_tallest_part",
    ]


def check_guidance(name: str) -> str:
    """What to do and look for in one check."""

    return _GUIDANCE[name]


def nominal_measurements(layer: Layer) -> dict[str, float]:
    """The sizes a trial measures with calipers, in mm, from the solids as built."""

    plate = workplane_shape(layer.parts["plate"]).BoundingBox()
    spacer = workplane_shape(layer.parts["spacer"]).BoundingBox()

    return {
        "plate_width_mm": round(plate.xlen, 3),
        "plate_depth_mm": round(plate.ylen, 3),
        "plate_thickness_mm": round(plate.zlen, 3),
        "spacer_height_mm": round(spacer.zlen, 3),
        "spacer_outer_mm": round(spacer.xlen, 3),
        "spacer_bore_mm": float(layer.summary["spacer_bore_mm"]),
    }


def write_layer_record(
    output_directory: Path,
    *,
    layer: Layer,
    design_name: str,
    printer_profile_id: str,
    part_stls: dict[str, Path],
) -> Path:
    """Write ``layer-build.json``; refuses to replace one."""

    path = output_directory / BUILD_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    spec = layer.spec
    summary = layer.summary
    record = {
        "schema_version": LAYER_BUILD_SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "design_name": design_name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "layer_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "board": {
            "identifier": summary["board"],
            "path": str(spec.board_path),
            "sha256": spec.board_sha256,
        },
        "settings": {
            "fastener": spec.fastener,
            "clearance_mm": spec.clearance_mm,
            "spacer_mm": summary["spacer_mm"],
            "plate_mm": spec.plate_mm,
            "wall_mm": spec.wall_mm,
        },
        "summary": summary,
        "printer_profile_id": printer_profile_id,
        "parts": {
            name: {"stl_path": str(stl), "stl_sha256": sha256(stl)}
            for name, stl in part_stls.items()
        },
        "fit_checks": layer.checks,
        "checks": layer_checks(),
        "nominal_measurements_mm": nominal_measurements(layer),
        "not_claimed": list(layer.notes) or [NOT_CLAIMED],
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")

    return path


def _fitting_template(build: dict[str, Any]) -> dict[str, Any]:
    """The fitting readings: blanks for a feeler gauge, a yes-or-no and a count. Leave a
    reading blank when it was not taken."""

    return {
        "not_a_limit": NO_LIMIT,
        "designed": {
            "air_over_tallest_mm": build["settings"]["clearance_mm"],
            "tallest_part": build["summary"]["tallest_part"],
        },
        "guidance": (
            "air_over_tallest_mm: the gap a feeler gauge finds between the plate and the board's "
            "tallest part; bolts_pass_all_holes: a screw goes through plate, spacer and board at "
            "every hole; assemblies_counted: how many times it was put together and taken apart, "
            "and anything_wore whether it or the board's holes wore or cracked"
        ),
        "air_over_tallest_mm": None,
        "bolts_pass_all_holes": None,
        "assemblies_counted": None,
        "anything_wore": None,
        "notes": "",
    }


def start_layer_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation, measurement and fitting templates."""

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
    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )
    (trial / MEASUREMENTS).write_text(
        json.dumps(measurements, indent=2) + "\n", encoding="utf-8"
    )
    (trial / FITTING).write_text(
        json.dumps(_fitting_template(build), indent=2) + "\n", encoding="utf-8"
    )

    return trial


def _fitting_readings(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's fitting readings, validated, set beside what was designed; ``None``
    when none was taken."""

    path = trial / FITTING
    entry = _read(path) if path.is_file() else {}
    where = "fitting.json"
    air = entry.get("air_over_tallest_mm")
    bolts = entry.get("bolts_pass_all_holes")
    count, wore = entry.get("assemblies_counted"), entry.get("anything_wore")

    if air is not None and (
        isinstance(air, bool) or not isinstance(air, int | float) or air < 0
    ):
        raise ValueError(
            f"{where}: air_over_tallest_mm must be a number from zero, not {air!r}"
        )

    if bolts is not None and not isinstance(bolts, bool):
        raise TypeError(f"{where}: bolts_pass_all_holes must be true or false")

    if count is None:
        if wore is not None:
            raise ValueError(f"{where}: anything_wore needs assemblies_counted")
    elif isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"{where}: assemblies_counted must be a whole number from 1")
    elif not isinstance(wore, bool):
        raise TypeError(f"{where}: anything_wore must be true or false")

    if air is None and bolts is None and count is None:
        return None

    designed = build["settings"]["clearance_mm"]

    return {
        "air_over_tallest_mm": None if air is None else float(air),
        "designed_air_mm": designed,
        "air_shortfall_mm": None if air is None else round(designed - float(air), 3),
        "tallest_part": build["summary"]["tallest_part"],
        "bolts_pass_all_holes": bolts,
        "assemblies_counted": count,
        "anything_wore": wore,
        "notes": entry.get("notes", ""),
        "not_a_limit": NO_LIMIT,
    }


def complete_layer_trial(
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
            f"Trial already completed: {record_path}; record another print as the next trial"
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
    fitting = _fitting_readings(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]

    if (
        disposition is not EnclosureTrialDisposition.FAIL
        and not measurements
        and fitting is None
    ):
        raise ValueError(
            f"A {disposition.value} trial needs at least one measurement or fitting reading"
        )

    if disposition is EnclosureTrialDisposition.PASS and failed:
        raise ValueError(f"A passing trial cannot have failed checks: {failed}")

    record = {
        "schema_version": LAYER_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": hashlib.sha256(build_path.read_bytes()).hexdigest(),
        "board_sha256": build["board"]["sha256"],
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
        "fitting": fitting,
        "notes": notes,
        "not_claimed": build.get("not_claimed", []),
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path
