"""Print records for drill guides: what was built, and how the print drilled.

``guide build`` writes a ``guide.json`` build record beside the exported part:
the guide file and the part by hash, each bore as placed, and the printed
part's STL hash. A trial then records one print of exactly that part, drilled
into the real thing:

1. :func:`start_guide_trial` writes ``trials/trial-NNN/`` with an
   ``observations.json`` and a ``measurements.json`` template listing only the
   checks and bores that apply to this guide.
2. Print the guide, fit it to the part, drill scrap or the part, and fill both
   in.
3. :func:`complete_guide_trial` validates them and writes ``guide-trial.json``,
   with each bore's offset from where it was meant to be. A completed trial is
   never overwritten; record another print as the next trial.

A guide that has passed two trials of the same build record is verified
(:func:`guide_verification`). The offsets of passing trials are pooled into a
measured positional error by :mod:`zcad_core.profiles.guide_accuracy`. The
engine states no accuracy of its own: these trials are the only source of one.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

GUIDE_TRIAL_SCHEMA_VERSION = "1.0.0"
BUILD_RECORD = "guide.json"
TRIAL_RECORD = "guide-trial.json"
OBSERVATIONS = "observations.json"
MEASUREMENTS = "measurements.json"
# A guide is verified by this many passing trials of the same build.
MINIMUM_TRIALS_TO_VERIFY = 2


class GuideTrialDisposition(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class GuideCheckName(str, Enum):
    SEATS = "guide_seats_on_part"
    RELEASES = "part_releases"
    DRILL_PASSES = "drill_passes_bores"
    BUSHINGS = "bushings_seated"
    DEPTH = "holes_reach_depth"


CHECK_GUIDANCE = {
    GuideCheckName.SEATS: (
        "Set the guide on the part. It should seat without rocking: the plate "
        "on the part's top face, or the nest's rim on the part's shoulder for a "
        "ledge nest, with no gap round the part you could not explain by the "
        "clearance."
    ),
    GuideCheckName.RELEASES: (
        "Lift the guide straight off the part. It should come away without "
        "catching or needing to be flexed."
    ),
    GuideCheckName.DRILL_PASSES: (
        "Put the drill through every bore with the guide seated. It should pass "
        "without binding and without more play than you can see."
    ),
    GuideCheckName.BUSHINGS: (
        "Press each steel bushing into its pocket. It should seat by hand or a "
        "light press and stay put when the guide is turned over."
    ),
    GuideCheckName.DEPTH: (
        "Drill each hole to its depth with the chuck seated on the plate (or "
        "its flange). The bit should reach the depth without the chuck meeting "
        "the guide first."
    ),
}
FRAME_NOTE = (
    "Positions are in the part's own frame: from the centre of its bounding "
    "box, +X to the right and +Y up the page seen from above. Measure a drilled "
    "hole's centre from the part's left and bottom edges, then x = left - "
    "width / 2 and y = bottom - length / 2, with the part's size below."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def applicable_checks(build: dict[str, Any]) -> tuple[GuideCheckName, ...]:
    """The checks that apply to this guide: all four of a guide with bores, one
    more if any is a bushing bore, and only the first two of one with none."""

    bores = build.get("bores") or []
    checks = [GuideCheckName.SEATS, GuideCheckName.RELEASES]

    if bores:
        checks.append(GuideCheckName.DRILL_PASSES)

    if any(bore.get("kind") == "bushing" for bore in bores):
        checks.append(GuideCheckName.BUSHINGS)

    if bores:
        checks.append(GuideCheckName.DEPTH)

    return tuple(checks)


def start_guide_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation and measurement templates."""

    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)
    observations = {
        check.value: {
            "result": "pending",
            "guidance": CHECK_GUIDANCE[check],
            "notes": "",
        }
        for check in applicable_checks(build)
    }
    bores: dict[str, Any] = {}

    for bore in build.get("bores") or []:
        entry: dict[str, Any] = {
            "kind": bore["kind"],
            "nominal_x_mm": bore["entry_mm"][0],
            "nominal_y_mm": bore["entry_mm"][1],
            "measured_x_mm": None,
            "measured_y_mm": None,
            "predicted_play_mm": bore.get("worst_case_entry_play_mm"),
            "notes": "",
        }

        if bore["kind"] == "printed":
            entry["modelled_bore_mm"] = bore["hole_diameter_mm"]
            entry["measured_bore_mm"] = None
        else:
            entry["modelled_seat_mm"] = bore["pocket_diameter_mm"]
            entry["measured_seat_mm"] = None

        bores[bore["identifier"]] = entry

    measurements = {
        "frame": FRAME_NOTE,
        "part_size_mm": build["part"]["size_mm"],
        "gauge": (
            "measured_bore_mm and measured_seat_mm are the printed hole's diameter "
            "as a pin gauge finds it: the largest that enters. They are optional."
        ),
        "position_tolerance_mm": None,
        "tolerance": (
            "position_tolerance_mm: how far a drilled hole may land from where it "
            "was meant to be and still be a pass for your use, in mm. A passing "
            "trial needs it, and every bore within it. predicted_play_mm is the "
            "build's bound from the clearances alone, not an accuracy: printing "
            "adds to it."
        ),
        "bores": bores,
    }
    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )
    (trial / MEASUREMENTS).write_text(
        json.dumps(measurements, indent=2) + "\n", encoding="utf-8"
    )

    return trial


def _observations(
    trial: Path, required: tuple[GuideCheckName, ...]
) -> list[dict[str, Any]]:
    payload = _read(trial / OBSERVATIONS)
    names = [check.value for check in required]
    missing = sorted(set(names) - set(payload))
    unknown = sorted(set(payload) - set(names))

    if missing or unknown:
        raise ValueError(
            f"Observations must cover exactly this guide's checks; "
            f"missing: {missing}, unexpected: {unknown}"
        )

    observations = []

    for name in names:
        entry = payload[name]
        result = entry.get("result")

        if result not in ("pass", "fail"):
            raise ValueError(f"Observation {name} must be pass or fail, not {result!r}")

        observations.append(
            {
                "check": name,
                "passed": result == "pass",
                "notes": entry.get("notes", ""),
            }
        )

    return observations


def _optional_number(entry: dict[str, Any], name: str, where: str) -> float | None:
    value = entry.get(name)

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where}: {name} must be a number, not {value!r}")

    return float(value)


def _bore_results(trial: Path, build: dict[str, Any]) -> list[dict[str, Any]]:
    """Each bore's measured position against its nominal, and its printed hole
    against the model. A bore with no position measured is left unmeasured."""

    payload = _read(trial / MEASUREMENTS)
    listed = payload.get("bores")

    if not isinstance(listed, dict):
        raise TypeError("measurements.json must hold a bores object")

    expected = {bore["identifier"]: bore for bore in build.get("bores") or []}
    unknown = sorted(set(listed) - set(expected))

    if unknown:
        raise ValueError(
            f"measurements.json lists bores the guide does not have: {unknown}"
        )

    results = []

    for name, bore in expected.items():
        entry = listed.get(name) or {}
        where = f"measurements.json bore {name}"
        x = _optional_number(entry, "measured_x_mm", where)
        y = _optional_number(entry, "measured_y_mm", where)

        if (x is None) != (y is None):
            raise ValueError(
                f"{where}: give both measured_x_mm and measured_y_mm, or neither"
            )

        result: dict[str, Any] = {
            "identifier": name,
            "kind": bore["kind"],
            "nominal_mm": list(bore["entry_mm"]),
            "measured_mm": None,
            "offset_mm": None,
            "notes": entry.get("notes", ""),
        }

        if x is not None and y is not None:
            dx, dy = x - bore["entry_mm"][0], y - bore["entry_mm"][1]
            result["measured_mm"] = [x, y]
            result["offset_mm"] = {
                "dx": round(dx, 3),
                "dy": round(dy, 3),
                "radial": round(math.hypot(dx, dy), 3),
            }

        printed = _optional_number(entry, "measured_bore_mm", where)
        seat = _optional_number(entry, "measured_seat_mm", where)

        if printed is not None and bore["kind"] == "printed":
            result["bore_error_mm"] = round(printed - bore["hole_diameter_mm"], 3)

        if seat is not None and bore["kind"] == "bushing":
            result["seat_error_mm"] = round(seat - bore["pocket_diameter_mm"], 3)

        results.append(result)

    return results


def complete_guide_trial(
    trial: Path,
    *,
    disposition: GuideTrialDisposition,
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
    printed = build["parts"]["guide"]
    stl = Path(printed["stl_path"])

    if not stl.is_file() or sha256(stl) != printed["stl_sha256"]:
        raise ValueError(
            "The printed part no longer matches the build record: its STL has "
            "changed or is missing"
        )

    observations = _observations(trial, applicable_checks(build))
    bores = _bore_results(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]
    measured = [b for b in bores if b["offset_mm"] is not None]
    tolerance = _optional_number(
        _read(trial / MEASUREMENTS), "position_tolerance_mm", "measurements.json"
    )

    if tolerance is not None and tolerance <= 0:
        raise ValueError("measurements.json: position_tolerance_mm must be above zero")

    for bore in measured:
        bore["within_tolerance"] = (
            None
            if tolerance is None
            else bore["offset_mm"]["radial"] <= tolerance + 1e-9
        )

    if disposition is GuideTrialDisposition.PASS:
        if failed:
            raise ValueError(f"A passing trial cannot have failed checks: {failed}")

        unmeasured = [b["identifier"] for b in bores if b["offset_mm"] is None]

        if unmeasured:
            raise ValueError(
                f"A passing trial measures every bore's position; not measured: "
                f"{unmeasured}"
            )

        # Position is what a drill guide is for, so a pass says how close is
        # close enough, and every hole must land that close.
        if tolerance is None:
            raise ValueError(
                "A passing trial states position_tolerance_mm in measurements.json: "
                "how far a hole may land from where it was meant to and still pass"
            )

        off = [
            f"{b['identifier']} ({b['offset_mm']['radial']:g} mm)"
            for b in measured
            if not b["within_tolerance"]
        ]

        if off:
            raise ValueError(
                f"A passing trial lands every bore within {tolerance:g} mm; "
                f"these are farther off: {', '.join(off)}"
            )
    elif disposition is GuideTrialDisposition.INCONCLUSIVE and not (measured or failed):
        raise ValueError(
            "An inconclusive trial needs at least one measurement or a failed check"
        )

    radial = [b["offset_mm"]["radial"] for b in measured]
    record = {
        "schema_version": GUIDE_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["identifier"],
        "build_record_path": str(build_path),
        "build_record_sha256": sha256(build_path),
        "part_sha256": build["part"]["sha256"],
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "disposition": disposition.value,
        "passed": disposition is GuideTrialDisposition.PASS,
        "failed_checks": failed,
        "observations": observations,
        "bores": bores,
        "position_tolerance_mm": tolerance,
        "summary": {
            "bores": len(bores),
            "bores_measured": len(measured),
            "max_radial_mm": max(radial) if radial else None,
            "mean_radial_mm": round(sum(radial) / len(radial), 3) if radial else None,
        },
        "notes": notes,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path


def guide_verification(build_record_path: Path) -> dict[str, Any]:
    """Whether a build is verified: at least two passing trials of this exact
    build record. A rebuilt guide has a new record and starts with none."""

    digest = sha256(build_record_path)
    found = []

    for path in sorted(build_record_path.parent.glob("trials/*/" + TRIAL_RECORD)):
        record = _read(path)
        found.append(
            {
                "trial_id": record["trial_id"],
                "disposition": record["disposition"],
                "of_this_build": record["build_record_sha256"] == digest,
                "max_radial_mm": record["summary"]["max_radial_mm"],
                "position_tolerance_mm": record.get("position_tolerance_mm"),
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
