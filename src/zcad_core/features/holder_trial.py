"""Trials for object holders: what was printed, how it hung, and how it held the real object.

``holder build`` writes a build record (``holder.json``): the holder file and the object by hash,
the settings, each printed part's STL hash, the checks a trial asks and the sizes it measures. A
trial records one print of exactly those parts, as the holding nest's do:

1. :func:`start_holder_trial` writes ``trials/trial-NNN/`` with ``observations.json`` and
   ``measurements.json`` listing the checks and sizes that apply, and ``use.json`` for how it was
   used: what it was fixed to, for how long, how often the object went in and out, whether it
   stayed put when knocked, and whether anything crept or cracked.
2. Fill them in after printing it, hanging it and using it with the real object.
3. :func:`complete_holder_trial` validates them and writes ``holder-trial.json``. A completed trial
   is never overwritten.

:func:`holder_verification` says whether a build is verified: two passing trials of that exact
build record. A rebuilt holder has a new record and starts with none.

The engine states no limit for any reading, and nothing about the load a holder bears. The
object's mass from its capture is set beside the readings, so a trial says what the holder carried.
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

HOLDER_TRIAL_SCHEMA_VERSION = "1.0.0"
HOLDER_BUILD_RECORD = "holder.json"
HOLDER_TRIAL_RECORD = "holder-trial.json"
USE = "use.json"
MINIMUM_TRIALS_TO_VERIFY = 2

NO_LIMIT = (
    "The engine states no limit for any reading here, and no figure to compare one with: it "
    "records what was measured and what was seen, and says nothing about the load a holder "
    "bears or what its mount holds in."
)
_GUIDANCE = {
    "printed_cleanly": (
        "The print came off without warping, stringing into the pocket, or a failed wall; the "
        "teardrop holes and any peg or hook printed without drooping"
    ),
    "object_goes_in": "The object drops into the pocket by hand and stands on the floor",
    "object_lifts_out": "The object lifts straight out by hand, with the finger notch if it has one",
    "object_sits_square": "The object stands square in the pocket and does not rattle or lean",
    "features_reachable": (
        "Every port, button or loop the holder left open can be reached and used with the "
        "object in it"
    ),
    "tabs_hold": (
        "The tabs spring over the object's top as it goes in, hold it when the holder is "
        "tilted and knocked, and give as it is lifted out"
    ),
    "screws_seat_flush": "Each screw's head sinks flush in its countersink, below the object",
    "keyholes_hang": "The holder drops onto the wall screws, slides down its slots, and hangs still",
    "pegs_hang": "The pegs go into the board's holes, turn up behind it, and the holder hangs still",
    "pad_holds": "The pad or tape holds the plate flat to the wall",
}
_MOUNT_CHECKS = {
    "screws": "screws_seat_flush",
    "keyhole": "keyholes_hang",
    "pegboard": "pegs_hang",
    "flat": "pad_holds",
}


def holder_checks(*, mount: str, openings: bool, tabs: bool) -> list[str]:
    """The checks a trial asks of a holder: its mount's own, and the features and tabs only when
    it has them."""

    checks = [
        "printed_cleanly",
        "object_goes_in",
        "object_lifts_out",
        "object_sits_square",
    ]

    if openings:
        checks.append("features_reachable")

    if tabs:
        checks.append("tabs_hold")

    checks.append(_MOUNT_CHECKS[mount])

    return checks


def check_guidance(name: str) -> str:
    """What to do and look for in one check."""

    return _GUIDANCE[name]


def start_holder_trial(build_record_path: Path) -> Path:
    """Write the next holder trial's observation, measurement and use templates."""

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
    use = {
        "not_a_limit": NO_LIMIT,
        "carried": {
            "mass_g": build["object"].get("mass_g"),
            "source": build["object"].get("mass_source"),
        },
        "guidance": (
            "mounted_on: what the holder was fixed to and how, e.g. 'plasterboard, two plugs'; "
            "days_in_use: how long it hung with the object in it; uses_counted: how many times "
            "the object was taken out and put back; stayed_put_when_knocked: whether the object "
            "stayed in when the holder was knocked; anything_crept_or_cracked: whether the "
            "holder, its mount or its tabs crept, sagged, cracked or went loose in that time. "
            "Leave a reading blank when it was not taken."
        ),
        "mounted_on": None,
        "days_in_use": None,
        "uses_counted": None,
        "stayed_put_when_knocked": None,
        "anything_crept_or_cracked": None,
        "notes": "",
    }

    for name, content in (
        (OBSERVATIONS, observations),
        (MEASUREMENTS, measurements),
        (USE, use),
    ):
        (trial / name).write_text(
            json.dumps(content, indent=2) + "\n", encoding="utf-8"
        )

    return trial


def _flag(entry: dict[str, Any], name: str) -> bool | None:
    value = entry.get(name)

    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{USE}: {name} must be true or false")

    return value


def _count(entry: dict[str, Any], name: str, *, least: float) -> float | None:
    value = entry.get(name)

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{USE}: {name} must be a number, not {value!r}")

    if not math.isfinite(value) or value < least:
        raise ValueError(f"{USE}: {name} must be at least {least:g}, not {value!r}")

    return float(value)


def use_readings(trial: Path, build: dict[str, Any]) -> dict[str, Any] | None:
    """The trial's use readings, validated; ``None`` when none was taken."""

    path = trial / USE
    entry = _read(path) if path.is_file() else {}
    mounted = entry.get("mounted_on")

    if mounted is not None and (not isinstance(mounted, str) or not mounted.strip()):
        raise ValueError(f"{USE}: mounted_on must say what the holder was fixed to")

    uses = entry.get("uses_counted")

    if uses is not None and (
        isinstance(uses, bool) or not isinstance(uses, int) or uses < 1
    ):
        raise ValueError(f"{USE}: uses_counted must be a whole number from 1")

    readings = {
        "mounted_on": mounted.strip() if isinstance(mounted, str) else None,
        "days_in_use": _count(entry, "days_in_use", least=0.0),
        "uses_counted": uses,
        "stayed_put_when_knocked": _flag(entry, "stayed_put_when_knocked"),
        "anything_crept_or_cracked": _flag(entry, "anything_crept_or_cracked"),
    }

    if all(value is None for value in readings.values()):
        return None

    return {
        **readings,
        "carried_mass_g": build["object"].get("mass_g"),
        "notes": entry.get("notes", ""),
        "not_a_limit": NO_LIMIT,
    }


def complete_holder_trial(
    trial: Path,
    *,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str = "",
) -> Path:
    """Validate a filled-in holder trial and write its record."""

    record_path = trial / HOLDER_TRIAL_RECORD

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as the next trial"
        )

    build_path = trial.parent.parent / HOLDER_BUILD_RECORD
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
    readings = use_readings(trial, build)
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
        "schema_version": HOLDER_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": hashlib.sha256(build_path.read_bytes()).hexdigest(),
        "object_sha256": build["object"]["sha256"],
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
        "use": readings,
        "notes": notes,
        "not_claimed": build.get("not_claimed", ""),
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path


def holder_verification(build_record_path: Path) -> dict[str, Any]:
    """Whether a build is verified: at least two passing trials of this exact build record."""

    digest = sha256(build_record_path)
    found = []

    for path in sorted(
        build_record_path.parent.glob("trials/*/" + HOLDER_TRIAL_RECORD)
    ):
        record = _read(path)
        found.append(
            {
                "trial_id": record["trial_id"],
                "disposition": record["disposition"],
                "of_this_build": record["build_record_sha256"] == digest,
            }
        )

    passing = [t for t in found if t["disposition"] == "pass" and t["of_this_build"]]

    return {
        "build_record": str(build_record_path),
        "verified": len(passing) >= MINIMUM_TRIALS_TO_VERIFY,
        "passing_trials": len(passing),
        "needed": MINIMUM_TRIALS_TO_VERIFY,
        "trials": found,
    }
