"""Joint profiles: the fits a printer and material actually give, from joint coupons.

A joint coupon (:mod:`zcad_core.features.joint_coupon`) sweeps the figure that
decides a joint across a ladder of rungs, and its trial records how each rung
felt. A joint profile picks a rung for each figure by a rule written down here,
and the rule must hold in every trial; readings are never averaged.

The fit coupon's rungs are round holes, each sized as the products size a hole
for a metal part: the part's diameter, the clearance each side, and the printer
profile's ``hole_oversize``. A metal reference is pushed into each, in a layer
(a hole whose axis is vertical) and across layers (a hole through a standing
wall). Its figures, read the same way by every product that takes a printer
profile's fits:

- ``sliding_clearance_per_side``: the smallest rung that slides, in both
  orientations, in every trial;
- ``press_fit_clearance_per_side``: the largest rung that is still a press, in
  both orientations, in every trial.

Where no rung meets a rule the figure is left out, with the reason, and the
printer profile's own figure stands. Two distinct trials are needed. A rung
measured with one ``hole_oversize`` says nothing about holes built with
another, so the trials must agree on it, the profile records it, and a build
whose printer profile has changed it is refused the profile.

A build applies a profile for one command (:func:`measured_fits`), as a
compensation profile's strain limit is applied; without one, nothing changes.
Profiles live in ``profiles/joints/<printer>-<material>.json`` and move only to
the next version, keeping the previous figures in their history.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zcad_core.profiles.trial_records import distinct_trial_records

JOINT_PROFILE_SCHEMA_VERSION = "1.0.0"
JOINT_TRIAL_RECORD = "joint-coupon-trial.json"
DEFAULT_MINIMUM_TRIALS = 2
ORIENTATIONS = ("in_layer", "across_layers")
# How a rung felt, from tightest to loosest; skipped rungs are left out of a trial.
FIT_READINGS = ("wont_go", "press", "slides", "loose")
SLIDING = "sliding_clearance_per_side"
PRESS_FIT = "press_fit_clearance_per_side"
RULES = {
    SLIDING: "the smallest rung that slides, in both orientations, in every trial",
    PRESS_FIT: "the largest rung that is still a press, in both orientations, in every trial",
}


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def fit_trials(
    evidence_root: Path, *, printer_profile_id: str, material_profile_id: str
) -> list[tuple[Path, dict[str, Any]]]:
    """Every fit coupon trial for this printer and material, each counted once."""

    return [
        (path, record)
        for path, record in distinct_trial_records(evidence_root, JOINT_TRIAL_RECORD)
        if record.get("family") == "fit"
        and record.get("printer_profile_id") == printer_profile_id
        and record.get("material_profile_id") == material_profile_id
    ]


def _rung_holds(trials: list[dict[str, Any]], clearance: float, reading: str) -> bool:
    """Whether every trial read ``reading`` at this clearance in both orientations."""

    for trial in trials:
        for orientation in ORIENTATIONS:
            felt = [
                entry["reading"]
                for entry in trial["readings"]
                if entry["orientation"] == orientation
                and abs(entry["clearance_per_side_mm"] - clearance) < 1e-9
            ]

            if not felt or any(value != reading for value in felt):
                return False

    return True


def choose_fits(trials: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each fit figure's rung by its rule, or why there is none."""

    clearances = sorted(
        {
            float(entry["clearance_per_side_mm"])
            for trial in trials
            for entry in trial["readings"]
        }
    )
    sliding = [c for c in clearances if _rung_holds(trials, c, "slides")]
    pressed = [c for c in clearances if _rung_holds(trials, c, "press")]
    chosen = {
        SLIDING: min(sliding) if sliding else None,
        PRESS_FIT: max(pressed) if pressed else None,
    }
    figures: dict[str, dict[str, Any]] = {}

    for figure, value in chosen.items():
        if value is None:
            figures[figure] = {
                "value_mm": None,
                "rule": RULES[figure],
                "reason": "no rung meets the rule in every trial; the printer profile's figure stands",
            }
        else:
            figures[figure] = {"value_mm": value, "rule": RULES[figure]}

    slide, press = chosen[SLIDING], chosen[PRESS_FIT]

    if slide is not None and press is not None and press >= slide:
        raise ValueError(
            f"The trials put a press at {press:g} mm, at or above a slide at "
            f"{slide:g} mm; check the readings before deriving a profile"
        )

    return figures


def derive_joint_profile(
    evidence_root: Path,
    *,
    printer_profile_id: str,
    material_profile_id: str,
    minimum_trials: int = DEFAULT_MINIMUM_TRIALS,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Choose each fit figure from the recorded trials, as the next version of a
    profile."""

    found = fit_trials(
        evidence_root,
        printer_profile_id=printer_profile_id,
        material_profile_id=material_profile_id,
    )

    if len(found) < minimum_trials:
        raise ValueError(
            f"{len(found)} fit coupon trial(s) for {printer_profile_id} with "
            f"{material_profile_id}; a joint profile needs at least {minimum_trials}"
        )

    oversizes = {float(record["hole_oversize_mm"]) for _, record in found}

    if len(oversizes) > 1:
        raise ValueError(
            "The fit coupon trials were built with different hole_oversize figures "
            f"({', '.join(f'{value:g}' for value in sorted(oversizes))} mm); a rung "
            "measured with one says nothing about the other"
        )

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
        "schema_version": JOINT_PROFILE_SCHEMA_VERSION,
        "profile_id": f"{printer_profile_id}-{material_profile_id}",
        "printer_profile_id": printer_profile_id,
        "material_profile_id": material_profile_id,
        "version": (previous["version"] + 1) if previous else 1,
        "derived_at_utc": datetime.now(UTC).isoformat(),
        "hole_oversize_mm": oversizes.pop(),
        "generator_versions": sorted(
            {str(record["generator_version"]) for _, record in found}
        ),
        "figures": choose_fits([record for _, record in found]),
        "sources": [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path, _ in found
        ],
        "history": history,
    }


def write_joint_profile(profile: dict[str, Any], path: Path) -> Path:
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
class JointProfile:
    """A loaded profile and the reference a build records for it."""

    path: Path
    payload: dict[str, Any]

    @property
    def hole_oversize_mm(self) -> float:
        return float(self.payload["hole_oversize_mm"])

    def fits(self) -> dict[str, float]:
        """The figures the profile measured; one it could not choose is left out."""

        return {
            figure: float(entry["value_mm"])
            for figure, entry in self.payload["figures"].items()
            if entry.get("value_mm") is not None
        }

    def reference(self) -> dict[str, Any]:
        return {
            "profile_id": self.payload["profile_id"],
            "version": self.payload["version"],
            "path": str(self.path),
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "fits_mm": self.fits(),
        }


def load_joint_profile(path: Path) -> JointProfile:
    payload = _read(path)

    if payload.get("schema_version") != JOINT_PROFILE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported joint profile schema in {path}")

    return JointProfile(path=path, payload=payload)


_MEASURED: ContextVar[JointProfile | None] = ContextVar("joint_profile", default=None)


def applied_joint_profile() -> JointProfile | None:
    """The joint profile this command applies, if it was given one."""

    return _MEASURED.get()


@contextmanager
def measured_fits(profile: JointProfile) -> Iterator[JointProfile]:
    """Build with a joint profile's fits for the length of one command. A build
    opts in by passing a profile; nothing changes for one that does not."""

    token = _MEASURED.set(profile)

    try:
        yield profile
    finally:
        _MEASURED.reset(token)


def fits_for(given: dict[str, float]) -> dict[str, float]:
    """A printer profile's fits with the applied joint profile's in their place.

    Refused when the printer profile's ``hole_oversize`` is not the one the
    profile's rungs were built with: its fits were measured on other holes."""

    profile = applied_joint_profile()

    if profile is None:
        return given

    oversize = given.get("hole_oversize")

    if oversize is not None and abs(oversize - profile.hole_oversize_mm) > 1e-9:
        raise ValueError(
            f"The joint profile {profile.path} was measured on holes built with "
            f"hole_oversize {profile.hole_oversize_mm:g} mm, but the printer profile "
            f"now says {oversize:g} mm; print a new fit coupon or build without "
            "--joint-profile"
        )

    return {**given, **profile.fits()}
