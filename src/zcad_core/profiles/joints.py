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

The snap coupon's rungs are drawer detents built at engagements from 0.3 to
0.6 mm, each tried for whether it clicks shut, holds a shake, lets go by hand and
whitens. Its figure is read by every stack build with a drawer detent or stop:

- ``detent_engagement_mm``: the smallest rung that clicks shut, holds, lets go
  and does not whiten, in every trial.

Where no rung meets a rule the figure is left out, with the reason, and the
engine's own figure stands. Each family needs two distinct trials of its own; a
family with fewer is left out of the profile, and one with none of either is
refused. A fit rung measured with one ``hole_oversize`` says nothing about holes
built with another, and a detent's tongue is sized from the strain limit, so a
rung measured at one limit says nothing about a tongue sized for another: the
trials of a family must agree on theirs, the profile records it, and a build
whose figure has since changed is refused the profile.

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

JOINT_PROFILE_SCHEMA_VERSION = "1.1.0"
JOINT_TRIAL_RECORD = "joint-coupon-trial.json"
DEFAULT_MINIMUM_TRIALS = 2
ORIENTATIONS = ("in_layer", "across_layers")
# How a rung felt, from tightest to loosest; skipped rungs are left out of a trial.
FIT_READINGS = ("wont_go", "press", "slides", "loose")
SLIDING = "sliding_clearance_per_side"
PRESS_FIT = "press_fit_clearance_per_side"
DETENT = "detent_engagement_mm"
# What a snap rung is tried for; every one is true or false, and a holding rung is
# one that clicks shut, holds and lets go, and has not whitened.
SNAP_READINGS = ("clicks_shut", "holds_shake", "lets_go", "whitened")
RULES = {
    SLIDING: "the smallest rung that slides, in both orientations, in every trial",
    PRESS_FIT: "the largest rung that is still a press, in both orientations, in every trial",
    DETENT: (
        "the smallest rung that clicks shut, holds a shake, lets go by hand and does "
        "not whiten, in every trial"
    ),
}
NO_RUNG = "no rung meets the rule in every trial; the engine's own figure stands"
NO_FIT = "no rung meets the rule in every trial; the printer profile's figure stands"


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def family_trials(
    evidence_root: Path,
    family: str,
    *,
    printer_profile_id: str,
    material_profile_id: str,
) -> list[tuple[Path, dict[str, Any]]]:
    """Every joint coupon trial of one family for this printer and material, each
    counted once."""

    return [
        (path, record)
        for path, record in distinct_trial_records(evidence_root, JOINT_TRIAL_RECORD)
        if record.get("family") == family
        and record.get("printer_profile_id") == printer_profile_id
        and record.get("material_profile_id") == material_profile_id
    ]


def fit_trials(
    evidence_root: Path, *, printer_profile_id: str, material_profile_id: str
) -> list[tuple[Path, dict[str, Any]]]:
    """Every fit coupon trial for this printer and material, each counted once."""

    return family_trials(
        evidence_root,
        "fit",
        printer_profile_id=printer_profile_id,
        material_profile_id=material_profile_id,
    )


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
                "reason": NO_FIT,
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


def _holds(reading: dict[str, Any]) -> bool:
    return (
        reading["clicks_shut"]
        and reading["holds_shake"]
        and reading["lets_go"]
        and not reading["whitened"]
    )


def choose_detent(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """The detent's engagement by its rule, or why there is none."""

    engagements = sorted(
        {
            float(entry["engagement_mm"])
            for trial in trials
            for entry in trial["readings"]
        }
    )

    for engagement in engagements:
        if all(
            any(
                abs(entry["engagement_mm"] - engagement) < 1e-9 and _holds(entry)
                for entry in trial["readings"]
            )
            for trial in trials
        ):
            return {"value_mm": engagement, "rule": RULES[DETENT]}

    return {"value_mm": None, "rule": RULES[DETENT], "reason": NO_RUNG}


def _agreed(found: list[tuple[Path, dict[str, Any]]], field: str, what: str) -> float:
    """The one value of ``field`` every trial of a family was built with."""

    values = {float(record[field]) for _, record in found}

    if len(values) > 1:
        raise ValueError(
            f"The {what} trials were built with different {field} figures "
            f"({', '.join(f'{value:g}' for value in sorted(values))}); a rung measured "
            "with one says nothing about the other"
        )

    return values.pop()


def derive_joint_profile(
    evidence_root: Path,
    *,
    printer_profile_id: str,
    material_profile_id: str,
    minimum_trials: int = DEFAULT_MINIMUM_TRIALS,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Choose each figure from the recorded trials of each family that has enough,
    as the next version of a profile."""

    families = {
        family: family_trials(
            evidence_root,
            family,
            printer_profile_id=printer_profile_id,
            material_profile_id=material_profile_id,
        )
        for family in ("fit", "snap")
    }
    ready = {
        family: found
        for family, found in families.items()
        if len(found) >= minimum_trials
    }

    if not ready:
        counts = ", ".join(
            f"{len(found)} {family}" for family, found in families.items()
        )
        raise ValueError(
            f"Joint coupon trials for {printer_profile_id} with {material_profile_id}: "
            f"{counts}; a joint profile needs at least {minimum_trials} of one family"
        )

    figures: dict[str, dict[str, Any]] = {}
    oversize = strain_limit = None

    if "fit" in ready:
        oversize = _agreed(ready["fit"], "hole_oversize_mm", "fit coupon")
        figures.update(choose_fits([record for _, record in ready["fit"]]))

    if "snap" in ready:
        strain_limit = _agreed(ready["snap"], "strain_limit", "snap coupon")
        figures[DETENT] = choose_detent([record for _, record in ready["snap"]])

    used = [entry for found in ready.values() for entry in found]
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
        "hole_oversize_mm": oversize,
        "strain_limit": strain_limit,
        "families": {
            family: (
                f"{len(found)} trial(s)"
                if family in ready
                else f"{len(found)} trial(s), {minimum_trials} needed: left out"
            )
            for family, found in families.items()
        },
        "generator_versions": sorted(
            {str(record["generator_version"]) for _, record in used}
        ),
        "figures": figures,
        "sources": [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path, _ in used
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
    def hole_oversize_mm(self) -> float | None:
        value = self.payload.get("hole_oversize_mm")

        return None if value is None else float(value)

    @property
    def strain_limit(self) -> float | None:
        value = self.payload.get("strain_limit")

        return None if value is None else float(value)

    def _measured(self, figure: str) -> float | None:
        entry = self.payload["figures"].get(figure) or {}
        value = entry.get("value_mm")

        return None if value is None else float(value)

    def fits(self) -> dict[str, float]:
        """The clearances the profile measured; one it could not choose is left out."""

        return {
            figure: value
            for figure in (SLIDING, PRESS_FIT)
            if (value := self._measured(figure)) is not None
        }

    def detent_engagement_mm(self) -> float | None:
        """The detent's measured engagement, or None when the profile has none."""

        return self._measured(DETENT)

    def reference(self) -> dict[str, Any]:
        return {
            "profile_id": self.payload["profile_id"],
            "version": self.payload["version"],
            "path": str(self.path),
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "fits_mm": self.fits(),
            "detent_engagement_mm": self.detent_engagement_mm(),
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

    fits = profile.fits()

    if not fits:
        return given

    oversize = given.get("hole_oversize")
    measured_on = profile.hole_oversize_mm

    if (
        oversize is not None
        and measured_on is not None
        and abs(oversize - measured_on) > 1e-9
    ):
        raise ValueError(
            f"The joint profile {profile.path} was measured on holes built with "
            f"hole_oversize {measured_on:g} mm, but the printer profile "
            f"now says {oversize:g} mm; print a new fit coupon or build without "
            "--joint-profile"
        )

    return {**given, **fits}


def measured_detent_engagement(strain_limit: float) -> float | None:
    """The applied joint profile's detent engagement, for a build held to
    ``strain_limit``; None when no profile is applied or it has none.

    Refused when the build's strain limit is not the one the profile's rungs were
    built at: their tongues were sized for another."""

    profile = applied_joint_profile()
    engagement = None if profile is None else profile.detent_engagement_mm()

    if profile is None or engagement is None:
        return None

    measured_at = profile.strain_limit

    if measured_at is not None and abs(measured_at - strain_limit) > 1e-9:
        raise ValueError(
            f"The joint profile {profile.path} measured the detent with tongues sized for "
            f"a strain limit of {100 * measured_at:g} per cent, but this build is held to "
            f"{100 * strain_limit:g} per cent; print a new snap coupon at this limit or "
            "build without --joint-profile"
        )

    return engagement
