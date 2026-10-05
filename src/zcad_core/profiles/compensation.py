"""Compensation profiles: how one printer and material print a fit.

Every recorded trial measures how far a printed fit came out from the fit
that was modelled. A compensation profile pools those errors across all the
trials for one printer and material:

- ``hole_shortfall_mm``: how much smaller holes print than modelled, from
  enclosure trials' insert pockets and lid screw holes (the modelled size is
  the intended size plus the build's ``hole_compensation_mm``);
- ``side_gap_shortfall_mm``: how much tighter a fixture's side gap prints
  than its ``board_clearance_mm``; and
- ``vertical_play_shortfall_mm``: how much tighter a fixture's vertical play
  prints than its clearance plus overlap.

Positive means tighter than modelled. Each figure keeps its mean, spread,
and sample count, and the profile lists every trial record it read, with its
hash. Profiles live in ``profiles/compensation/<printer>-<material>.json``;
deriving again writes the next version and keeps the previous figures in the
profile's history. Builds that apply a profile record its id, version, and
hash.

The trial records are read as plain JSON, so this module depends on neither
the Validation Lab nor the enclosure builder.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.profiles.trial_records import distinct_trial_records

COMPENSATION_SCHEMA_VERSION = "1.0.0"
FIGURES = ("hole_shortfall_mm", "side_gap_shortfall_mm", "vertical_play_shortfall_mm")
# One trial is a revision's job; a profile pools several.
DEFAULT_MINIMUM_TRIALS = 2
HOLE_MEASUREMENTS = ("insert_pocket_diameter_mm", "lid_hole_diameter_mm")


@dataclass(frozen=True)
class Sample:
    """One measured error from one trial record."""

    figure: str
    shortfall_mm: float
    record: Path


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def _measured(record: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Each measurement with a nominal, as (nominal, measured)."""

    return {
        entry["name"]: (float(entry["nominal_mm"]), float(entry["value_mm"]))
        for entry in record.get("measurements", [])
        if entry.get("nominal_mm") is not None and entry.get("value_mm") is not None
    }


def _fixture_samples(path: Path, record: dict[str, Any]) -> list[Sample]:
    measured = _measured(record)
    samples = []

    for name, figure in (
        ("board_clearance", "side_gap_shortfall_mm"),
        ("vertical_play", "vertical_play_shortfall_mm"),
    ):
        if name in measured:
            nominal, value = measured[name]
            samples.append(Sample(figure, nominal - value, path))

    return samples


def _enclosure_samples(path: Path, record: dict[str, Any]) -> list[Sample]:
    build = _read(Path(record["build_record_path"]))
    modelled_extra = float(build["design"].get("hole_compensation_mm", 0.0))
    measured = _measured(record)

    return [
        Sample(
            "hole_shortfall_mm",
            measured[name][0] + modelled_extra - measured[name][1],
            path,
        )
        for name in HOLE_MEASUREMENTS
        if name in measured
    ]


def collect_samples(
    evidence_root: Path, *, printer_profile_id: str, material_profile_id: str
) -> list[Sample]:
    """Every measured error in the recorded trials for one printer and material."""

    samples: list[Sample] = []

    # Each record once: a copy in a second folder is the same trial.
    for path, record in distinct_trial_records(
        evidence_root, "trials/*/physical-validation.json"
    ):
        pending = (
            record.get("disposition") == "pending"
            or not record.get("completed_at_utc", "").strip()
        )

        if (
            not pending
            and record.get("printer_profile") == printer_profile_id
            and record.get("material_profile") == material_profile_id
        ):
            samples.extend(_fixture_samples(path, record))

    for path, record in distinct_trial_records(
        evidence_root, "trials/*/enclosure-trial.json"
    ):
        if (
            record.get("printer_profile_id") == printer_profile_id
            and record.get("material_profile_id") == material_profile_id
        ):
            samples.extend(_enclosure_samples(path, record))

    return samples


def _figure(samples: Iterable[Sample]) -> dict[str, Any] | None:
    samples = list(samples)
    values = [sample.shortfall_mm for sample in samples]

    if not values:
        return None

    return {
        "mean_mm": round(statistics.fmean(values), 3),
        "spread_mm": round(statistics.pstdev(values), 3),
        "samples": len(values),
        "trials": len({sample.record for sample in samples}),
    }


def derive_compensation_profile(
    evidence_root: Path,
    *,
    printer_profile_id: str,
    material_profile_id: str,
    minimum_trials: int = DEFAULT_MINIMUM_TRIALS,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pool the recorded trials into the next version of a profile."""

    samples = collect_samples(
        evidence_root,
        printer_profile_id=printer_profile_id,
        material_profile_id=material_profile_id,
    )
    trials = sorted({sample.record for sample in samples})

    if len(trials) < minimum_trials:
        raise ValueError(
            f"{len(trials)} recorded trial(s) for {printer_profile_id} with "
            f"{material_profile_id}; a profile needs at least {minimum_trials}. "
            "Revise from a single trial instead."
        )

    figures = {
        figure: _figure(sample for sample in samples if sample.figure == figure)
        for figure in FIGURES
    }
    history = list(previous.get("history", [])) if previous else []

    if previous:
        history.append(
            {
                "version": previous["version"],
                "derived_at_utc": previous["derived_at_utc"],
                "figures": previous["figures"],
            }
        )

    return {
        "schema_version": COMPENSATION_SCHEMA_VERSION,
        "profile_id": f"{printer_profile_id}-{material_profile_id}",
        "printer_profile_id": printer_profile_id,
        "material_profile_id": material_profile_id,
        "version": (previous["version"] + 1) if previous else 1,
        "derived_at_utc": datetime.now(UTC).isoformat(),
        "figures": figures,
        "sources": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in trials
        ],
        "history": history,
    }


def write_compensation_profile(profile: dict[str, Any], path: Path) -> Path:
    """Write a profile; the file only ever moves to the next version."""

    if path.exists():
        current = _read(path)

        if profile.get("version", 0) <= current.get("version", 0):
            raise FileExistsError(
                f"{path} is at version {current.get('version')}; derive the next "
                "version from it instead of replacing it"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", "utf-8")

    return path


@dataclass(frozen=True)
class CompensationProfile:
    """A loaded profile and the reference a build records for it."""

    path: Path
    payload: dict[str, Any]

    def mean(self, figure: str) -> float | None:
        entry = self.payload["figures"].get(figure)

        return None if entry is None else float(entry["mean_mm"])

    def reference(self) -> dict[str, Any]:
        return {
            "profile_id": self.payload["profile_id"],
            "version": self.payload["version"],
            "path": str(self.path),
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
        }


def load_compensation_profile(path: Path) -> CompensationProfile:
    payload = _read(path)

    if payload.get("schema_version") != COMPENSATION_SCHEMA_VERSION:
        raise ValueError(f"Unsupported compensation profile schema in {path}")

    return CompensationProfile(path=path, payload=payload)
