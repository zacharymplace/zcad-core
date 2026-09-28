#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from zcad_core.retention import (
    UNRECORDED_SLICER_PROFILE,
    CandidateRevision,
    PhysicalTrialManifest,
    ValidationTarget,
    candidate_identifier,
    sha256_file,
    write_immutable_manifest,
)

ROOT = Path(__file__).resolve().parents[1]

TARGET_ID = "adafruit-feather-rp2040"
REVISION = "r001"
TRIAL_ID = "trial-001"

EVIDENCE_ROOT = ROOT / "evidence" / TARGET_ID

SOURCE_STEP = EVIDENCE_ROOT / "4884 Feather RP2040.step"

AUTOMATED_REPORT = EVIDENCE_ROOT / "feather-rp2040-corner-capture.json"

RETENTION_STEP = EVIDENCE_ROOT / "feather-rp2040-corner-capture.step"

FIXTURE_STL = EVIDENCE_ROOT / "feather-rp2040-physical-validation.stl"

PHYSICAL_RECORD = EVIDENCE_ROOT / "feather-rp2040-physical-validation.json"

LAB_ROOT = EVIDENCE_ROOT / "validation-lab"

TARGET_MANIFEST = LAB_ROOT / "target.json"

CANDIDATE_ROOT = LAB_ROOT / "candidates" / REVISION

CANDIDATE_MANIFEST = CANDIDATE_ROOT / "candidate.json"

TRIAL_ROOT = CANDIDATE_ROOT / "trials" / TRIAL_ID

TRIAL_MANIFEST = TRIAL_ROOT / "trial.json"


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, dict):
        raise TypeError(f"Expected object in {path}")

    return value


def git_commit() -> str:
    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def require_artifacts() -> None:
    required = (
        SOURCE_STEP,
        AUTOMATED_REPORT,
        RETENTION_STEP,
        FIXTURE_STL,
        PHYSICAL_RECORD,
    )

    missing = tuple(path for path in required if not path.is_file())

    if not missing:
        return

    formatted = "\n".join(f"- {path}" for path in missing)

    raise FileNotFoundError(
        f"Required Validation Lab artifacts are missing:\n{formatted}"
    )


def build_target(
    automated: dict[str, object],
) -> ValidationTarget:
    generated_at = str(automated.get("generated_at_utc", "")).strip()

    if not generated_at:
        generated_at = datetime.now(UTC).isoformat()

    source = automated["source"]

    if not isinstance(source, dict):
        raise TypeError("Automated source section must be an object")

    return ValidationTarget(
        schema_version="1.0.0",
        target_id=TARGET_ID,
        display_name="Adafruit Feather RP2040",
        manufacturer="Adafruit",
        product_family="Feather",
        source_model_path=str(SOURCE_STEP.relative_to(ROOT)),
        source_model_sha256=sha256_file(SOURCE_STEP),
        pcb_solid_index=int(source["pcb_solid_index"]),
        created_at_utc=generated_at,
    )


def build_candidate(
    automated: dict[str, object],
    target: ValidationTarget,
) -> CandidateRevision:
    policy = automated["policy"]
    pcb = automated["pcb"]
    selected = automated["selected_corners"]

    if not isinstance(policy, dict):
        raise TypeError("Automated policy must be an object")

    if not isinstance(pcb, dict):
        raise TypeError("Automated PCB section must be an object")

    if not isinstance(selected, list):
        raise TypeError("Selected corners must be a list")

    retention_policy = {str(key): float(value) for key, value in policy.items()}

    derived_parameters = {
        "board_thickness_mm": float(pcb["z_length_mm"]),
        **retention_policy,
    }

    return CandidateRevision(
        schema_version="1.0.0",
        candidate_id=candidate_identifier(
            target_id=TARGET_ID,
            strategy="corner-capture",
            revision=REVISION,
        ),
        target_id=TARGET_ID,
        revision=REVISION,
        source_sha256=target.source_model_sha256,
        output_sha256=sha256_file(RETENTION_STEP),
        git_commit=git_commit(),
        generator_version="1.0.0",
        retention_policy=retention_policy,
        derived_parameters=derived_parameters,
        selected_corners=tuple(str(value) for value in selected),
        automated_decision=str(automated["decision"]),
        automated_evidence_path=str(AUTOMATED_REPORT.relative_to(ROOT)),
        fixture_artifact_path=str(FIXTURE_STL.relative_to(ROOT)),
        created_at_utc=target.created_at_utc,
    )


def build_trial(
    physical: dict[str, object],
    candidate: CandidateRevision,
) -> PhysicalTrialManifest:
    created_at = str(physical.get("completed_at_utc", "")).strip()

    if not created_at:
        created_at = candidate.created_at_utc

    return PhysicalTrialManifest(
        schema_version="1.0.0",
        trial_id=TRIAL_ID,
        candidate_id=candidate.candidate_id,
        physical_validation_path=str(PHYSICAL_RECORD.relative_to(ROOT)),
        fixture_artifact_path=str(FIXTURE_STL.relative_to(ROOT)),
        printer_profile=str(physical["printer_profile"]),
        material_profile=str(physical["material_profile"]),
        slicer_profile=str(physical.get("slicer_profile", UNRECORDED_SLICER_PROFILE)),
        disposition=str(physical["disposition"]),
        complete=bool(physical["complete"]),
        passed=bool(physical["passed"]),
        created_at_utc=created_at,
    )


def main() -> None:
    require_artifacts()

    automated = load_json(AUTOMATED_REPORT)

    physical = load_json(PHYSICAL_RECORD)

    target = build_target(automated)

    write_immutable_manifest(
        target,
        output_path=TARGET_MANIFEST,
    )

    candidate = build_candidate(
        automated,
        target,
    )

    write_immutable_manifest(
        candidate,
        output_path=CANDIDATE_MANIFEST,
    )

    trial = build_trial(
        physical,
        candidate,
    )

    write_immutable_manifest(
        trial,
        output_path=TRIAL_MANIFEST,
    )

    print("Validation Lab registration")
    print(f"Target: {target.target_id}")
    print(f"Target manifest: {TARGET_MANIFEST}")
    print(f"Candidate: {candidate.candidate_id}")
    print(f"Candidate manifest: {CANDIDATE_MANIFEST}")
    print(f"Decision: {candidate.automated_decision}")
    print(f"Trial: {trial.trial_id}")
    print(f"Trial manifest: {TRIAL_MANIFEST}")
    print(f"Physical passed: {trial.passed}")
    print("Publication eligible: False")


if __name__ == "__main__":
    main()
