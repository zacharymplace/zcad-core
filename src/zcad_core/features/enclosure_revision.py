"""Turn a completed enclosure trial into revised design settings.

A trial measures the intended sizes of an enclosure's holes and openings,
so the printer's shortfall on them is measured directly: the mean of
intended minus measured, over the insert pockets and lid screw holes, is
added to ``hole_compensation_mm``, which widens every hole and opening in
the model by that much. A cable that would not plug in widens the cable
opening's plug allowance. Failed checks no setting can fix become notes on
what to look at, and a base that printed the wrong size is reported as a
printer calibration problem rather than scaled away.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.features.enclosure import HOLE_COMPENSATION_RANGE_MM
from zcad_core.features.enclosure_trial import BUILD_RECORD, TRIAL_RECORD

HOLE_MEASUREMENTS = ("insert_pocket_diameter_mm", "lid_hole_diameter_mm")
OUTER_MEASUREMENTS = ("base_outer_width_mm", "base_outer_depth_mm", "base_height_mm")
# Shortfalls smaller than this are within caliper and print noise.
NOISE_MM = 0.05
# Scale errors larger than this are worth a printer calibration.
SCALE_TOLERANCE = 0.005
PLUG_STEP_MM = 1.0

FAILED_CHECK_GUIDANCE = {
    "parts_printed_cleanly": (
        "The print itself failed or warped: look at the slicer and printer "
        "settings (bed adhesion, temperature) before the design."
    ),
    "inserts_installed": (
        "Inserts went in crooked or proud. Hole compensation fixes undersized "
        "pockets; if the pockets measured true, go slower with the iron."
    ),
    "lid_closes_flush": (
        "The lid does not close flat. Reseat any insert standing proud of its "
        "boss, and check the lid and rim for warping."
    ),
    "board_seats": (
        "The board does not sit level. Look for a part under it touching the "
        "floor or a support; raising bottom_clearance_mm lifts the board."
    ),
    "board_retained": (
        "The board is loose. On standoffs, use screws that bite the standoff "
        "holes; in a cradle, the clip fit is not a design setting yet, so "
        "record how much play there is."
    ),
    "access_openings_clear": (
        "An opening does not reach its part. Record which side it misses on; "
        "the board's part data may be off."
    ),
    "display_aligned": (
        "The window covers some pixels. Record which edge; the display's "
        "active-area offset in its spec may be wrong."
    ),
    "display_retained": (
        "The display is loose. On posts, use screws that bite the pilot holes "
        "(hole compensation widens them too); with clips, record the play."
    ),
    "nothing_rattles": (
        "Something moves. Find it: a loose board or display has its own check above."
    ),
}


@dataclass(frozen=True)
class DesignChange:
    """One setting a revision changes, and why."""

    setting: str
    current: float
    proposed: float
    reason: str


@dataclass(frozen=True)
class EnclosureRevision:
    """What a trial says to change, and the design with those changes."""

    trial_directory: Path
    build_record_path: Path
    build_record: dict[str, Any]
    trial: dict[str, Any]
    changes: tuple[DesignChange, ...]
    notes: tuple[str, ...]

    @property
    def design(self) -> dict[str, Any]:
        """The build's design settings with the changes applied."""
        design = dict(self.build_record["design"])

        for change in self.changes:
            design[change.setting] = change.proposed

        return design

    def summary(self) -> dict[str, Any]:
        return {
            "trial": self.trial["trial_id"],
            "disposition": self.trial["disposition"],
            "build_record": str(self.build_record_path),
            "changes": [
                {
                    "setting": change.setting,
                    "current": change.current,
                    "proposed": change.proposed,
                    "reason": change.reason,
                }
                for change in self.changes
            ],
            "notes": list(self.notes),
        }


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def _hole_change(
    design: dict[str, Any], measured: dict[str, dict[str, Any]]
) -> DesignChange | None:
    shortfalls = {
        name: measured[name]["nominal_mm"] - measured[name]["value_mm"]
        for name in HOLE_MEASUREMENTS
        if name in measured and measured[name].get("nominal_mm") is not None
    }

    if not shortfalls:
        return None

    mean = sum(shortfalls.values()) / len(shortfalls)

    if abs(mean) < NOISE_MM:
        return None

    current = float(design.get("hole_compensation_mm", 0.0))
    low, high = HOLE_COMPENSATION_RANGE_MM
    proposed = round(min(max(current + mean, low), high), 2)

    if proposed == current:
        return None

    rendered = ", ".join(
        f"{name.removesuffix('_mm')} {'short' if value > 0 else 'over'} by "
        f"{abs(value):.2f} mm"
        for name, value in shortfalls.items()
    )

    return DesignChange(
        setting="hole_compensation_mm",
        current=current,
        proposed=proposed,
        reason=f"Holes printed {'small' if mean > 0 else 'large'}: {rendered}.",
    )


def _plug_changes(design: dict[str, Any]) -> list[DesignChange]:
    return [
        DesignChange(
            setting=setting,
            current=float(design[setting]),
            proposed=round(float(design[setting]) + PLUG_STEP_MM, 2),
            reason=(
                "The cable would not plug in; widen the opening's plug "
                f"allowance by {PLUG_STEP_MM} mm."
            ),
        )
        for setting in ("cable_plug_width_mm", "cable_plug_height_mm")
    ]


def _scale_notes(measured: dict[str, dict[str, Any]]) -> list[str]:
    notes = []

    for name in OUTER_MEASUREMENTS:
        entry = measured.get(name)

        if not entry or not entry.get("nominal_mm"):
            continue

        error = (entry["value_mm"] - entry["nominal_mm"]) / entry["nominal_mm"]

        if abs(error) > SCALE_TOLERANCE:
            notes.append(
                f"{name.removesuffix('_mm')} printed {abs(error):.1%} "
                f"{'large' if error > 0 else 'small'}: calibrate the printer's "
                "steps or the filament's shrinkage; this revision does not "
                "scale the design."
            )

    return notes


def propose_revision(trial_directory: Path) -> EnclosureRevision:
    """Read a completed trial and propose the next design."""

    trial_path = trial_directory / TRIAL_RECORD

    if not trial_path.is_file():
        raise FileNotFoundError(
            f"No completed trial at {trial_path}; run enclosure trial complete"
        )

    trial = _read(trial_path)
    build_path = trial_directory.parent.parent / BUILD_RECORD
    digest = hashlib.sha256(build_path.read_bytes()).hexdigest()

    if digest != trial["build_record_sha256"]:
        raise ValueError(f"The build record changed after the trial: {build_path}")

    build = _read(build_path)
    design = build["design"]
    measured = {entry["name"]: entry for entry in trial["measurements"]}
    changes: list[DesignChange] = []
    hole = _hole_change(design, measured)

    if hole is not None:
        changes.append(hole)

    failed = list(trial["failed_checks"])

    if "cable_plugs_in" in failed:
        changes.extend(_plug_changes(design))

    notes = [
        f"{check}: {FAILED_CHECK_GUIDANCE[check]}"
        for check in failed
        if check in FAILED_CHECK_GUIDANCE
    ]
    notes.extend(_scale_notes(measured))

    if not changes and not notes:
        notes.append("The trial found nothing to change.")

    return EnclosureRevision(
        trial_directory=trial_directory,
        build_record_path=build_path,
        build_record=build,
        trial=trial,
        changes=tuple(changes),
        notes=tuple(notes),
    )


def revised_name(design_name: str) -> str:
    """The next revision's name: ``case`` becomes ``case-r2``, ``case-r2``
    becomes ``case-r3``."""

    stem, _, suffix = design_name.rpartition("-r")

    if stem and suffix.isdigit():
        return f"{stem}-r{int(suffix) + 1}"

    return f"{design_name}-r2"
