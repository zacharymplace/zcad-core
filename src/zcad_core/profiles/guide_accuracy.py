"""Guide accuracy profiles: how far a printed drill guide's holes land, measured.

A guide trial records, for every bore, where a drilled hole came out against
where it was meant to. A guide accuracy profile pools those offsets from every
passing trial for one printer and one material:

- ``position``: per bore kind (``printed`` or ``bushing``), the mean, spread,
  and largest radial offset, the sample count, and the mean offset in X and Y
  (a bias: all holes landing the same way means the frame or the print is off,
  not the guide's play); and
- ``bore_diameter_error_mm`` and ``seat_diameter_error_mm``: how much a printed
  bore and a bushing pocket came out against the model, which is what the
  printer's ``hole_oversize`` is meant to cancel.

A build that is given a profile reports these beside the clearance bound it
computes, with the sample size, and says so when the measured offsets are bigger
than that bound. The profile never replaces the bound: it is evidence about one
printer, material, and way of measuring, and the engine states it as that.

Profiles live in ``profiles/guides/<printer>-<material>.json``; deriving again
writes the next version and keeps the previous figures in its history.

The trial records are read as plain JSON, so this module depends on neither the
guide builder nor the Validation Lab.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.profiles.trial_records import distinct_trial_records

GUIDE_ACCURACY_SCHEMA_VERSION = "1.0.0"
# One trial is a data point; a profile pools several.
DEFAULT_MINIMUM_TRIALS = 2
KINDS = ("printed", "bushing")


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def collect_guide_trials(
    evidence_root: Path, *, printer_profile_id: str, material_profile_id: str
) -> list[tuple[Path, dict[str, Any]]]:
    """Every passing guide trial for one printer and one material."""

    trials = []

    # Each record once: a copy in a second folder is the same trial.
    for path, record in distinct_trial_records(
        evidence_root, "trials/*/guide-trial.json"
    ):
        if (
            record.get("passed")
            and record.get("printer_profile_id") == printer_profile_id
            and record.get("material_profile_id") == material_profile_id
        ):
            trials.append((path, record))

    return trials


def _figure(values: list[float]) -> dict[str, Any]:
    return {
        "mean": round(statistics.fmean(values), 3),
        "spread": round(statistics.pstdev(values), 3),
        "samples": len(values),
    }


def _position(offsets: list[dict[str, float]]) -> dict[str, Any] | None:
    if not offsets:
        return None

    radial = [o["radial"] for o in offsets]

    return {
        **_figure(radial),
        "max": round(max(radial), 3),
        "bias_mm": [
            round(statistics.fmean(o["dx"] for o in offsets), 3),
            round(statistics.fmean(o["dy"] for o in offsets), 3),
        ],
    }


def derive_guide_profile(
    evidence_root: Path,
    *,
    printer_profile_id: str,
    material_profile_id: str,
    minimum_trials: int = DEFAULT_MINIMUM_TRIALS,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pool the passing guide trials into the next version of a profile."""

    trials = collect_guide_trials(
        evidence_root,
        printer_profile_id=printer_profile_id,
        material_profile_id=material_profile_id,
    )

    if len(trials) < minimum_trials:
        raise ValueError(
            f"{len(trials)} passing guide trial(s) for {printer_profile_id} in "
            f"{material_profile_id}; a profile needs at least {minimum_trials}"
        )

    offsets: dict[str, list[dict[str, float]]] = {kind: [] for kind in KINDS}
    bore_errors: list[float] = []
    seat_errors: list[float] = []

    for _, record in trials:
        for bore in record["bores"]:
            if bore.get("offset_mm") is not None:
                offsets[bore["kind"]].append(bore["offset_mm"])

            if bore.get("bore_error_mm") is not None:
                bore_errors.append(float(bore["bore_error_mm"]))

            if bore.get("seat_error_mm") is not None:
                seat_errors.append(float(bore["seat_error_mm"]))

    if not any(offsets.values()):
        raise ValueError("The passing trials measured no bore's position")

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
        "schema_version": GUIDE_ACCURACY_SCHEMA_VERSION,
        "profile_id": f"{printer_profile_id}-{material_profile_id}",
        "printer_profile_id": printer_profile_id,
        "material_profile_id": material_profile_id,
        "version": (previous["version"] + 1) if previous else 1,
        "derived_at_utc": datetime.now(UTC).isoformat(),
        "figures": {
            "position": {kind: _position(offsets[kind]) for kind in KINDS},
            "bore_diameter_error_mm": _figure(bore_errors) if bore_errors else None,
            "seat_diameter_error_mm": _figure(seat_errors) if seat_errors else None,
        },
        "trials": len(trials),
        "sources": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path, _ in trials
        ],
        "history": history,
    }


def write_guide_profile(profile: dict[str, Any], path: Path) -> Path:
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
class GuideAccuracyProfile:
    """A loaded profile and the reference a build records for it."""

    path: Path
    payload: dict[str, Any]

    @property
    def printer_profile_id(self) -> str:
        return str(self.payload["printer_profile_id"])

    @property
    def material_profile_id(self) -> str:
        return str(self.payload["material_profile_id"])

    def position(self, kind: str) -> dict[str, Any] | None:
        return self.payload["figures"]["position"].get(kind)

    def describe(self) -> str:
        return (
            f"profile {self.payload['profile_id']} v{self.payload['version']}: "
            f"{self.payload['trials']} passing trials"
        )

    def reference(self) -> dict[str, Any]:
        return {
            "profile_id": self.payload["profile_id"],
            "version": self.payload["version"],
            "path": str(self.path),
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
        }


def load_guide_profile(path: Path) -> GuideAccuracyProfile:
    payload = _read(path)

    if payload.get("schema_version") != GUIDE_ACCURACY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported guide accuracy profile schema in {path}")

    position = payload.get("figures", {}).get("position")

    if not isinstance(position, dict) or not any(position.values()):
        raise ValueError(f"{path} has no measured position figure")

    return GuideAccuracyProfile(path=path, payload=payload)
