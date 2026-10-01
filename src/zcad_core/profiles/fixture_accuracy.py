"""Fixture accuracy profiles: how far a printed fixture's pins land off their
pads, measured.

A fixture trial records, for every test point, where the pin's tip mark fell
against the pad's centre. A fixture accuracy profile pools those offsets from
every passing trial for one printer and one material:

- ``position``: the mean, spread and largest radial offset, the sample count,
  and the mean offset in X and Y (a bias: all tips landing the same way means the
  board's seat or the plate's turn is off, not the pins' play);
- ``share_of_slack``: the largest share of a pad's slack any tip used, which
  says how near the pooled prints came to missing; and
- ``contact``: how many points of the pooled trials were probed, and how many
  made contact (a passing trial has all of them).

A build that is given a profile reports these beside the worst-case sum it
computes, with the sample size, and says so when the measured offsets are bigger
than a point's slack or than the sum. The profile never replaces the sum: it is
evidence about one printer, material and way of measuring, and the engine states
it as that.

Profiles live in ``profiles/fixtures/<printer>-<material>.json``; deriving again
writes the next version and keeps the previous figures in its history.

The trial records are read as plain JSON, so this module depends on neither the
fixture builder nor the Validation Lab.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIXTURE_ACCURACY_SCHEMA_VERSION = "1.0.0"
# One trial is a data point; a profile pools several.
DEFAULT_MINIMUM_TRIALS = 2


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def collect_fixture_trials(
    evidence_root: Path, *, printer_profile_id: str, material_profile_id: str
) -> list[tuple[Path, dict[str, Any]]]:
    """Every passing fixture trial for one printer and one material."""

    trials = []

    for path in sorted(evidence_root.rglob("trials/*/fixture-trial.json")):
        record = _read(path)

        if (
            record.get("passed")
            and record.get("printer_profile_id") == printer_profile_id
            and record.get("material_profile_id") == material_profile_id
        ):
            trials.append((path, record))

    return trials


def derive_fixture_profile(
    evidence_root: Path,
    *,
    printer_profile_id: str,
    material_profile_id: str,
    minimum_trials: int = DEFAULT_MINIMUM_TRIALS,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pool the passing fixture trials into the next version of a profile."""

    trials = collect_fixture_trials(
        evidence_root,
        printer_profile_id=printer_profile_id,
        material_profile_id=material_profile_id,
    )

    if len(trials) < minimum_trials:
        raise ValueError(
            f"{len(trials)} passing fixture trial(s) for {printer_profile_id} in "
            f"{material_profile_id}; a profile needs at least {minimum_trials}"
        )

    offsets: list[dict[str, float]] = []
    shares: list[float] = []
    probed = 0
    in_contact = 0

    for _, record in trials:
        for point in record["points"]:
            probed += 1
            in_contact += 1 if point.get("contact") else 0

            if point.get("offset_mm") is not None:
                offsets.append(point["offset_mm"])

            if point.get("share_of_slack") is not None:
                shares.append(float(point["share_of_slack"]))

    if not offsets:
        raise ValueError("The passing trials measured no point's offset")

    radial = [o["radial"] for o in offsets]
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
        "schema_version": FIXTURE_ACCURACY_SCHEMA_VERSION,
        "profile_id": f"{printer_profile_id}-{material_profile_id}",
        "printer_profile_id": printer_profile_id,
        "material_profile_id": material_profile_id,
        "version": (previous["version"] + 1) if previous else 1,
        "derived_at_utc": datetime.now(UTC).isoformat(),
        "figures": {
            "position": {
                "mean": round(statistics.fmean(radial), 3),
                "spread": round(statistics.pstdev(radial), 3),
                "max": round(max(radial), 3),
                "samples": len(radial),
                "bias_mm": [
                    round(statistics.fmean(o["dx"] for o in offsets), 3),
                    round(statistics.fmean(o["dy"] for o in offsets), 3),
                ],
            },
            "max_share_of_slack": round(max(shares), 3) if shares else None,
            "contact": {"points": probed, "in_contact": in_contact},
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


def write_fixture_profile(profile: dict[str, Any], path: Path) -> Path:
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
class FixtureAccuracyProfile:
    """A loaded profile and the reference a build records for it."""

    path: Path
    payload: dict[str, Any]

    @property
    def printer_profile_id(self) -> str:
        return str(self.payload["printer_profile_id"])

    @property
    def material_profile_id(self) -> str:
        return str(self.payload["material_profile_id"])

    @property
    def position(self) -> dict[str, Any]:
        return dict(self.payload["figures"]["position"])

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


def load_fixture_profile(path: Path) -> FixtureAccuracyProfile:
    payload = _read(path)

    if payload.get("schema_version") != FIXTURE_ACCURACY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported fixture accuracy profile schema in {path}")

    position = payload.get("figures", {}).get("position")

    if not isinstance(position, dict) or "max" not in position:
        raise ValueError(f"{path} has no measured position figure")

    return FixtureAccuracyProfile(path=path, payload=payload)
