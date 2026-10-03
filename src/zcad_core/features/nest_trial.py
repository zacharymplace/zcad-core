"""Trials for holding nests and insert jigs: what was printed, and how it did its job.

``nest build`` and ``jig build`` write a build record (``nest.json``, ``jig.json``): the nest or jig
file and the part by hash, the settings, each printed part's STL hash, the checks a trial asks and
the dimensions it measures. A trial records one print of exactly those parts, in the style of
:mod:`zcad_core.features.layer_trial`:

1. :func:`start_nest_trial` and :func:`start_jig_trial` write ``trials/trial-NNN/`` with
   ``observations.json`` and ``measurements.json`` listing the checks and dimensions that apply, and a
   readings file: ``use.json`` for a nest, ``insertion.json`` for a jig.
2. Fill them in after printing and using the print on the real part.
3. :func:`complete_nest_trial` and :func:`complete_jig_trial` validate them and write
   ``nest-trial.json`` or ``jig-trial.json``. A completed trial is never overwritten.

A nest's readings are a **count of uses** and whether anything wore. A jig's are, for each insert,
whether it **went in square**, the **depth below the face** it ended at, and its **offset from the
pocket's centre**, all measured. The engine states no limit for any reading, and nothing about how
well a nest holds a part or whether an insert holds.
"""

from __future__ import annotations

import hashlib
import json
import math
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

NEST_TRIAL_SCHEMA_VERSION = "1.0.0"
JIG_TRIAL_SCHEMA_VERSION = "1.0.0"
NEST_BUILD_RECORD = "nest.json"
JIG_BUILD_RECORD = "jig.json"
NEST_TRIAL_RECORD = "nest-trial.json"
JIG_TRIAL_RECORD = "jig-trial.json"
USE = "use.json"
INSERTION = "insertion.json"

NO_LIMIT = (
    "The engine states no limit for any reading here, and no figure to compare one with: it records "
    "what was measured and what was seen, and says nothing about how well a nest holds a part or "
    "whether an insert holds."
)
_GUIDANCE = {
    "printed_cleanly": (
        "The print came off without warping, stringing into a pocket, bore or slot, or a failed wall"
    ),
    "part_seats": "The part goes down into the pocket and stands on the floor or the plate, level",
    "part_lifts_out": "The part lifts straight out by hand, with the notches or the lip if it has them",
    "part_stays_in": (
        "The part stays in the nest when the nest is tilted and knocked, held by the lip's hooks"
    ),
    "strap_holds_still": "A strap through the slots holds the nest still on the bench or in the clamp",
    "label_legible": "The label reads clearly and has not come away from the flange",
    "bores_clear": "An insert drops down every bore without catching, and the iron's tip goes down it",
    "shoulder_stops": "The iron's shoulder stops on the plate and the tip goes no further",
}


def nest_checks(*, lip: bool, strap: bool, label: bool) -> list[str]:
    """The checks a trial asks of a nest: the lip, the strap slots and the label only when it
    has them."""

    checks = ["printed_cleanly", "part_seats", "part_lifts_out"]

    if lip:
        checks.append("part_stays_in")

    if strap:
        checks.append("strap_holds_still")

    if label:
        checks.append("label_legible")

    return checks


def jig_checks() -> list[str]:
    """The checks a trial asks of an insert jig."""

    return [
        "printed_cleanly",
        "part_seats",
        "part_lifts_out",
        "bores_clear",
        "shoulder_stops",
    ]


def check_guidance(name: str) -> str:
    """What to do and look for in one check."""

    return _GUIDANCE[name]


def _next_trial(build_record_path: Path) -> tuple[dict[str, Any], Path]:
    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)

    return build, trial


def _write_templates(
    build: dict[str, Any], trial: Path, readings_name: str, readings: dict[str, Any]
) -> None:
    observations = {
        check: {"result": "pending", "guidance": check_guidance(check), "notes": ""}
        for check in build["checks"]
    }
    measurements = {
        name: {"nominal_mm": nominal, "value_mm": None, "notes": ""}
        for name, nominal in build["nominal_measurements_mm"].items()
    }

    for name, content in (
        (OBSERVATIONS, observations),
        (MEASUREMENTS, measurements),
        (readings_name, readings),
    ):
        (trial / name).write_text(
            json.dumps(content, indent=2) + "\n", encoding="utf-8"
        )


def start_nest_trial(build_record_path: Path) -> Path:
    """Write the next nest trial's observation, measurement and use templates."""

    build, trial = _next_trial(build_record_path)
    use = {
        "not_a_limit": NO_LIMIT,
        "guidance": (
            "uses_counted: how many times the part was put in and taken out; anything_wore: "
            "whether the nest, its lip or its slots wore, cracked or went loose in that time"
        ),
        "uses_counted": None,
        "anything_wore": None,
        "notes": "",
    }
    _write_templates(build, trial, USE, use)

    return trial


def start_jig_trial(build_record_path: Path) -> Path:
    """Write the next jig trial's observation, measurement and insertion templates."""

    build, trial = _next_trial(build_record_path)
    insertion = {
        "not_a_limit": NO_LIMIT,
        "designed": {"depth_below_face_mm": build["settings"]["depth_below_face_mm"]},
        "guidance": (
            "For each insert: went_in_square, whether it went in square to the face; "
            "depth_below_face_mm, how far below the part's face its top ended, measured (negative "
            "if it stands proud); offset_from_pocket_centre_mm, how far its centre is from the "
            "pocket's centre, measured. Leave a reading blank when it was not taken."
        ),
        "inserts": {
            bore["id"]: {
                "went_in_square": None,
                "depth_below_face_mm": None,
                "offset_from_pocket_centre_mm": None,
                "notes": "",
            }
            for bore in build["bores"]
        },
    }
    _write_templates(build, trial, INSERTION, insertion)

    return trial


def _use_readings(trial: Path) -> dict[str, Any] | None:
    """The trial's use readings, validated; ``None`` when none was taken."""

    path = trial / USE
    entry = _read(path) if path.is_file() else {}
    count, wore = entry.get("uses_counted"), entry.get("anything_wore")

    if count is None:
        if wore is not None:
            raise ValueError(f"{USE}: anything_wore needs uses_counted")

        return None

    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"{USE}: uses_counted must be a whole number from 1")

    if not isinstance(wore, bool):
        raise TypeError(f"{USE}: anything_wore must be true or false")

    return {
        "uses_counted": count,
        "anything_wore": wore,
        "notes": entry.get("notes", ""),
        "not_a_limit": NO_LIMIT,
    }


def _reading(
    entry: dict[str, Any], name: str, where: str, *, from_zero: bool
) -> float | None:
    value = entry.get(name)

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where}: {name} must be a number, not {value!r}")

    if not math.isfinite(value) or (from_zero and value < 0):
        raise ValueError(
            f"{where}: {name} must be a number"
            + (" from zero" if from_zero else "")
            + f", not {value!r}"
        )

    return float(value)


def _insertion_readings(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's insertion readings per insert, validated and set beside the designed depth;
    ``None`` when none was taken."""

    path = trial / INSERTION
    payload = _read(path) if path.is_file() else {}
    inserts = payload.get("inserts") or {}
    known = {bore["id"] for bore in build["bores"]}
    unknown = sorted(set(inserts) - known)

    if unknown:
        raise ValueError(
            f"{INSERTION}: readings for {unknown}, but the jig's inserts are {sorted(known)}"
        )

    designed = build["settings"]["depth_below_face_mm"]
    readings: dict[str, Any] = {}

    for name in sorted(inserts):
        entry = inserts[name]
        where = f"{INSERTION} insert {name}"
        square = entry.get("went_in_square")

        if square is not None and not isinstance(square, bool):
            raise TypeError(f"{where}: went_in_square must be true or false")

        depth = _reading(entry, "depth_below_face_mm", where, from_zero=False)
        offset = _reading(entry, "offset_from_pocket_centre_mm", where, from_zero=True)

        if square is None and depth is None and offset is None:
            continue

        readings[name] = {
            "went_in_square": square,
            "depth_below_face_mm": depth,
            "designed_depth_below_face_mm": designed,
            "depth_error_mm": None if depth is None else round(depth - designed, 3),
            "offset_from_pocket_centre_mm": offset,
            "notes": entry.get("notes", ""),
        }

    if not readings:
        return None

    return {"inserts": readings, "not_a_limit": NO_LIMIT}


def _complete(
    trial: Path,
    *,
    build_name: str,
    record_name: str,
    schema_version: str,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str,
    readings_key: str,
    read_readings: Any,
) -> Path:
    record_path = trial / record_name

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as the next trial"
        )

    build_path = trial.parent.parent / build_name
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
    readings = read_readings(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]

    if (
        disposition is not EnclosureTrialDisposition.FAIL
        and not measurements
        and readings is None
    ):
        raise ValueError(
            f"A {disposition.value} trial needs at least one measurement or reading"
        )

    if disposition is EnclosureTrialDisposition.PASS and failed:
        raise ValueError(f"A passing trial cannot have failed checks: {failed}")

    record = {
        "schema_version": schema_version,
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": hashlib.sha256(build_path.read_bytes()).hexdigest(),
        "part_sha256": build["part"]["sha256"],
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
        readings_key: readings,
        "notes": notes,
        "not_claimed": build.get("not_claimed", ""),
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path


def complete_nest_trial(
    trial: Path,
    *,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str = "",
) -> Path:
    """Validate a filled-in nest trial and write its record."""

    return _complete(
        trial,
        build_name=NEST_BUILD_RECORD,
        record_name=NEST_TRIAL_RECORD,
        schema_version=NEST_TRIAL_SCHEMA_VERSION,
        disposition=disposition,
        material_profile_id=material_profile_id,
        notes=notes,
        readings_key="use",
        read_readings=lambda path, _build: _use_readings(path),
    )


def complete_jig_trial(
    trial: Path,
    *,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str = "",
) -> Path:
    """Validate a filled-in jig trial and write its record."""

    return _complete(
        trial,
        build_name=JIG_BUILD_RECORD,
        record_name=JIG_TRIAL_RECORD,
        schema_version=JIG_TRIAL_SCHEMA_VERSION,
        disposition=disposition,
        material_profile_id=material_profile_id,
        notes=notes,
        readings_key="insertion",
        read_readings=_insertion_readings,
    )
