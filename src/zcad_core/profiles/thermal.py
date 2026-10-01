"""Thermal profiles: how printed boxes of one material shed heat, measured.

A thermal trial records the steady-state air temperature inside a printed box
with a known power in it. From one closed box (no vent, fan, or lid slot) that
gives an effective coefficient, ``power / (surface * rise)``, to set against
the 8 W/m2K the temperature estimate assumes. A thermal profile pools those
coefficients across every closed-box trial for one material:

- ``convection_w_m2k``: the mean, spread, and count of the effective
  coefficients, which a build can use in place of the default; and
- ``ventilated``: each vented or fanned trial's measured conductance, beside
  the passive conductance that box would have had, as a ratio. These are
  listed and not pooled, because each is one configuration; they are what
  decides whether vents and fans can be credited, and by how much.

It also keeps what the trials saw of the plastic: the highest air temperature
at which no deformation was observed, and the lowest at which some was. They
inform the material's ``max_service_c`` and never replace it.

Profiles live in ``profiles/thermal/<material>.json``; deriving again writes the
next version and keeps the previous figures in its history. A build that
applies a profile records its id, version, and hash.

The trial records are read as plain JSON, so this module depends on neither
the Validation Lab nor the enclosure builder.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

THERMAL_SCHEMA_VERSION = "1.0.0"
# One trial is a data point; a profile pools several.
DEFAULT_MINIMUM_TRIALS = 2


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def collect_thermal_trials(
    evidence_root: Path, *, material_profile_id: str
) -> list[tuple[Path, dict[str, Any]]]:
    """Every completed trial of one material that recorded a temperature."""

    trials = []

    for path in sorted(evidence_root.rglob("trials/*/enclosure-trial.json")):
        record = _read(path)
        thermal = record.get("thermal")

        if record.get("material_profile_id") == material_profile_id and thermal:
            trials.append((path, thermal))

    return trials


def _figure(values: list[float]) -> dict[str, Any]:
    return {
        "mean": round(statistics.fmean(values), 3),
        "spread": round(statistics.pstdev(values), 3),
        "samples": len(values),
    }


def derive_thermal_profile(
    evidence_root: Path,
    *,
    material_profile_id: str,
    minimum_trials: int = DEFAULT_MINIMUM_TRIALS,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pool the recorded thermal trials into the next version of a profile."""

    trials = collect_thermal_trials(
        evidence_root, material_profile_id=material_profile_id
    )
    closed = [(path, t) for path, t in trials if t.get("closed")]

    if len(closed) < minimum_trials:
        raise ValueError(
            f"{len(closed)} closed-box thermal trial(s) for {material_profile_id}; a "
            f"profile needs at least {minimum_trials}. Vented and fanned trials "
            "are recorded but cannot set the passive coefficient."
        )

    coefficient = _figure([float(t["h_effective_w_m2k"]) for _, t in closed])
    ventilated = [
        {
            "record": str(path),
            "conductance_w_k": t["conductance_w_k"],
            "passive_conductance_w_k": round(
                coefficient["mean"] * float(t["surface_m2"]), 4
            ),
            "conductance_ratio": round(
                float(t["conductance_w_k"])
                / (coefficient["mean"] * float(t["surface_m2"])),
                2,
            ),
            "configuration": t.get("configuration"),
        }
        for path, t in trials
        if not t.get("closed")
    ]
    clean = [
        float(t["internal_air_c"]) for _, t in trials if not t["deformation_observed"]
    ]
    deformed = [
        float(t["internal_air_c"]) for _, t in trials if t["deformation_observed"]
    ]
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
        "schema_version": THERMAL_SCHEMA_VERSION,
        "profile_id": material_profile_id,
        "material_profile_id": material_profile_id,
        "version": (previous["version"] + 1) if previous else 1,
        "derived_at_utc": datetime.now(UTC).isoformat(),
        "figures": {"convection_w_m2k": coefficient},
        "ventilated": ventilated,
        "deformation": {
            "highest_air_c_without_deformation": max(clean) if clean else None,
            "lowest_air_c_with_deformation": min(deformed) if deformed else None,
        },
        "sources": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path, _ in trials
        ],
        "history": history,
    }


def write_thermal_profile(profile: dict[str, Any], path: Path) -> Path:
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
class ThermalProfile:
    """A loaded profile and the reference a build records for it."""

    path: Path
    payload: dict[str, Any]

    @property
    def coefficient_w_m2k(self) -> float:
        return float(self.payload["figures"]["convection_w_m2k"]["mean"])

    @property
    def samples(self) -> int:
        return int(self.payload["figures"]["convection_w_m2k"]["samples"])

    @property
    def spread_w_m2k(self) -> float:
        return float(self.payload["figures"]["convection_w_m2k"]["spread"])

    def describe(self) -> str:
        """Where a coefficient from this profile came from, for the estimate."""

        return (
            f"profile {self.payload['profile_id']} v{self.payload['version']}: "
            f"{self.samples} closed-box trials, spread {self.spread_w_m2k:.1f} W/m2K"
        )

    def reference(self) -> dict[str, Any]:
        return {
            "profile_id": self.payload["profile_id"],
            "version": self.payload["version"],
            "path": str(self.path),
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
        }


def load_thermal_profile(path: Path) -> ThermalProfile:
    payload = _read(path)

    if payload.get("schema_version") != THERMAL_SCHEMA_VERSION:
        raise ValueError(f"Unsupported thermal profile schema in {path}")

    coefficient = payload.get("figures", {}).get("convection_w_m2k")

    if not coefficient or float(coefficient.get("mean", 0)) <= 0:
        raise ValueError(f"{path} has no positive convection_w_m2k figure")

    return ThermalProfile(path=path, payload=payload)
