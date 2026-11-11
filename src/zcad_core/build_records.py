"""Reading the build records under ``evidence/``: which they are, their slices and trials, and status.

The z-cadalog (``scripts/build-catalog.py``) and the print-day pages
(``scripts/build-print-day.py``) both start from here, so a design the catalogue calls on print
day is one the print-day pages find, by the same rule.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

# Known build records: the product they are, and the file a completed trial writes.
KINDS = {
    "candidate.json": ("Validation Lab fixture", "trial.json"),
    "enclosure.json": ("Enclosure", "enclosure-trial.json"),
    "enclosure-group.json": ("Group enclosure", "enclosure-group-trial.json"),
    "coupon.json": ("Calibration coupon", "calibration-coupon-trial.json"),
    "joint-coupon.json": ("Joint coupon", "joint-coupon-trial.json"),
    "gridfinity.json": ("Gridfinity", "gridfinity-trial.json"),
    "holder.json": ("Object holder", "holder-trial.json"),
    "nest.json": ("Holding nest", "nest-trial.json"),
    "jig.json": ("Insert jig", "jig-trial.json"),
    "stack-build.json": ("Stackable items", "stack-trial.json"),
    "layer-build.json": ("Stack layer", "layer-trial.json"),
    "housing-build.json": ("Wearable housing", "housing-trial.json"),
    "guide.json": ("Drill guide", "guide-trial.json"),
    "fixture.json": ("PCB test fixture", "fixture-trial.json"),
}
# Folders a build writes inside its own, which hold no build records.
INNER = {
    "trials",
    "slice",
    "print",
    "export-validation",
    "review",
    "design-review-superseded",
}
# Builds from a template's example readings, one of each product not yet built for real.
EXAMPLES = "examples"


def read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"{path} is not a JSON object")

    return payload


def _parts_with_stl(record: dict[str, Any]) -> bool:
    parts = record.get("parts")

    return isinstance(parts, dict) and any(
        isinstance(part, dict) and "stl_path" in part for part in parts.values()
    )


def find_records(evidence: Path) -> list[Path]:
    """Every build record under ``evidence``: the known kinds by name, and any other JSON
    object whose ``parts`` give STL paths."""

    found = []

    for path in sorted(evidence.rglob("*.json")):
        relative = path.relative_to(evidence)

        if relative.parts[0].startswith(".") or INNER & set(relative.parts[:-1]):
            continue

        if path.name in KINDS:
            found.append(path)
            continue

        if path.name.endswith(".metadata.json"):
            continue

        try:
            record = read(path)
        except (TypeError, ValueError):
            continue

        if _parts_with_stl(record):
            found.append(path)

    return found


def locate(named: str, record_path: Path, evidence: Path) -> Path:
    """A path as a record writes it: absolute, from the repository (``evidence/...``), or
    beside the record. A record written in another checkout is found by name beside it."""

    path = Path(named)

    if not path.is_absolute():
        path = (
            evidence.parent / path
            if path.parts[:1] == ("evidence",)
            else record_path.parent / path
        )

    return path if path.is_file() else record_path.parent / path.name


def stl_files(
    record_path: Path, record: dict[str, Any], evidence: Path
) -> dict[str, Path]:
    """Each part's exported STL, found from the record's own paths."""

    if record_path.name == "candidate.json":
        # The candidate names its fixture; a snap shell's is a STEP only, with no STL.
        named = str(record.get("fixture_artifact_path") or "")
        fixture = locate(named, record_path, evidence) if named else None
        return (
            {"fixture": fixture}
            if fixture and fixture.suffix == ".stl" and fixture.is_file()
            else {}
        )

    found = {}
    parts = dict(record.get("parts") or {})

    # A stack build keeps each item's part under its name.
    for name, item in (record.get("items") or {}).items():
        if isinstance(item, dict) and isinstance(item.get("part"), dict):
            parts[name] = item["part"]

    for name, part in parts.items():
        if isinstance(part, dict) and "stl_path" in part:
            stl = locate(str(part["stl_path"]), record_path, evidence)

            if stl.is_file():
                found[name] = stl

    return found


def checks(record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks the build passed, and the checks a trial asks."""

    built: list[dict[str, Any]] = []
    asked: list[str] = []

    for source in (record.get("fit_checks"), record.get("checks")):
        if isinstance(source, dict):
            for name, value in source.items():
                if isinstance(value, dict):
                    built.append(
                        {
                            "name": name,
                            "passed": value.get("passed"),
                            "detail": str(value.get("detail", "")),
                        }
                    )
                elif isinstance(value, bool):
                    built.append({"name": name, "passed": value, "detail": ""})
        elif isinstance(source, list):
            asked.extend(str(name) for name in source)

    return built, asked


def slices(folder: Path) -> list[dict[str, Any]]:
    """Each plate a build was sliced to, from its ``slice-summary.json``."""

    plates = []

    for summary_path in sorted((folder / "slice").rglob("slice-summary.json")):
        summary = read(summary_path)
        gcode = sorted(summary_path.parent.glob("*.gcode"))
        plates.append(
            {
                "plate": summary_path.parent.relative_to(folder).as_posix(),
                "part": summary.get("part"),
                "minutes": round(summary["estimated_print_time_seconds"] / 60, 1),
                "grams": round(summary["filament_used_g"], 2),
                "warning": summary.get("slicer_warning", ""),
                "gcode": gcode[0] if gcode else None,
                "gcode_sha256": summary.get("gcode_sha256"),
                "rebuild": summary.get("rebuild"),
                "commit": (summary.get("source") or {}).get("git_commit"),
            }
        )

    return plates


def trials(folder: Path, trial_record: str) -> list[dict[str, Any]]:
    """Each trial folder: completed (its disposition) or open."""

    found = []

    for trial in sorted((folder / "trials").glob("trial-*")):
        record_path = trial / trial_record
        pending_path = trial / "physical-validation.json"

        if record_path.is_file():
            record = read(record_path)
            disposition = record.get("disposition")

            if disposition is None and pending_path.is_file():
                disposition = read(pending_path).get("disposition")

            found.append(
                {
                    "trial": trial.name,
                    "complete": True,
                    "disposition": disposition or "measured",
                    "record": record_path,
                }
            )
        elif pending_path.is_file() and not read(pending_path).get("pending", True):
            found.append(
                {
                    "trial": trial.name,
                    "complete": True,
                    "disposition": read(pending_path).get("disposition"),
                    "record": pending_path,
                }
            )
        else:
            found.append(
                {
                    "trial": trial.name,
                    "complete": False,
                    "disposition": "pending",
                    "record": trial,
                }
            )

    return found


def verified(record_path: Path) -> bool:
    """The kind's own verification rule, where it has one."""

    if record_path.name != "gridfinity.json":
        return False

    from zcad_core.features.gridfinity_trial import gridfinity_verification

    return bool(gridfinity_verification(record_path)["verified"])


def lineage(
    record_path: Path, record: dict[str, Any], records: dict[Path, dict[str, Any]]
) -> tuple[str | None, str | None]:
    """The design this one replaced, and the one that replaced it, by design id."""

    if record_path.name == "candidate.json":
        mine = record["candidate_id"]
        # Every relationship (supersedes, derived_from, adjusts_clearance_from) makes a new
        # revision from its parent, which it replaces.
        relationship = record_path.parent / "relationship.json"
        replaced = (
            read(relationship).get("target_candidate_id")
            if relationship.is_file()
            else None
        )
        replaced_by = None

        for other in record_path.parent.parent.glob("*/relationship.json"):
            link = read(other)

            if link.get("target_candidate_id") == mine:
                replaced_by = link.get("source_candidate_id")

        return replaced, replaced_by

    name = record.get("design_name")
    replaced = record.get("revision_of")
    replaced_by = next(
        (
            other.get("design_name") or path.parent.name
            for path, other in records.items()
            if path != record_path
            and other.get("revision_of")
            and other.get("revision_of") in (name, record_path.parent.name)
        ),
        None,
    )

    return (str(replaced) if replaced else None), replaced_by


def status_of(
    record_path: Path, record: dict[str, Any], records: dict[Path, dict[str, Any]]
) -> dict[str, Any]:
    """The design's status and the file that settled it."""

    folder = record_path.parent
    _, trial_record = KINDS.get(record_path.name, ("", ""))
    _, replaced_by = lineage(record_path, record, records)

    if replaced_by:
        return {"status": "superseded", "by": replaced_by, "evidence": None}

    if (folder / "promotion.json").is_file():
        return {"status": "promoted", "evidence": folder / "promotion.json"}

    if verified(record_path):
        return {"status": "verified", "evidence": record_path}

    found = trials(folder, trial_record) if trial_record else []
    completed = [trial for trial in found if trial["complete"]]

    if completed:
        last = completed[-1]
        return {
            "status": "trial recorded",
            "disposition": last["disposition"],
            "evidence": last["record"],
        }

    if found:
        return {"status": "on print day", "evidence": found[-1]["record"]}

    if (folder / "visual-review.json").is_file():
        review = read(folder / "visual-review.json")
        return {
            "status": "reviewed",
            "disposition": review.get("disposition"),
            "evidence": folder / "visual-review.json",
        }

    return {"status": "built", "evidence": record_path}


def name_of(record_path: Path, record: dict[str, Any]) -> str:
    """The design's name: a candidate's id, a build's design name, or its folder."""

    return str(
        record.get("candidate_id")
        or record.get("design_name")
        or record_path.parent.name
    )


def subject(record: dict[str, Any]) -> str | None:
    """What the design is for: a candidate's target, or an enclosure's board."""

    if record.get("target_id"):
        return str(record["target_id"])

    board = record.get("board")

    if isinstance(board, dict):
        return str(board.get("name") or board.get("id") or "") or None

    return str(board) if board else None


def commit_of(record: dict[str, Any], plates: list[dict[str, Any]]) -> str | None:
    """The commit the design was built at: its record's, or else its slice's."""

    commit = record.get("git_commit") or next(
        (plate["commit"] for plate in plates if plate.get("commit")), None
    )

    return str(commit) if commit else None


def head_commit(directory: Path) -> str | None:
    """The short commit ``directory`` is checked out at, or None outside git."""

    try:
        return subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def is_example(record_path: Path, evidence: Path) -> bool:
    """Built from a template's example readings, under ``evidence/examples/``."""

    return record_path.relative_to(evidence).parts[0] == EXAMPLES


def relative(path: Path | None, evidence: Path) -> str | None:
    """A path under ``evidence`` as the repository names it, ``evidence/...``."""

    if path is None:
        return None

    try:
        return "evidence/" + path.relative_to(evidence).as_posix()
    except ValueError:
        return str(path)
