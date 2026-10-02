"""Print records for wearable housings: what was built, and how it wore.

``housing build`` writes a ``housing-build.json`` build record beside the exported
parts: the style, the housing file and the file it houses by hash, the figures of each
way of wearing and where they came from, the skin side, each part's STL hash, and the
dimensions a trial measures. A trial then records one print of exactly those parts, in
the style of :mod:`zcad_core.features.enclosure_trial`:

1. :func:`start_housing_trial` writes ``trials/trial-NNN/`` with ``observations.json``
   and ``measurements.json`` listing only the checks and dimensions that apply to this
   housing, and ``wear.json`` for the readings of wearing it.
2. Fill them in after printing, fitting and wearing.
3. :func:`complete_housing_trial` validates them and writes ``housing-trial.json``. A
   completed trial is never overwritten.

``wear.json`` holds four kinds of reading: the **force** it took to pull the housed
thing out (a spring scale), a **pull test** of each lug, ear, tab or clip (the load
reached and what gave), a **count of wears** with whether anything wore or cracked, and
whether **skin was irritated**. The last is a person's observation: the record keeps
the answer and the notes, and the engine draws no conclusion from it. The engine states
no limit for any reading, and no figure to compare one with.
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
    _positive,
    _read,
    sha256,
)
from zcad_core.features.housing import Housing

HOUSING_BUILD_SCHEMA_VERSION = "1.0.0"
HOUSING_TRIAL_SCHEMA_VERSION = "1.0.0"
BUILD_RECORD = "housing-build.json"
TRIAL_RECORD = "housing-trial.json"
WEAR = "wear.json"

# The ways whose attachment a pull test loads. An adhesive plate holds by the patch,
# which is not the housing's.
PULLED = ("strap", "band", "lanyard", "clip")

NO_LIMIT = (
    "The engine states no limit for any reading here, and no figure to compare one "
    "with: it records what was measured and what was seen."
)
_CHECK_GUIDANCE = {
    "parts_printed_cleanly": (
        "Every part printed without warping, stringing into an opening, or a failed "
        "feature"
    ),
    "skin_side_clean": (
        "The skin face and its rounded edge printed without stringing, burrs or a "
        "ridge at the first layer; the radius is a setting, not a result"
    ),
    "device_seats": (
        "The device presses into the pocket, sits level on the floor and is held "
        "without rocking, with every feature the file lists left open"
    ),
    "board_seats": (
        "The board sits level on its standoffs and no part meets the base or the lid"
    ),
    "lid_closes": "The lid snaps onto the base and stays shut when the case is shaken",
    "nothing_rattles": "Nothing moves or rattles when the housing is shaken",
    "strap_fits": (
        "The spring bar goes into both lug holes and the strap sits on it without "
        "binding"
    ),
    "band_fits": "The band threads through the slot in each ear and lies flat",
    "clip_fits": (
        "The belt goes in under the arm without forcing it, and the nub grips it"
    ),
    "adhesive_fits": "The patch lies inside the flange and the housing sits square on it",
    "lanyard_fits": "The cord passes through the tab's hole and the knot clears the body",
}
_RETENTION_GUIDANCE = {
    "cradle": (
        "Pull the device straight out of the pocket by hand-held spring scale on the "
        "device's face, and write the highest force read before it came free"
    ),
    "case": (
        "Lift the lid's edge with a spring scale and write the highest force read "
        "before it came off"
    ),
}
_PULL_GUIDANCE = {
    "strap": "Load a spring bar through its lug holes by spring scale until it gives",
    "band": "Load a band through its ear's slot by spring scale until it gives",
    "lanyard": "Load the cord through its tab by spring scale until it gives",
    "clip": (
        "Hang the housing on a belt of the thickness named and pull it off by "
        "spring scale, writing the highest force read"
    ),
}


def housing_checks(housing: Housing) -> list[str]:
    """The checks a trial asks of this housing, in order."""

    spec = housing.spec
    checks = ["parts_printed_cleanly", "skin_side_clean"]
    checks.append("device_seats" if spec.style == "cradle" else "board_seats")

    if spec.style == "case":
        checks.append("lid_closes")

    checks += [f"{wear.kind}_fits" for wear in spec.wear]

    return [*checks, "nothing_rattles"]


def check_guidance(name: str) -> str:
    """What to do and look for in one check."""

    return _CHECK_GUIDANCE[name]


def nominal_measurements(housing: Housing) -> dict[str, float]:
    """The designed dimensions a trial measures with calipers, in mm."""

    length, width, height = housing.summary["outer_size_mm"]
    nominals = {
        "outer_length_mm": length,
        "outer_width_mm": width,
        "outer_height_mm": height,
        "wall_thickness_mm": housing.spec.wall_mm,
        "floor_thickness_mm": housing.spec.floor_mm,
    }

    if housing.spec.style == "case":
        nominals["lid_thickness_mm"] = housing.spec.lid_mm

    return {name: round(float(value), 3) for name, value in nominals.items()}


def write_housing_record(
    output_directory: Path,
    *,
    housing: Housing,
    design_name: str,
    printer_profile_id: str,
    part_stls: dict[str, Path],
) -> Path:
    """Write ``housing-build.json``; refuses to replace one."""

    path = output_directory / BUILD_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    spec = housing.spec
    record = {
        "schema_version": HOUSING_BUILD_SCHEMA_VERSION,
        "design_name": design_name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "style": spec.style,
        "housing_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "houses": {"path": str(spec.input_path), "sha256": spec.input_sha256},
        "settings": {
            "wall_mm": spec.wall_mm,
            "floor_mm": spec.floor_mm,
            "lid_mm": spec.lid_mm,
            "clearance_mm": spec.clearance_mm,
            "corner_radius_mm": spec.corner_radius_mm,
            "skin_edge_radius_mm": spec.skin_edge_radius_mm,
        },
        "wear": [
            {"kind": w.kind, "figures": dict(w.figures), "source": w.source}
            for w in spec.wear
        ],
        "summary": housing.summary,
        "skin_side": housing.summary.get("skin_side"),
        "device_mass_g": housing.summary.get("device_mass_g"),
        "device_mass_source": housing.summary.get("device_mass_source", ""),
        "printer_profile_id": printer_profile_id,
        "parts": {
            name: {"stl_path": str(stl), "stl_sha256": sha256(stl)}
            for name, stl in part_stls.items()
        },
        "fit_checks": housing.checks,
        "checks": housing_checks(housing),
        "nominal_measurements_mm": nominal_measurements(housing),
        "not_claimed": list(housing.notes),
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")

    return path


def _wear_template(build: dict[str, Any]) -> dict[str, Any]:
    """The wear readings: what the build made, and blanks for a spring scale, a count
    and a person's answer. Leave a reading blank when it was not taken."""

    template: dict[str, Any] = {
        "not_a_limit": NO_LIMIT,
        "retention": {
            "guidance": _RETENTION_GUIDANCE[build["style"]],
            "device_mass_g": build.get("device_mass_g"),
            "retention_force_n": None,
            "notes": "",
        },
        "pull_tests": {
            way["kind"]: {
                "guidance": _PULL_GUIDANCE[way["kind"]],
                "figures": way["figures"],
                "pull_n": None,
                "what_gave": None,
                "notes": "",
            }
            for way in build["wear"]
            if way["kind"] in PULLED
        },
        "wearing": {
            "guidance": (
                "Count the times it was worn, and say whether anything wore or "
                "cracked. Say whether skin was irritated: a person's observation, "
                "kept as written; the engine draws no conclusion from it"
            ),
            "wears_counted": None,
            "anything_wore_or_cracked": None,
            "skin_irritated": None,
            "notes": "",
        },
    }

    return template


def start_housing_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation, measurement and wear templates."""

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
    (trial / WEAR).write_text(
        json.dumps(_wear_template(build), indent=2) + "\n", encoding="utf-8"
    )

    return trial


def _flag(entry: dict[str, Any], name: str, where: str) -> bool | None:
    value = entry.get(name)

    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{where}: {name} must be true or false")

    return value


def _count(entry: dict[str, Any], where: str) -> int | None:
    count = entry.get("wears_counted")

    if count is None:
        return None

    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"{where}: wears_counted must be a whole number from 1")

    return count


def _wearing(entry: dict[str, Any]) -> dict[str, Any] | None:
    """The count of wears, whether anything wore or cracked, and whether skin was
    irritated. Both answers need a count: a housing is only as worn, or as irritating,
    as the number of times it was worn."""

    where = "wear.json wearing"
    count = _count(entry, where)
    wore = _flag(entry, "anything_wore_or_cracked", where)
    irritated = _flag(entry, "skin_irritated", where)

    if count is None:
        if wore is not None or irritated is not None:
            raise ValueError(
                f"{where}: anything_wore_or_cracked and skin_irritated need "
                "wears_counted"
            )

        return None

    if wore is None:
        raise ValueError(f"{where}: anything_wore_or_cracked must be true or false")

    return {
        "wears_counted": count,
        "anything_wore_or_cracked": wore,
        "skin_irritated": irritated,
        "notes": entry.get("notes", ""),
    }


def _pull_tests(entries: dict[str, Any], build: dict[str, Any]) -> list[dict[str, Any]]:
    tests = []
    built = {w["kind"] for w in build["wear"] if w["kind"] in PULLED}
    unknown = sorted(set(entries) - built)

    if unknown:
        raise ValueError(f"wear.json pull_tests: not built in this housing: {unknown}")

    for kind, entry in entries.items():
        where = f"wear.json pull_tests.{kind}"
        pull = _positive(entry, "pull_n", where)

        if pull is None:
            continue

        gave = entry.get("what_gave")

        if not isinstance(gave, str) or not gave.strip():
            raise ValueError(
                f"{where}: what_gave must say what gave, or that nothing did"
            )

        tests.append(
            {
                "kind": kind,
                "pull_n": pull,
                "what_gave": gave,
                "figures": next(
                    w["figures"] for w in build["wear"] if w["kind"] == kind
                ),
                "notes": entry.get("notes", ""),
            }
        )

    return tests


def _wear_readings(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's wear readings, validated; ``None`` when none was taken."""

    path = trial / WEAR
    entry = _read(path) if path.is_file() else {}
    retention = entry.get("retention", {})
    force = _positive(retention, "retention_force_n", "wear.json retention")
    pulls = _pull_tests(entry.get("pull_tests", {}), build)
    wearing = _wearing(entry.get("wearing", {}))

    if force is None and not pulls and wearing is None:
        return None

    return {
        "retention_force_n": force,
        "device_mass_g": build.get("device_mass_g"),
        "retention_notes": retention.get("notes", ""),
        "pull_tests": pulls,
        "wearing": wearing,
        "not_a_limit": NO_LIMIT,
    }


def complete_housing_trial(
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
    wear = _wear_readings(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]

    if (
        disposition is not EnclosureTrialDisposition.FAIL
        and not measurements
        and wear is None
    ):
        raise ValueError(
            f"A {disposition.value} trial needs at least one measurement or wear "
            "reading"
        )

    if disposition is EnclosureTrialDisposition.PASS and failed:
        raise ValueError(f"A passing trial cannot have failed checks: {failed}")

    record = {
        "schema_version": HOUSING_TRIAL_SCHEMA_VERSION,
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
        "wear": wear,
        "notes": notes,
        "not_claimed": build.get("not_claimed", []),
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path
