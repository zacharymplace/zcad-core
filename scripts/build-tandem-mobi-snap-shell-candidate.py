#!/usr/bin/env python3
"""Register a synthetic-tier Tandem Mobi Validation Lab target and candidate.

There is no manufacturer STEP file for the Mobi, so the "source model"
here is a placeholder rectangular envelope sized from the
manufacturer-published dimensions in
:mod:`zcad_core.hardware.wearables.tandem` - not a real device scan, and
without the fill port, buttons, or charging contacts, whose locations are
still unknown. The resulting target and candidate are explicitly flagged
``provisional_synthetic_candidate`` and are not eligible for promotion or
physical trials until they are replaced by a caliper-verified capture (see
docs/roadmaps/validation-lab.md).
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import cadquery as cq

from zcad_core.hardware.wearables import get_tandem_mobi
from zcad_core.retention import (
    CandidateRevision,
    RetentionEngine,
    RetentionStrategy,
    SnapShellLocation,
    SnapShellPolicy,
    SnapShellRequest,
    SyntheticSnapShellBackend,
    ValidationTarget,
    candidate_identifier,
    sha256_file,
    write_immutable_manifest,
)

ROOT = Path(__file__).resolve().parents[1]

TARGET_ID = "tandem-mobi-pump"
REVISION = "r001"
STRATEGY = "snap-shell"

EVIDENCE_ROOT = ROOT / "evidence" / TARGET_ID

SOURCE_STEP = EVIDENCE_ROOT / "step" / "tandem-mobi-placeholder-envelope.step"

LAB_ROOT = EVIDENCE_ROOT / "validation-lab"

TARGET_MANIFEST = LAB_ROOT / "target.json"

CANDIDATE_ROOT = LAB_ROOT / "candidates" / REVISION

AUTOMATED_REPORT = CANDIDATE_ROOT / "automated-validation.json"

RETENTION_STEP = CANDIDATE_ROOT / "retention.step"

CANDIDATE_MANIFEST = CANDIDATE_ROOT / "candidate.json"


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def build_placeholder_envelope() -> cq.Workplane:
    """Build a placeholder rectangular envelope from published dimensions.

    Not a device scan - see the module docstring above.
    """

    spec = get_tandem_mobi()

    return (
        cq.Workplane("XY")
        .box(
            spec.body_length_mm,
            spec.body_width_mm,
            spec.body_thickness_mm,
        )
        .translate((0.0, 0.0, spec.body_thickness_mm / 2.0))
    )


def snap_shell_locations() -> tuple[SnapShellLocation, ...]:
    """Four edge-midpoint clip locations.

    Placeholder positions only: the fill port, buttons, and charging
    contacts are not yet located, so a real layout must avoid them and
    may need to use fewer or repositioned clips.
    """

    spec = get_tandem_mobi()
    half_length = spec.body_length_mm / 2.0
    half_width = spec.body_width_mm / 2.0

    return (
        SnapShellLocation(
            label="north",
            x_mm=0.0,
            y_mm=half_width,
            rotation_degrees=270.0,
        ),
        SnapShellLocation(
            label="south",
            x_mm=0.0,
            y_mm=-half_width,
            rotation_degrees=90.0,
        ),
        SnapShellLocation(
            label="east",
            x_mm=half_length,
            y_mm=0.0,
            rotation_degrees=180.0,
        ),
        SnapShellLocation(
            label="west",
            x_mm=-half_length,
            y_mm=0.0,
            rotation_degrees=0.0,
        ),
    )


def main() -> None:
    spec = get_tandem_mobi()

    envelope = build_placeholder_envelope()
    SOURCE_STEP.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(envelope, str(SOURCE_STEP))

    policy = SnapShellPolicy()
    locations = snap_shell_locations()

    engine = RetentionEngine()
    engine.register(
        RetentionStrategy.SNAP_SHELL,
        SyntheticSnapShellBackend(),  # type: ignore[arg-type]
    )

    execution = engine.execute(
        strategy=RetentionStrategy.SNAP_SHELL,
        request=SnapShellRequest(
            device_thickness_mm=spec.body_thickness_mm,
            locations=locations,
            policy=policy,
        ),
        model=envelope,
    )

    if not isinstance(execution.model, cq.Workplane):
        raise TypeError("Retention execution did not produce a cadquery Workplane")

    RETENTION_STEP.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(execution.model, str(RETENTION_STEP))

    created_at = datetime.now(UTC).isoformat()
    source_sha256 = sha256_file(SOURCE_STEP)
    output_sha256 = sha256_file(RETENTION_STEP)

    decision = (
        "provisional_synthetic_candidate"
        if execution.passed
        else "rejected"
    )

    fit_results = {
        result.check.value: {"passed": result.passed, "detail": result.detail}
        for result in execution.report.results
    }

    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "generated_at_utc": created_at,
        "decision": decision,
        "geometry_evidence_status": spec.geometry_evidence_status,
        "geometry_source": spec.geometry_source,
        "source": {
            "step_path": str(SOURCE_STEP.relative_to(ROOT)),
            "step_sha256": source_sha256,
            "pcb_solid_index": 1,
        },
        "output": {
            "step_path": str(RETENTION_STEP.relative_to(ROOT)),
            "step_sha256": output_sha256,
        },
        "device": {
            "body_length_mm": spec.body_length_mm,
            "body_width_mm": spec.body_width_mm,
            "body_thickness_mm": spec.body_thickness_mm,
        },
        "selected_corners": [location.label for location in locations],
        "snap_shell_locations": [
            {
                "label": location.label,
                "x_mm": location.x_mm,
                "y_mm": location.y_mm,
                "rotation_degrees": location.rotation_degrees,
            }
            for location in locations
        ],
        "policy": {
            "clip_width_mm": policy.clip_width_mm,
            "wall_mm": policy.wall_mm,
            "clip_height_mm": policy.clip_height_mm,
            "overhang_mm": policy.overhang_mm,
            "clearance_mm": policy.clearance_mm,
            "compliant_span_mm": policy.compliant_span_mm,
        },
        "fit_checks": fit_results,
        "metadata_publication": {
            "approved": False,
            "reason": (
                "Source geometry is a placeholder envelope with no "
                "modeled fill port, buttons, or charging contacts, not "
                "a caliper-verified capture; not eligible for "
                "promotion or physical trials."
            ),
        },
    }

    AUTOMATED_REPORT.parent.mkdir(parents=True, exist_ok=True)
    AUTOMATED_REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    target = ValidationTarget(
        schema_version="1.0.0",
        target_id=TARGET_ID,
        display_name="Tandem Mobi Pump",
        manufacturer="Tandem Diabetes Care",
        product_family="Mobi",
        source_model_path=str(SOURCE_STEP.relative_to(ROOT)),
        source_model_sha256=source_sha256,
        pcb_solid_index=1,
        created_at_utc=created_at,
    )
    write_immutable_manifest(target, output_path=TARGET_MANIFEST)

    retention_policy = {
        "clip_width_mm": policy.clip_width_mm,
        "wall_mm": policy.wall_mm,
        "clip_height_mm": policy.clip_height_mm,
        "overhang_mm": policy.overhang_mm,
        "clearance_mm": policy.clearance_mm,
        "compliant_span_mm": policy.compliant_span_mm,
    }
    derived_parameters: dict[str, object] = {
        "device_thickness_mm": spec.body_thickness_mm,
        **retention_policy,
    }

    candidate = CandidateRevision(
        schema_version="1.0.0",
        candidate_id=candidate_identifier(
            target_id=TARGET_ID,
            strategy=STRATEGY,
            revision=REVISION,
        ),
        target_id=TARGET_ID,
        revision=REVISION,
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        git_commit=git_commit(),
        generator_version="1.0.0",
        retention_policy=retention_policy,
        derived_parameters=derived_parameters,
        selected_corners=tuple(location.label for location in locations),
        automated_decision=decision,
        automated_evidence_path=str(AUTOMATED_REPORT.relative_to(ROOT)),
        fixture_artifact_path=str(RETENTION_STEP.relative_to(ROOT)),
        created_at_utc=created_at,
        strategy=STRATEGY,
    )
    write_immutable_manifest(candidate, output_path=CANDIDATE_MANIFEST)

    print("=== TANDEM MOBI SNAP-SHELL CANDIDATE (synthetic, placeholder geometry) ===")
    print(f"Passed: {execution.passed}")
    print(f"Decision: {decision}")
    print(f"Locations: {', '.join(location.label for location in locations)}")
    print(f"Target manifest: {TARGET_MANIFEST}")
    print(f"Candidate manifest: {CANDIDATE_MANIFEST}")
    print(f"Retention STEP: {RETENTION_STEP}")

    if not execution.passed:
        failed = ", ".join(
            result.check.value
            for result in execution.report.results
            if not result.passed
        )
        raise SystemExit(f"Snap-shell verification failed: {failed}")


if __name__ == "__main__":
    main()
