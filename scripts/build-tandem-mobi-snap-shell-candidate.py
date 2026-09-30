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

With no arguments it registers the target and r001. A later revision names
its parent and why, such as after the spec's dimensions change; it writes
its own placeholder envelope beside r001's, so r001's pinned files never
change, and records its relationship to the parent:

    python scripts/build-tandem-mobi-snap-shell-candidate.py \\
        --revision r002 --parent r001 --reason "..."
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cadquery as cq

from zcad_core.hardware.wearables import get_tandem_mobi
from zcad_core.retention import (
    CandidateRevision,
    RetentionEngine,
    RetentionStrategy,
    RevisionRelationshipType,
    SnapShellLocation,
    SnapShellPolicy,
    SnapShellRequest,
    SyntheticSnapShellBackend,
    ValidationTarget,
    as_snap_shell_fit_report,
    candidate_identifier,
    load_candidate_revision,
    load_manifest,
    persist_candidate_revision,
    run_candidate_export_validation,
    sha256_file,
    write_immutable_manifest,
)

ROOT = Path(__file__).resolve().parents[1]

TARGET_ID = "tandem-mobi-pump"
FIRST_REVISION = "r001"
STRATEGY = "snap-shell"


@dataclass(frozen=True)
class RevisionPaths:
    """Where one revision's files go, under a repository root."""

    root: Path
    revision: str

    @property
    def lab(self) -> Path:
        return self.root / "evidence" / TARGET_ID / "validation-lab"

    @property
    def source_step(self) -> Path:
        # r001 keeps the name it was registered with.
        suffix = "" if self.revision == FIRST_REVISION else f"-{self.revision}"
        return (
            self.root
            / "evidence"
            / TARGET_ID
            / "step"
            / f"tandem-mobi-placeholder-envelope{suffix}.step"
        )

    @property
    def target_manifest(self) -> Path:
        return self.lab / "target.json"

    @property
    def candidate_root(self) -> Path:
        return self.lab / "candidates" / self.revision

    @property
    def automated_report(self) -> Path:
        return self.candidate_root / "automated-validation.json"

    @property
    def retention_step(self) -> Path:
        return self.candidate_root / "retention.step"

    @property
    def candidate_manifest(self) -> Path:
        return self.candidate_root / "candidate.json"

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))


def git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
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


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--revision", default=FIRST_REVISION)
    parser.add_argument("--parent", help="the revision this one follows, as r001")
    parser.add_argument(
        "--relationship",
        choices=[kind.value for kind in RevisionRelationshipType],
        default=RevisionRelationshipType.SUPERSEDES.value,
    )
    parser.add_argument("--reason", help="why this revision exists; needs --parent")
    args = parser.parse_args(argv)

    if args.revision == FIRST_REVISION and args.parent:
        parser.error(f"{FIRST_REVISION} is the first revision and has no parent")

    if args.revision != FIRST_REVISION and not (args.parent and args.reason):
        parser.error(f"{args.revision} needs --parent and --reason")

    return args


def _require_new(paths: RevisionPaths, parent: RevisionPaths | None) -> None:
    """Refuse before exporting anything: the STEP files and report are
    written before the immutable manifests, so a rerun against an existing
    revision would clobber its pinned artifacts and only then fail."""

    pinned = [paths.candidate_manifest, paths.source_step, paths.retention_step]

    if parent is None:
        pinned.append(paths.target_manifest)

    existing = [path for path in pinned if path.exists()]

    if existing:
        raise SystemExit(
            "Refusing to regenerate over pinned files: "
            + ", ".join(paths.relative(path) for path in existing)
        )

    if parent is not None:
        missing = [
            path
            for path in (paths.target_manifest, parent.candidate_manifest)
            if not path.exists()
        ]

        if missing:
            raise SystemExit(
                "A revision needs its target and parent registered first: "
                + ", ".join(paths.relative(path) for path in missing)
            )


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> None:
    args = _arguments(argv)
    paths = RevisionPaths(root, args.revision)
    parent = RevisionPaths(root, args.parent) if args.parent else None
    _require_new(paths, parent)

    spec = get_tandem_mobi()

    envelope = build_placeholder_envelope()
    paths.source_step.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(envelope, str(paths.source_step))

    policy = SnapShellPolicy()
    locations = snap_shell_locations()

    engine = RetentionEngine()
    engine.register(
        RetentionStrategy.SNAP_SHELL,
        SyntheticSnapShellBackend(),
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

    fit_report = as_snap_shell_fit_report(execution.report)

    paths.retention_step.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(execution.model, str(paths.retention_step))

    created_at = datetime.now(UTC).isoformat()
    source_sha256 = sha256_file(paths.source_step)
    output_sha256 = sha256_file(paths.retention_step)

    decision = "provisional_synthetic_candidate" if execution.passed else "rejected"

    fit_results = {
        result.check.value: {"passed": result.passed, "detail": result.detail}
        for result in fit_report.results
    }

    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "generated_at_utc": created_at,
        "decision": decision,
        "geometry_evidence_status": spec.geometry_evidence_status,
        "geometry_source": spec.geometry_source,
        "source": {
            "step_path": paths.relative(paths.source_step),
            "step_sha256": source_sha256,
            "pcb_solid_index": 1,
        },
        "output": {
            "step_path": paths.relative(paths.retention_step),
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

    paths.automated_report.parent.mkdir(parents=True, exist_ok=True)
    paths.automated_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if parent is None:
        target = ValidationTarget(
            schema_version="1.0.0",
            target_id=TARGET_ID,
            display_name="Tandem Mobi Pump",
            manufacturer="Tandem Diabetes Care",
            product_family="Mobi",
            source_model_path=paths.relative(paths.source_step),
            source_model_sha256=source_sha256,
            pcb_solid_index=1,
            created_at_utc=created_at,
        )
        write_immutable_manifest(target, output_path=paths.target_manifest)

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
            revision=args.revision,
        ),
        target_id=TARGET_ID,
        revision=args.revision,
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        git_commit=git_commit(root),
        generator_version="1.0.0",
        retention_policy=retention_policy,
        derived_parameters=derived_parameters,
        selected_corners=tuple(location.label for location in locations),
        automated_decision=decision,
        automated_evidence_path=paths.relative(paths.automated_report),
        fixture_artifact_path=paths.relative(paths.retention_step),
        created_at_utc=created_at,
        strategy=STRATEGY,
    )

    if parent is None:
        write_immutable_manifest(candidate, output_path=paths.candidate_manifest)
    else:
        persist_candidate_revision(
            parent_candidate=load_candidate_revision(parent.candidate_manifest),
            candidate=candidate,
            relationship=RevisionRelationshipType(args.relationship),
            reason=args.reason,
            output_directory=paths.candidate_root,
        )

    # The shell does not embed the placeholder envelope, so no reference board.
    export_validation, export_validation_path = run_candidate_export_validation(
        candidate=candidate,
        retention_step=paths.retention_step,
        validation_root=paths.candidate_root / "export-validation",
        printer_profile=load_manifest(
            root / "profiles/printers/bambu-lab-a1-mini.json"
        ),
        repository_root=root,
        validated_at_utc=created_at,
    )

    print("=== TANDEM MOBI SNAP-SHELL CANDIDATE (synthetic, placeholder geometry) ===")
    print(
        f"Revision: {args.revision}"
        + (f" ({args.relationship} {args.parent})" if parent else "")
    )
    print(f"Passed: {execution.passed}")
    print(f"Decision: {decision}")
    print(f"Locations: {', '.join(location.label for location in locations)}")
    print(f"Target manifest: {paths.target_manifest}")
    print(f"Candidate manifest: {paths.candidate_manifest}")
    print(f"Retention STEP: {paths.retention_step}")
    print(f"Export validation: {export_validation.evaluated_status}")
    print(f"Export-validation record: {export_validation_path}")

    if not execution.passed:
        failed = ", ".join(
            result.check.value for result in fit_report.results if not result.passed
        )
        raise SystemExit(f"Snap-shell verification failed: {failed}")


if __name__ == "__main__":
    main()
