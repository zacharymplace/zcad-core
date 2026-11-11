"""Build the print-day data: every part whose trial is open and whose slice is ready, from evidence/.

A print is a build record (the kinds the z-cadalog knows) that is current (not an example, not
superseded, not promoted or verified) and whose latest trial is open. For each it reads, from the
records and never from a hand-copied figure:

- the build record: name, kind, what it is for, the commit it was built at;
- each plate's ``slice-summary.json``: minutes, grams, its G-code and slicer warning;
- the open trial's ``observations.json``: the checks, and a joint coupon's rungs with what each
  is read for; its ``measurements.json``: each measurement, its nominal and how to take it; and a
  Gridfinity part's ``fit.json``;
- the disposition choices the kind's ``trial complete`` takes;
- ``print-notes.json`` beside the record, where present: what a person knows that no record does
  (``watch``, ``have``, ``optional``, ``after``; every field optional).

A current design that cannot go on the pages is listed with why: no open trial, not sliced, or a
slice whose G-code is missing. Prints with no notes are listed too.

Writes ``<output>/print-day.json``, replacing an earlier one; an ``<output>`` holding anything
else is refused. The pages drawn from it are later phases of docs/roadmaps/print-day-pages.md.

Usage:
    python scripts/build-print-day.py [--evidence-root evidence] [--output print-day]
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.build_records import (
    KINDS,
    commit_of,
    find_records,
    head_commit,
    is_example,
    name_of,
    read,
    relative,
    slices,
    status_of,
    subject,
    trials,
)
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.guide_trial import GuideTrialDisposition
from zcad_core.features.pcb_fixture_trial import FixtureTrialDisposition
from zcad_core.retention.physical_validation import PhysicalValidationDisposition

REPOSITORY = Path(__file__).resolve().parents[1]
PRINT_DAY_SCHEMA_VERSION = "1.0.0"
NOTES = "print-notes.json"
NOTE_FIELDS: dict[str, type] = {
    "watch": list,
    "have": list,
    "optional": bool,
    "after": str,
}
# Statuses that end a design's time on print day.
DONE = {"superseded", "promoted", "verified"}


def dispositions(record_name: str) -> list[str]:
    """What the kind's ``trial complete`` takes as an answer."""

    if record_name == "candidate.json":
        return [
            choice.value
            for choice in PhysicalValidationDisposition
            if choice is not PhysicalValidationDisposition.PENDING
        ]

    if record_name in ("coupon.json", "joint-coupon.json"):
        # A coupon has no verdict: it was measured, or it did not print.
        return ["measured", "fail"]

    if record_name == "guide.json":
        return [choice.value for choice in GuideTrialDisposition]

    if record_name == "fixture.json":
        return [choice.value for choice in FixtureTrialDisposition]

    return [choice.value for choice in EnclosureTrialDisposition]


def read_notes(folder: Path) -> dict[str, Any] | None:
    """``print-notes.json`` beside a build record, checked field by field."""

    path = folder / NOTES

    if not path.is_file():
        return None

    notes = read(path)
    unknown = sorted(set(notes) - set(NOTE_FIELDS))

    if unknown:
        raise ValueError(
            f"{path}: unknown field(s) {', '.join(unknown)}; "
            f"a print's notes take {', '.join(NOTE_FIELDS)}"
        )

    for field, expected in NOTE_FIELDS.items():
        if field in notes and not isinstance(notes[field], expected):
            raise ValueError(f"{path}: {field} must be a {expected.__name__}")

        if (
            expected is list
            and field in notes
            and not all(isinstance(line, str) for line in notes[field])
        ):
            raise ValueError(f"{path}: every line of {field} must be text")

    return {
        "watch": list(notes.get("watch", [])),
        "have": list(notes.get("have", [])),
        "optional": bool(notes.get("optional", False)),
        "after": notes.get("after"),
    }


def _observations(trial: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The open trial's checks, and its rungs: a check is answered yes or no, a rung is read."""

    path = trial / "observations.json"

    if not path.is_file():
        return [], []

    checks = []
    rungs = []

    for name, entry in read(path).items():
        if not isinstance(entry, dict):
            continue

        if "reading" in entry:
            reading = entry["reading"]
            rung = {
                key: value
                for key, value in entry.items()
                if key not in ("reading", "notes", "choices")
            }
            rung["name"] = name
            # A fit rung is read as one word of its choices; a snap rung as several readings.
            rung["reads"] = (
                {"choice": list(entry.get("choices", []))}
                if not isinstance(reading, dict)
                else {"readings": list(reading)}
            )
            rungs.append(rung)
        else:
            checks.append({"name": name, "guidance": str(entry.get("guidance", ""))})

    return checks, rungs


def _measurements(trial: Path) -> list[dict[str, Any]]:
    path = trial / "measurements.json"

    if not path.is_file():
        return []

    return [
        {
            "name": name,
            "nominal_mm": entry.get("nominal_mm"),
            # A fixture's template says how to take a measurement in its notes.
            "guidance": str(entry.get("guidance") or entry.get("notes") or ""),
        }
        for name, entry in read(path).items()
        if isinstance(entry, dict)
    ]


def _fit(trial: Path) -> dict[str, Any] | None:
    path = trial / "fit.json"

    return read(path) if path.is_file() else None


def _plates(folder: Path, evidence: Path) -> list[dict[str, Any]]:
    return [
        {
            "plate": plate["plate"],
            "part": plate["part"],
            "minutes": plate["minutes"],
            "grams": plate["grams"],
            "gcode": relative(plate["gcode"], evidence),
            "gcode_sha256": plate["gcode_sha256"],
            "warning": plate["warning"],
        }
        for plate in slices(folder)
    ]


def find_prints(evidence: Path) -> dict[str, Any]:
    """Every print ready for print day, the current designs left off with why, and the prints
    with no notes."""

    paths = find_records(evidence)
    records = {path: read(path) for path in paths}
    prints = []
    left_off = []

    for record_path, record in records.items():
        if is_example(record_path, evidence):
            continue

        folder = record_path.parent
        design_id = folder.relative_to(evidence).as_posix()
        kind, trial_record = KINDS.get(record_path.name, (None, None))

        if kind is None or trial_record is None:
            # The catalogue lists a record it does not know; print day cannot read its trials.
            left_off.append(
                {
                    "id": design_id,
                    "kind": f"Other ({record_path.name})",
                    "why": "the engine does not know this record's trials",
                }
            )
            continue

        if status_of(record_path, record, records)["status"] in DONE:
            continue

        found = trials(folder, trial_record)

        if found and found[-1]["complete"]:
            continue

        why = None
        plates = _plates(folder, evidence)

        if not found:
            why = "no open trial"
        elif not plates:
            why = "not sliced"
        elif missing := [plate["plate"] for plate in plates if not plate["gcode"]]:
            why = f"sliced, but no G-code in {', '.join(missing)}"

        if why:
            left_off.append({"id": design_id, "kind": kind, "why": why})
            continue

        trial = folder / "trials" / found[-1]["trial"]
        checks, rungs = _observations(trial)
        prints.append(
            {
                "id": design_id,
                "record": record_path.name,
                "kind": kind,
                "name": name_of(record_path, record),
                "for": subject(record),
                "commit": commit_of(record, slices(folder)),
                "trial": relative(trial, evidence),
                "plates": plates,
                "minutes": round(sum(plate["minutes"] for plate in plates), 1),
                "grams": round(sum(plate["grams"] for plate in plates), 2),
                "checks": checks,
                "measurements": _measurements(trial),
                "rungs": rungs,
                "fit": _fit(trial),
                "dispositions": dispositions(record_path.name),
                "notes": read_notes(folder),
            }
        )

    return {
        "prints": prints,
        "left_off": left_off,
        "without_notes": [entry["id"] for entry in prints if entry["notes"] is None],
    }


def build_print_day(evidence: Path, output: Path) -> dict[str, Any]:
    """Write ``print-day.json`` for ``evidence`` into ``output``, replacing an earlier one."""

    found = find_prints(evidence)

    if output.exists():
        if not (output / "print-day.json").is_file():
            raise FileExistsError(
                f"{output} exists and is not print-day output: refusing to replace it"
            )
        shutil.rmtree(output)

    output.mkdir(parents=True)
    data = {
        "schema_version": PRINT_DAY_SCHEMA_VERSION,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "repository_commit": head_commit(REPOSITORY),
        "evidence_commit": head_commit(evidence),
        **found,
    }
    (output / "print-day.json").write_text(
        json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )

    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    parser.add_argument("--output", type=Path, default=Path("print-day"))
    args = parser.parse_args()

    data = build_print_day(args.evidence_root.resolve(), args.output)
    print(
        json.dumps(
            {
                "print_day": str(args.output / "print-day.json"),
                "prints": len(data["prints"]),
                "minutes": round(sum(entry["minutes"] for entry in data["prints"]), 1),
                "left_off": {entry["id"]: entry["why"] for entry in data["left_off"]},
                "without_notes": len(data["without_notes"]),
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
