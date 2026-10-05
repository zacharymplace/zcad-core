"""Promote a board file into the catalog on the evidence of its trials.

A board from a file is unverified: nothing has shown its numbers fit the real
board. A board joins the catalog, as a file in ``hardware/data/boards/``, only
when at least two passing trials were printed from enclosures built from this
exact file. Each trial record names its build record, whose ``board_source``
carries the file's SHA-256, so a file edited since its trials is refused. The
promoted file is the board file with one field added, ``verified_by``, which
says which trials verified it and what file they were of.

Trials are counted by what they record, not where they lie: two records with
the same build record, trial id and completion time are one trial copied, and
count once.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from zcad_core.hardware import BOARD_CATALOG
from zcad_core.hardware.electronics.board_file import (
    catalog_filename,
    check_board_data,
    read_board_file,
)
from zcad_core.hardware.electronics.boards import BOARD_DATA_DIRECTORY

MINIMUM_TRIALS = 2


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def _trial_summary(
    record_path: Path, board_sha: str, identifier: str
) -> tuple[tuple[str, str, str], str]:
    """A passing trial of this exact file: what makes it one trial (its build
    record's SHA-256, its id and when it was completed), and a sentence for
    ``verified_by``. Refuses anything else."""

    trial = _read(record_path)

    if not trial.get("passed"):
        raise ValueError(f"{record_path} is not a passing trial")

    build_path = Path(trial["build_record_path"])

    if not build_path.is_file():
        raise ValueError(f"{record_path}: the build record {build_path} is missing")

    if hashlib.sha256(build_path.read_bytes()).hexdigest() != trial.get(
        "build_record_sha256"
    ):
        raise ValueError(f"{record_path}: the build record has changed since the trial")

    source = _read(build_path).get("board_source") or {}

    if source.get("kind") != "file" or source.get("identifier") != identifier:
        raise ValueError(
            f"{record_path} is not a trial of a board file for {identifier}"
        )

    if source.get("sha256") != board_sha:
        raise ValueError(
            f"{record_path} is a trial of a different version of the file: its "
            f"SHA-256 was {source.get('sha256')}, this file's is {board_sha}"
        )

    key = (
        str(trial.get("build_record_sha256")),
        str(trial["trial_id"]),
        str(trial["completed_at_utc"]),
    )

    return key, (
        f"{trial['design_name']} {trial['trial_id']} "
        f"({trial['printer_profile_id']}, {trial['material_profile_id']}, "
        f"{str(trial['completed_at_utc'])[:10]})"
    )


def promote_board(
    board_file: Path,
    trial_records: list[Path],
    directory: Path = BOARD_DATA_DIRECTORY,
) -> Path:
    """Write a verified copy of a board file into the catalog's data directory.

    Refuses a file with errors or warnings, an identifier the catalog already
    holds, fewer than two distinct passing trials of this exact file, and a
    file already in the directory."""

    data, origin = read_board_file(board_file)
    report = check_board_data(data)

    if not report.valid:
        raise ValueError(
            f"{board_file} is not a valid board file:\n- " + "\n- ".join(report.errors)
        )

    if report.warnings:
        raise ValueError(
            "A catalogued board has no warnings; settle these first:\n- "
            + "\n- ".join(report.warnings)
        )

    identifier = str(data["identifier"])

    try:
        BOARD_CATALOG.get(identifier)
    except ValueError:
        pass
    else:
        raise ValueError(f"{identifier} is already in the board catalog")

    found: dict[tuple[str, str, str], str] = {}

    for path in sorted({path.resolve() for path in trial_records}):
        key, summary = _trial_summary(path, origin.sha256, identifier)
        found.setdefault(key, summary)

    if len(found) < MINIMUM_TRIALS:
        raise ValueError(
            f"A board needs {MINIMUM_TRIALS} passing trials of its file to join "
            f"the catalog; {len(found)} distinct given (a trial copied to "
            "another folder counts once)"
        )

    trials = list(found.values())
    target = directory / catalog_filename(identifier)

    if target.exists():
        raise FileExistsError(f"{target} already exists")

    promoted = {
        **data,
        "verified_by": (
            f"{len(trials)} passing trials of the board file with SHA-256 "
            f"{origin.sha256}: " + "; ".join(trials)
        ),
    }
    directory.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(promoted, indent=2) + "\n", encoding="utf-8")

    return target
