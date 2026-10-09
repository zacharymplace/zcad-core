"""Record print-day fit trials from the Fixture Fit Trials checklist.

The checklist page saves one answer document per print: its checks, its
measurements, a disposition, and notes. Export them (Claude does this with
the page's database, one ``<id>.json`` per print) and this script records
each finished one:

- a Validation Lab fixture: writes the trial's ``observations.json`` and
  ``measurements.json`` (dropping anything not measured), then runs
  ``zcad-validation trial complete`` and ``trial register``, taking the
  printer, material, and slicer from the pending record;
- an enclosure build under ``evidence/enclosures/``: writes the same two
  files in the enclosure trial's form and runs
  ``zcad-validation enclosure trial complete``, or, for a group of boards
  in one enclosure (an ``enclosure-group.json`` build),
  ``zcad-validation enclosure-group trial complete``;
- a calibration coupon under ``evidence/coupons/``: writes the same two
  files and runs ``zcad-validation coupon trial complete``. A coupon has no
  verdict: answered ``measured``, its readings are recorded; answered
  ``fail``, it did not print, so there is nothing to record;
- a Gridfinity bin or baseplate under ``evidence/gridfinity/``: writes the
  same two files and ``fit.json`` from the answer's ``fit`` (what it was
  fitted with and how it felt), and runs
  ``zcad-validation gridfinity trial complete``. A pass must name what it was
  fitted with;
- a joint coupon under ``evidence/joints/``: writes the trial's
  ``observations.json`` from the answer's checks and the reading of each rung
  in its ``fit`` (``{"readings": {rung: reading}}``: a fit rung's word, or a
  snap rung's readings; a rung not named is skipped), and runs
  ``zcad-validation joint trial complete``. Like a coupon it
  has no verdict: answered ``fail``, it did not print, so there is nothing to
  record.

An answer that is not finished (a check unanswered, no disposition, or no
measurement where one is needed) is skipped with the reason, and a trial
already recorded is never touched. ``--dry-run`` reports the plan and
writes nothing. Back up the evidence afterwards.

Once it has recorded something, it says what the printer and material's
compensation profile would become with the new trials (each figure and the
strain limit, from and to) or why there are not yet enough trials for one. It
does not write the profile, a file this repository tracks: it prints the
command that does, to run in a worktree and land through a pull request.

Usage:
    python scripts/record-print-day.py <answers-directory> \\
        [--evidence-root evidence] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from zcad_core.cli import main as zcad
from zcad_core.profiles import derive_compensation_profile
from zcad_core.profiles.compensation import FIGURES

GIVE_UP = ("reject", "fail")


@dataclass(frozen=True)
class Answer:
    """One print's answers from the checklist."""

    source: Path
    candidate_id: str
    observations: dict[str, dict[str, Any]]
    measurements: dict[str, dict[str, Any]]
    disposition: str
    notes: str
    fit: dict[str, Any]

    @property
    def measured(self) -> dict[str, dict[str, Any]]:
        return {
            name: entry
            for name, entry in self.measurements.items()
            if entry.get("value_mm") is not None
        }

    def unfinished(self) -> str | None:
        """Why this answer cannot be recorded yet, if it cannot."""

        open_checks = [
            check
            for check, entry in self.observations.items()
            if entry.get("passed") is None
        ]

        if open_checks:
            return f"unanswered checks: {', '.join(open_checks)}"

        if not self.disposition:
            return "no disposition"

        failed = [
            check for check, entry in self.observations.items() if not entry["passed"]
        ]

        if self.disposition == "pass" and failed:
            return f"a pass with failed checks: {', '.join(failed)}"

        if self.disposition not in GIVE_UP and not self.measured:
            return f"a {self.disposition} needs at least one measurement"

        return None


def read_answers(directory: Path) -> list[Answer]:
    answers = []

    for path in sorted(directory.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        answers.append(
            Answer(
                source=path,
                candidate_id=str(payload["candidate_id"]),
                observations=dict(payload.get("observations", {})),
                measurements=dict(payload.get("measurements", {})),
                disposition=str(payload.get("disposition", "")),
                notes=str(payload.get("operator_notes", "")),
                fit=dict(payload.get("fit") or {}),
            )
        )

    return answers


def find_print(evidence_root: Path, candidate_id: str) -> tuple[str, Path]:
    """Whether a candidate id names an enclosure, a group enclosure, a
    calibration coupon, a Gridfinity part, or a fixture, and where."""

    coupon = evidence_root / "coupons" / candidate_id

    if (coupon / "coupon.json").is_file():
        return "coupon", coupon

    enclosure = evidence_root / "enclosures" / candidate_id

    if (enclosure / "enclosure.json").is_file():
        return "enclosure", enclosure

    if (enclosure / "enclosure-group.json").is_file():
        return "group", enclosure

    joint = evidence_root / "joints" / candidate_id

    if (joint / "joint-coupon.json").is_file():
        return "joint", joint

    gridfinity = evidence_root / "gridfinity" / candidate_id

    if (gridfinity / "gridfinity.json").is_file():
        return "gridfinity", gridfinity

    for manifest in evidence_root.glob("*/validation-lab/candidates/*/candidate.json"):
        if json.loads(manifest.read_text(encoding="utf-8")).get("candidate_id") == (
            candidate_id
        ):
            return "fixture", manifest.parent

    raise FileNotFoundError(f"No fixture candidate or enclosure named {candidate_id}")


def _run(arguments: list[str]) -> dict[str, Any]:
    output = StringIO()

    with redirect_stdout(output):
        code = zcad(arguments)

    if code != 0:
        raise RuntimeError(f"zcad-validation {' '.join(arguments[:3])} failed")

    result: dict[str, Any] = json.loads(output.getvalue())

    return result


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_fixture(answer: Answer, candidate: Path) -> dict[str, Any]:
    trial = candidate / "trials" / "trial-001"
    pending = json.loads((trial / "physical-validation.json").read_text("utf-8"))
    _write(trial / "observations.json", answer.observations)
    _write(trial / "measurements.json", answer.measured)
    completed = _run(
        [
            "trial",
            "complete",
            "--candidate-report",
            str(candidate / "automated-validation.json"),
            "--fixture-stl",
            str(candidate / "fixture.stl"),
            "--printer-profile",
            pending["printer_profile"],
            "--material-profile",
            pending["material_profile"],
            "--slicer-profile",
            pending["slicer_profile"],
            "--observations",
            str(trial / "observations.json"),
            "--measurements",
            str(trial / "measurements.json"),
            "--disposition",
            answer.disposition,
            "--operator-notes",
            answer.notes,
            "--output",
            str(trial / "physical-validation.json"),
        ]
    )
    registered = _run(
        [
            "trial",
            "register",
            "--candidate-manifest",
            str(candidate / "candidate.json"),
            "--physical-validation-record",
            str(trial / "physical-validation.json"),
            "--fixture",
            str(candidate / "fixture.stl"),
            "--trial-id",
            "trial-001",
            "--output",
            str(trial / "trial.json"),
        ]
    )

    return {"passed": completed["passed"], "manifest": registered["manifest"]}


def record_enclosure(
    answer: Answer, build: Path, command: str = "enclosure"
) -> dict[str, Any]:
    """Record an enclosure trial; ``command`` is ``enclosure-group`` for a group,
    whose trial takes the same observations and measurements."""

    trial = build / "trials" / "trial-001"
    _write(
        trial / "observations.json",
        {
            check: {
                "result": "pass" if entry["passed"] else "fail",
                "notes": entry.get("notes", ""),
            }
            for check, entry in answer.observations.items()
        },
    )
    _write(trial / "measurements.json", answer.measured)
    completed = _run(
        [
            command,
            "trial",
            "complete",
            "--trial-directory",
            str(trial),
            "--disposition",
            answer.disposition,
            "--notes",
            answer.notes,
        ]
    )

    return {"trial_record": completed["trial_record"]}


def record_coupon(answer: Answer, build: Path) -> dict[str, Any]:
    """Record a coupon trial: its two checks and every feature measured."""

    trial = build / "trials" / "trial-001"
    _write(
        trial / "observations.json",
        {
            check: {
                "result": "pass" if entry["passed"] else "fail",
                "notes": entry.get("notes", ""),
            }
            for check, entry in answer.observations.items()
        },
    )
    _write(trial / "measurements.json", answer.measured)
    completed = _run(
        [
            "coupon",
            "trial",
            "complete",
            "--trial-directory",
            str(trial),
            "--notes",
            answer.notes,
        ]
    )

    return {"trial_record": completed["trial_record"]}


def record_gridfinity(answer: Answer, build: Path) -> dict[str, Any]:
    """Record a Gridfinity trial: its checks, its measurements, and what it
    was fitted with, over the trial's own fit template."""

    trial = build / "trials" / "trial-001"
    _write(
        trial / "observations.json",
        {
            check: {
                "result": "pass" if entry["passed"] else "fail",
                "notes": entry.get("notes", ""),
            }
            for check, entry in answer.observations.items()
        },
    )
    _write(trial / "measurements.json", answer.measured)
    fit = json.loads((trial / "fit.json").read_text(encoding="utf-8"))
    _write(trial / "fit.json", {**fit, **answer.fit})
    completed = _run(
        [
            "gridfinity",
            "trial",
            "complete",
            "--trial-directory",
            str(trial),
            "--disposition",
            answer.disposition,
            "--notes",
            answer.notes,
        ]
    )

    return {
        "trial_record": completed["trial_record"],
        "verification": completed["verification"],
    }


def record_joint(answer: Answer, build: Path) -> dict[str, Any]:
    """Record a joint coupon trial: its two checks and how each rung read,
    over the trial's own template."""

    trial = build / "trials" / "trial-001"
    observations = json.loads((trial / "observations.json").read_text("utf-8"))
    readings = dict(answer.fit.get("readings") or {})

    for name, entry in observations.items():
        if "reading" in entry:
            entry["reading"] = readings.get(name, "skipped")
        elif name in answer.observations:
            given = answer.observations[name]
            entry["result"] = "pass" if given["passed"] else "fail"
            entry["notes"] = given.get("notes", "")

    _write(trial / "observations.json", observations)
    completed = _run(
        [
            "joint",
            "trial",
            "complete",
            "--trial-directory",
            str(trial),
            "--notes",
            answer.notes,
        ]
    )

    return {"trial_record": completed["trial_record"]}


def joint_unfinished(answer: Answer) -> str | None:
    """Why a joint coupon's answer cannot be recorded yet: it is judged by its
    readings, not by measurements or a verdict."""

    open_checks = [
        check
        for check, entry in answer.observations.items()
        if entry.get("passed") is None
    ]

    if open_checks:
        return f"unanswered checks: {', '.join(open_checks)}"

    if answer.disposition in GIVE_UP:
        return "the coupon did not print, so it has nothing to record; print another"

    if not answer.fit.get("readings"):
        return "a joint coupon needs at least one rung read"

    return None


def recorded(kind: str, location: Path) -> bool:
    trial = location / "trials" / "trial-001"

    if kind == "enclosure":
        return (trial / "enclosure-trial.json").is_file()

    if kind == "group":
        return (trial / "enclosure-group-trial.json").is_file()

    if kind == "coupon":
        return (trial / "calibration-coupon-trial.json").is_file()

    if kind == "gridfinity":
        return (trial / "gridfinity-trial.json").is_file()

    if kind == "joint":
        return (trial / "joint-coupon-trial.json").is_file()

    return (trial / "trial.json").is_file()


def plan(answer: Answer, evidence_root: Path) -> tuple[str, str, Path | None]:
    """What to do with one answer: record it, or why not."""

    kind, location = find_print(evidence_root, answer.candidate_id)

    if recorded(kind, location):
        return kind, "already recorded", location

    reason = joint_unfinished(answer) if kind == "joint" else answer.unfinished()

    if reason is None and kind == "coupon" and answer.disposition in GIVE_UP:
        reason = "the coupon did not print, so it has nothing to record; print another"

    if (
        reason is None
        and kind == "gridfinity"
        and answer.disposition == "pass"
        and not (answer.fit.get("mated_with") or {}).get("made_by")
    ):
        reason = "a pass must name what the part was fitted with"

    return kind, (f"skip: {reason}" if reason else "record"), location


def _figure_mean(profile: dict[str, Any] | None, figure: str) -> float | None:
    entry = (profile or {}).get("figures", {}).get(figure)

    return None if entry is None else float(entry["mean_mm"])


def _strain_value(profile: dict[str, Any] | None) -> float | None:
    entry = (profile or {}).get("strain_limit")

    return None if not entry else entry.get("value")


def profile_preview(
    evidence_root: Path,
    *,
    printer_profile_id: str,
    material_profile_id: str,
    profile_path: Path,
) -> dict[str, Any]:
    """What the compensation profile would become with every recorded trial,
    against what it is now; nothing is written."""

    current = (
        json.loads(profile_path.read_text(encoding="utf-8"))
        if profile_path.exists()
        else None
    )

    try:
        derived = derive_compensation_profile(
            evidence_root,
            printer_profile_id=printer_profile_id,
            material_profile_id=material_profile_id,
            previous=current,
        )
    except ValueError as error:
        return {"ready": False, "reason": str(error)}

    changes: dict[str, dict[str, float | None]] = {
        figure: {
            "from": _figure_mean(current, figure),
            "to": _figure_mean(derived, figure),
        }
        for figure in FIGURES
    }
    changes["strain_limit"] = {
        "from": _strain_value(current),
        "to": _strain_value(derived),
    }

    return {
        "ready": True,
        "profile": str(profile_path),
        "version": derived["version"],
        "trials": len(derived["sources"]),
        "changes": {
            name: change
            for name, change in changes.items()
            if change["from"] != change["to"]
        },
        "write_with": (
            "zcad-validation compensation derive --printer-profile-id "
            f"{printer_profile_id} --material-profile-id {material_profile_id}"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("answers", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--printer-profile-id", default="bambu-lab-a1-mini")
    parser.add_argument("--material-profile-id", default="petg")
    parser.add_argument(
        "--compensation-profile",
        type=Path,
        help="the profile to compare with; defaults to profiles/compensation/<printer>-<material>.json",
    )
    args = parser.parse_args()
    report = []

    for answer in read_answers(args.answers):
        kind, action, location = plan(answer, args.evidence_root)
        entry: dict[str, Any] = {
            "print": answer.candidate_id,
            "kind": kind,
            "action": action,
        }

        if action == "record" and not args.dry_run and location is not None:
            if kind == "fixture":
                entry["result"] = record_fixture(answer, location)
            elif kind == "coupon":
                entry["result"] = record_coupon(answer, location)
            elif kind == "gridfinity":
                entry["result"] = record_gridfinity(answer, location)
            elif kind == "joint":
                entry["result"] = record_joint(answer, location)
            else:
                entry["result"] = record_enclosure(
                    answer,
                    location,
                    "enclosure-group" if kind == "group" else "enclosure",
                )

        report.append(entry)

    print(json.dumps(report, indent=2))

    if not args.dry_run and any("result" in entry for entry in report):
        print("Now back up the evidence: scripts/backup-evidence.sh")
        preview = profile_preview(
            args.evidence_root,
            printer_profile_id=args.printer_profile_id,
            material_profile_id=args.material_profile_id,
            profile_path=args.compensation_profile
            or Path("profiles/compensation")
            / f"{args.printer_profile_id}-{args.material_profile_id}.json",
        )
        print(json.dumps({"compensation_profile": preview}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
