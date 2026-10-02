"""Print records for PCB test fixtures: what was built, and how the pins landed.

``fixture build`` writes a ``fixture.json`` build record beside the exported
nest and plate: the fixture file and the board by hash, each test point with its
pad, its slack and its worst-case misalignment, and the printed parts' STL
hashes. A trial then records one print of exactly those parts, with the board in
it and the plate closed:

1. :func:`start_fixture_trial` writes ``trials/trial-NNN/`` with an
   ``observations.json`` and a ``measurements.json`` template listing only the
   checks and points that apply to this fixture.
2. Print the fixture, seat the board, close the plate, and fill both in: whether
   each pin made contact, and where its tip mark fell against the pad's centre.
3. :func:`complete_fixture_trial` validates them and writes
   ``fixture-trial.json``, with each point's offset and how much of its slack
   that used. A completed trial is never overwritten; record another print as
   the next trial.

A fixture that has passed two trials of the same build record is verified
(:func:`fixture_verification`): each of those trials had every point in contact
and every check passing. The offsets of passing trials are pooled into a
measured misalignment by :mod:`zcad_core.profiles.fixture_accuracy`. The engine
states no accuracy of its own: these trials are the only source of one, and the
worst-case sum a build computes stays what it was, a bound from provisional
tolerances.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

FIXTURE_TRIAL_SCHEMA_VERSION = "1.0.0"
BUILD_RECORD = "fixture.json"
TRIAL_RECORD = "fixture-trial.json"
OBSERVATIONS = "observations.json"
MEASUREMENTS = "measurements.json"
# A fixture is verified by this many passing trials of the same build.
MINIMUM_TRIALS_TO_VERIFY = 2


class FixtureTrialDisposition(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class FixtureCheckName(str, Enum):
    BOARD_SEATS = "board_seats_in_nest"
    BOARD_RELEASES = "board_releases"
    PLATE_SEATS = "plate_seats_on_rim"
    PLATE_STAYS_DOWN = "plate_stays_down"
    PINS_TRAVEL = "pins_travel_freely"
    PLATE_SWINGS = "plate_swings_free"


CHECK_GUIDANCE = {
    FixtureCheckName.BOARD_SEATS: (
        "Drop the board into the nest. It should seat on its ledge without "
        "rocking, and no part should meet the nest."
    ),
    FixtureCheckName.BOARD_RELEASES: (
        "Lift the board straight out of the nest by the finger notches. It "
        "should come away without catching a part on the wall."
    ),
    FixtureCheckName.PLATE_SEATS: (
        "Set the plate on the nest's rim, over its dowels or posts, or close a "
        "hinged plate onto it. It should go down onto the rim without forcing, "
        "with no gap you could not explain by the clearance."
    ),
    FixtureCheckName.PLATE_STAYS_DOWN: (
        "Fit the screws, or click the catch home, and close the plate against "
        "the pins. It should stay on the rim at the working travel, with no gap "
        "opening at the rim between the screws, or between the hinge and the "
        "catch."
    ),
    FixtureCheckName.PINS_TRAVEL: (
        "With the plate off, press each pin by its working travel and let go. "
        "It should move freely and spring back, without binding in its bore."
    ),
    FixtureCheckName.PLATE_SWINGS: (
        "Fit the hinge pin and swing the plate open and shut with the pins in "
        "it, over the board. No pin should catch a part or the nest, the catch "
        "should click home and hold the plate when shaken, and the board should "
        "lift out with the plate open."
    ),
}
FRAME_NOTE = (
    "Offsets are in the board's own frame, +X to the right and +Y up the page "
    "seen from above: where the pin's tip mark fell from the pad's centre, "
    "offset_x_mm to the right and offset_y_mm up. Find the mark with a thin "
    "coat of marker on the pad, or a witness mark, and measure its centre from "
    "the pad's."
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def applicable_checks(build: dict[str, Any]) -> tuple[FixtureCheckName, ...]:
    """The checks for a fixture: five, since a built fixture always has a nest, a
    plate, and pins, and a sixth, the swing, if the plate is hinged."""

    return tuple(
        check
        for check in FixtureCheckName
        if check is not FixtureCheckName.PLATE_SWINGS or build.get("closure") == "hinge"
    )


def start_fixture_trial(build_record_path: Path) -> Path:
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
    points = {
        point["identifier"]: {
            "net": point.get("net", ""),
            "nominal_position_mm": point["position_mm"],
            "pad_diameter_mm": point["pad_diameter_mm"],
            "slack_mm": point["slack_mm"],
            "contact": None,
            "offset_x_mm": None,
            "offset_y_mm": None,
            "notes": "",
        }
        for point in build["points"]
    }
    measurements = {
        "frame": FRAME_NOTE,
        "contact": (
            "contact is true if the pin made contact with its pad (a continuity "
            "check, or a program loading) and false if not. A passing trial has "
            "every point true."
        ),
        "offset": (
            "offset_x_mm and offset_y_mm are optional, and both or neither. Give "
            "them for a point that missed, to see how far, and for the points "
            "that touched, to pool a measured misalignment."
        ),
        "points": points,
    }
    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )
    (trial / MEASUREMENTS).write_text(
        json.dumps(measurements, indent=2) + "\n", encoding="utf-8"
    )

    return trial


def _observations(
    trial: Path, required: tuple[FixtureCheckName, ...]
) -> list[dict[str, Any]]:
    payload = _read(trial / OBSERVATIONS)
    names = [check.value for check in required]
    missing = sorted(set(names) - set(payload))
    unknown = sorted(set(payload) - set(names))

    if missing or unknown:
        raise ValueError(
            f"Observations must cover exactly this fixture's checks; "
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


def _contact(entry: dict[str, Any], where: str) -> bool | None:
    value = entry.get("contact")

    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{where}: contact must be true or false, not {value!r}")

    return value


def _point_results(trial: Path, build: dict[str, Any]) -> list[dict[str, Any]]:
    """Each point's contact and offset, and how much of its slack the offset
    used. A point with no offset measured is left unmeasured."""

    payload = _read(trial / MEASUREMENTS)
    listed = payload.get("points")

    if not isinstance(listed, dict):
        raise TypeError("measurements.json must hold a points object")

    expected = {point["identifier"]: point for point in build["points"]}
    unknown = sorted(set(listed) - set(expected))

    if unknown:
        raise ValueError(
            f"measurements.json lists points the fixture does not probe: {unknown}"
        )

    results = []

    for name, point in expected.items():
        entry = listed.get(name) or {}
        where = f"measurements.json point {name}"
        x = _optional_number(entry, "offset_x_mm", where)
        y = _optional_number(entry, "offset_y_mm", where)

        if (x is None) != (y is None):
            raise ValueError(
                f"{where}: give both offset_x_mm and offset_y_mm, or neither"
            )

        result: dict[str, Any] = {
            "identifier": name,
            "net": point.get("net", ""),
            "pad_diameter_mm": point["pad_diameter_mm"],
            "slack_mm": point["slack_mm"],
            "assumed_misalignment_mm": point["misalignment_mm"],
            "contact": _contact(entry, where),
            "offset_mm": None,
            "share_of_slack": None,
            "notes": entry.get("notes", ""),
        }

        if x is not None and y is not None:
            radial = math.hypot(x, y)
            result["offset_mm"] = {
                "dx": round(x, 3),
                "dy": round(y, 3),
                "radial": round(radial, 3),
            }

            if point["slack_mm"] > 0:
                result["share_of_slack"] = round(radial / point["slack_mm"], 3)

        results.append(result)

    return results


def _require_parts_match(build: dict[str, Any]) -> None:
    for name in ("nest", "plate"):
        printed = build["parts"][name]
        stl = Path(printed["stl_path"])

        if not stl.is_file() or sha256(stl) != printed["stl_sha256"]:
            raise ValueError(
                f"The printed {name} no longer matches the build record: its STL "
                "has changed or is missing"
            )


def _check_disposition(
    disposition: FixtureTrialDisposition,
    failed: list[str],
    points: list[dict[str, Any]],
) -> None:
    measured = [p for p in points if p["offset_mm"] is not None]
    missed = [p["identifier"] for p in points if p["contact"] is False]

    if disposition is FixtureTrialDisposition.PASS:
        if failed:
            raise ValueError(f"A passing trial cannot have failed checks: {failed}")

        unanswered = [p["identifier"] for p in points if p["contact"] is None]

        if unanswered:
            raise ValueError(
                f"A passing trial says whether every point made contact; not "
                f"answered: {unanswered}"
            )

        if missed:
            raise ValueError(
                f"A passing trial has every point in contact; missed: {missed}"
            )
    elif disposition is FixtureTrialDisposition.INCONCLUSIVE and not (
        measured or failed or missed
    ):
        raise ValueError(
            "An inconclusive trial needs at least one offset, a missed point, "
            "or a failed check"
        )


def complete_fixture_trial(
    trial: Path,
    *,
    disposition: FixtureTrialDisposition,
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
    _require_parts_match(build)
    observations = _observations(trial, applicable_checks(build))
    points = _point_results(trial, build)
    failed = [entry["check"] for entry in observations if not entry["passed"]]
    _check_disposition(disposition, failed, points)
    measured = [p for p in points if p["offset_mm"] is not None]
    radial = [p["offset_mm"]["radial"] for p in measured]
    answered = [p for p in points if p["contact"] is not None]
    record = {
        "schema_version": FIXTURE_TRIAL_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["identifier"],
        "build_record_path": str(build_path),
        "build_record_sha256": sha256(build_path),
        "board_sha256": build["board"]["sha256"],
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "disposition": disposition.value,
        "passed": disposition is FixtureTrialDisposition.PASS,
        "failed_checks": failed,
        "observations": observations,
        "points": points,
        "summary": {
            "points": len(points),
            "points_answered": len(answered),
            "points_in_contact": sum(1 for p in answered if p["contact"]),
            "offsets_measured": len(measured),
            "max_radial_mm": max(radial) if radial else None,
            "mean_radial_mm": round(sum(radial) / len(radial), 3) if radial else None,
            "offsets_over_slack": sum(
                1
                for p in measured
                if p["share_of_slack"] is not None and p["share_of_slack"] > 1.0
            ),
        },
        "notes": notes,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return record_path


def fixture_verification(build_record_path: Path) -> dict[str, Any]:
    """Whether a build is verified: at least two passing trials of this exact
    build record. A rebuilt fixture has a new record and starts with none."""

    digest = sha256(build_record_path)
    found = []

    for path in sorted(build_record_path.parent.glob("trials/*/" + TRIAL_RECORD)):
        record = _read(path)
        found.append(
            {
                "trial_id": record["trial_id"],
                "disposition": record["disposition"],
                "of_this_build": record["build_record_sha256"] == digest,
                "points_in_contact": record["summary"]["points_in_contact"],
                "points": record["summary"]["points"],
                "max_radial_mm": record["summary"]["max_radial_mm"],
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
