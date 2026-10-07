"""Trials for Gridfinity parts: a printed bin or baseplate, and how it fitted what it mates with.

``gridfinity bin``, ``baseplate`` and ``fitted`` write a build record (``gridfinity.json``): the
settings, the figures and their sources, each printed part's STL hash, the checks a trial asks and
the sizes it measures. A trial records one print of exactly those parts, as the holders' do:

1. :func:`start_gridfinity_trial` writes ``trials/trial-NNN/`` with ``observations.json`` and
   ``measurements.json``, and ``fit.json`` for what the part was fitted with and how it felt.
2. Fill them in after printing the part and fitting it.
3. :func:`complete_gridfinity_trial` validates them and writes ``gridfinity-trial.json``. A
   completed trial is never overwritten.

A trial names what the part mated with: a baseplate for a bin, a bin for a baseplate, made by this
engine or by another generator, which it names. :func:`gridfinity_verification` says a build is
verified on two passing trials of its exact build record, and counts apart those that passed with a
part from another generator, since those are what say the part keeps to the standard in practice.

The engine states no pass mark for how a fit feels, and nothing about load.
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

GRIDFINITY_TRIAL_SCHEMA_VERSION = "1.0.0"
GRIDFINITY_BUILD_RECORD = "gridfinity.json"
GRIDFINITY_TRIAL_RECORD = "gridfinity-trial.json"
FIT = "fit.json"
MINIMUM_TRIALS_TO_VERIFY = 2
MADE_BY = ("this engine", "another generator")
FEELS = ("loose", "right", "tight")

NO_LIMIT = (
    "The engine states no pass mark for how a fit feels and no figure to compare a reading "
    "with: it records what was measured and what was seen, and says nothing about load."
)
_GUIDANCE = {
    "printed_cleanly": (
        "The print came off without warping, elephant's foot on the base, or stringing; the "
        "base's chamfers and the lip are clean"
    ),
    "seats_flat": "The bin drops into its cell and sits flat, without rocking or riding high",
    "lifts_out": "The bin lifts out of its cell by hand without catching",
    "stacks": "A bin set on this one's lip seats in it and stays put when nudged",
    "compartments_clean": "Every divider and label tab printed whole, with nothing sagging",
    "object_fits": "The object drops into its pocket and lifts out by its notches",
    "magnets_seat": "Magnets press into their holes and stay, flush or below the face",
    "screws_fit": "M3 screws go through their holes and seat",
    "holds_a_bin": "A bin drops into every cell tried and sits flat",
    "pieces_lie_flat": "The pieces lie side by side, flat and level across their joins",
}


def gridfinity_checks(kind: str, settings: dict[str, Any]) -> list[str]:
    """The checks a trial asks of a part: what it is, and its options."""

    if kind == "baseplate":
        checks = ["printed_cleanly", "holds_a_bin"]

        if settings.get("pieces"):
            checks.append("pieces_lie_flat")
    else:
        checks = ["printed_cleanly", "seats_flat", "lifts_out"]

        if settings.get("lip"):
            checks.append("stacks")

        if list(settings.get("divisions", [1, 1])) != [1, 1] or settings.get(
            "label_tabs"
        ):
            checks.append("compartments_clean")

        if settings.get("fitted"):
            checks.append("object_fits")

    if settings.get("magnets"):
        checks.append("magnets_seat")

    if settings.get("screws"):
        checks.append("screws_fit")

    return checks


def check_guidance(name: str) -> str:
    return _GUIDANCE[name]


def start_gridfinity_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation, measurement and fit templates."""

    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)
    mate = "baseplate" if build["kind"] == "bin" else "bin"
    observations = {
        check: {"result": "pending", "guidance": check_guidance(check), "notes": ""}
        for check in build["checks"]
    }
    measurements = {
        name: {"nominal_mm": nominal, "value_mm": None, "notes": ""}
        for name, nominal in build["nominal_measurements_mm"].items()
    }
    fit = {
        "not_a_limit": NO_LIMIT,
        "guidance": (
            f"mated_with: the {mate} it was fitted with, made_by one of {list(MADE_BY)}, and "
            "for another generator its name and where it came from (a link or a file); "
            f"feel: one of {list(FEELS)}; seats_flat, lifts_out, stacks, magnets_hold: true or "
            "false, blank when not tried."
        ),
        "mated_with": {"kind": mate, "made_by": None, "name": ""},
        "feel": None,
        "seats_flat": None,
        "lifts_out": None,
        "stacks": None,
        "magnets_hold": None,
        "notes": "",
    }

    for name, content in (
        (OBSERVATIONS, observations),
        (MEASUREMENTS, measurements),
        (FIT, fit),
    ):
        (trial / name).write_text(
            json.dumps(content, indent=2) + "\n", encoding="utf-8"
        )

    return trial


def fit_readings(trial: Path) -> dict[str, Any] | None:
    """The trial's fit readings, validated; ``None`` when nothing was fitted."""

    path = trial / FIT
    entry = _read(path) if path.is_file() else {}
    mate = entry.get("mated_with") or {}
    made_by = mate.get("made_by")

    if made_by is None:
        return None

    if made_by not in MADE_BY:
        raise ValueError(f"{FIT}: mated_with.made_by must be one of {list(MADE_BY)}")

    name = mate.get("name", "")

    if made_by == "another generator" and (
        not isinstance(name, str) or not name.strip()
    ):
        raise ValueError(
            f"{FIT}: a part from another generator needs its name and where it came from"
        )

    feel = entry.get("feel")

    if feel not in (*FEELS, None):
        raise ValueError(f"{FIT}: feel must be one of {list(FEELS)}, not {feel!r}")

    flags = {}

    for flag in ("seats_flat", "lifts_out", "stacks", "magnets_hold"):
        value = entry.get(flag)

        if value is not None and not isinstance(value, bool):
            raise TypeError(f"{FIT}: {flag} must be true or false")

        flags[flag] = value

    return {
        "mated_with": {
            "kind": mate.get("kind"),
            "made_by": made_by,
            "name": name.strip() if isinstance(name, str) else "",
        },
        "feel": feel,
        **flags,
        "notes": entry.get("notes", ""),
        "not_a_limit": NO_LIMIT,
    }


def complete_gridfinity_trial(
    trial: Path,
    *,
    disposition: EnclosureTrialDisposition,
    material_profile_id: str,
    notes: str = "",
) -> Path:
    """Validate a filled-in trial and write its record."""

    record_path = trial / GRIDFINITY_TRIAL_RECORD

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as the next trial"
        )

    build_path = trial.parent.parent / GRIDFINITY_BUILD_RECORD
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
    fit = fit_readings(trial)
    failed = [entry["check"] for entry in observations if not entry["passed"]]

    if disposition is EnclosureTrialDisposition.PASS and fit is None:
        raise ValueError(
            f"A passing trial names what the part was fitted with, in {FIT}: a fit is the "
            "whole of a Gridfinity part's job"
        )

    if disposition is EnclosureTrialDisposition.PASS and failed:
        raise ValueError(f"A passing trial cannot have failed checks: {failed}")

    record = {
        "schema_version": GRIDFINITY_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build.get("design_name", ""),
        "kind": build["kind"],
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
        "fit": fit,
        "notes": notes,
        "not_claimed": build.get("not_claimed", ""),
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path


def gridfinity_verification(build_record_path: Path) -> dict[str, Any]:
    """Whether a build is verified (two passing trials of this build record), and how many of
    those passed with a part from another generator."""

    digest = sha256(build_record_path)
    found = []

    for path in sorted(
        build_record_path.parent.glob("trials/*/" + GRIDFINITY_TRIAL_RECORD)
    ):
        record = _read(path)
        fit = record.get("fit") or {}
        found.append(
            {
                "trial_id": record["trial_id"],
                "disposition": record["disposition"],
                "of_this_build": record["build_record_sha256"] == digest,
                "mated_with": fit.get("mated_with"),
                "feel": fit.get("feel"),
            }
        )

    passing = [t for t in found if t["disposition"] == "pass" and t["of_this_build"]]
    elsewhere = [
        t
        for t in passing
        if (t["mated_with"] or {}).get("made_by") == "another generator"
    ]

    return {
        "build_record": str(build_record_path),
        "verified": len(passing) >= MINIMUM_TRIALS_TO_VERIFY,
        "passing_trials": len(passing),
        "needed": MINIMUM_TRIALS_TO_VERIFY,
        "passing_with_another_generator": len(elsewhere),
        "trials": found,
    }
