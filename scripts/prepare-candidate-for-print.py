"""Bring a Validation Lab candidate to the pre-print state.

For a corner-capture or edge-clip candidate directory this:

1. requires its latest export-validation run to pass and still verify
2. regenerates the retention geometry and requires it to match the
   candidate's ``retention.step`` solid for solid (volume and bounds)
3. writes the design-review package and ``installation-path-analysis.json``
4. stops there if the design review is blocked; otherwise writes
   ``slicing-readiness.json`` if it is missing and
5. opens ``trials/trial-001`` with a pending record for the project's
   printer, material, and slicer profiles, plus an ``observations.json``
   template for the operator

Nothing existing is overwritten. Slice the fixture separately with
``scripts/slice-candidate-fixture.py``.

Usage:
    python scripts/prepare-candidate-for-print.py <candidate-directory> \\
        [--corner-keepout-mm 4.0] \\
        [--slicer-profile profiles/slicers/<id>.json]
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import cadquery as cq
from OCP.StlAPI import StlAPI_Reader  # type: ignore[import-untyped]
from OCP.TopoDS import TopoDS_Shape  # type: ignore[import-untyped]

from zcad_core.retention import (
    CornerCapturePolicy,
    EdgeCapturePolicy,
    PhysicalValidationCheck,
    ProductionCornerExecutionRequest,
    ProductionEdgeExecutionRequest,
    ValidationFixturePolicy,
    analyze_edge_installation_paths,
    analyze_installation_paths,
    create_pending_physical_validation_record,
    evaluate_slicing_readiness,
    execute_production_corner_capture,
    execute_production_edge_capture,
    export_design_review_package,
    load_candidate_revision,
    load_export_validation_record,
    load_manifest,
    verify_export_validation,
    write_installation_path_report,
    write_physical_validation_record,
    write_slicing_readiness_report,
)

POLICY_FIELDS = (
    "arm_width_mm",
    "engagement_depth_mm",
    "board_clearance_mm",
    "vertical_overlap_mm",
    "minimum_wall_mm",
)


def solid_signature(step: Path) -> list[tuple[float, ...]]:
    signature = []

    for solid in cq.importers.importStep(str(step)).solids().vals():
        if not isinstance(solid, cq.Shape):
            continue

        box = solid.BoundingBox()
        signature.append(
            tuple(
                round(value, 6)
                for value in (
                    solid.Volume(),
                    box.xmin,
                    box.ymin,
                    box.zmin,
                    box.xmax,
                    box.ymax,
                    box.zmax,
                )
            )
        )

    return sorted(signature)


def latest_export_validation(candidate_directory: Path) -> Path:
    runs = sorted(
        path
        for path in (candidate_directory / "export-validation").glob("v*")
        if re.fullmatch(r"v[0-9]{3}", path.name)
    )

    if not runs:
        raise SystemExit("No export-validation run; run candidate revalidate first")

    return runs[-1] / "export-validation.json"


def refuse_existing(*paths: Path) -> None:
    existing = [str(path) for path in paths if path.exists()]

    if existing:
        raise SystemExit(f"Refusing to overwrite: {', '.join(existing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidate_directory", type=Path)
    parser.add_argument("--corner-keepout-mm", type=float, default=4.0)
    parser.add_argument(
        "--slicer-profile",
        type=Path,
        default=Path("profiles/slicers/bambu-studio-a1-mini-petg-validation.json"),
    )
    args = parser.parse_args()

    directory = args.candidate_directory
    candidate = load_candidate_revision(directory / "candidate.json")
    target = load_manifest(directory.parents[1] / "target.json")
    slicer: dict[str, Any] = load_manifest(args.slicer_profile)
    printer_id = str(slicer["printer_profile_id"])
    material_id = str(slicer["material_profile_id"])

    trial = directory / "trials" / "trial-001"
    install_report = directory / "installation-path-analysis.json"
    refuse_existing(directory / "design-review.json", install_report, trial)

    record_path = latest_export_validation(directory)
    failures = verify_export_validation(
        load_export_validation_record(record_path), candidate=candidate
    )

    if failures:
        raise SystemExit(f"{record_path} does not support the candidate: {failures}")

    policy = {name: float(candidate.retention_policy[name]) for name in POLICY_FIELDS}
    source_step = Path(target["source_model_path"])
    pcb_solid_index = int(target["pcb_solid_index"])

    with tempfile.TemporaryDirectory(prefix="zcad-prepare-") as folder:
        regenerated = Path(folder) / "retention.step"

        if candidate.strategy == "corner-capture":
            corner = execute_production_corner_capture(
                ProductionCornerExecutionRequest(
                    source_step=source_step,
                    pcb_solid_index=pcb_solid_index,
                    output_step=regenerated,
                    policy=CornerCapturePolicy(**policy),
                    corner_keepout_mm=args.corner_keepout_mm,
                )
            )
            install = analyze_installation_paths(
                corner, candidate_id=candidate.candidate_id
            )
            execution: Any = corner
        elif candidate.strategy == "edge-clip":
            edge_policy = EdgeCapturePolicy(**policy)
            edge = execute_production_edge_capture(
                ProductionEdgeExecutionRequest(
                    source_step=source_step,
                    pcb_solid_index=pcb_solid_index,
                    output_step=regenerated,
                    policy=edge_policy,
                    engagement_depth_mm=edge_policy.engagement_depth_mm,
                )
            )
            install = analyze_edge_installation_paths(
                edge, candidate_id=candidate.candidate_id
            )
            execution = edge
        else:
            raise SystemExit(f"Unsupported strategy: {candidate.strategy}")

        if solid_signature(regenerated) != solid_signature(
            directory / "retention.step"
        ):
            raise SystemExit(
                "Regenerated geometry does not match retention.step; check "
                "--corner-keepout-mm and the generator version"
            )

    review = export_design_review_package(
        execution,
        output_directory=directory,
        fixture_policy=ValidationFixturePolicy(),
    )
    write_installation_path_report(install, output_path=install_report)

    if not review.passed:
        # A blocked candidate must not look ready: keep the review evidence,
        # but do not open a trial or claim slicing readiness.
        print(
            json.dumps(
                {
                    "candidate_id": candidate.candidate_id,
                    "design_review_passed": False,
                    "design_review": str(review.report_path),
                },
                indent=2,
            )
        )
        return 1

    readiness_path = directory / "slicing-readiness.json"

    if not readiness_path.exists():
        mesh = TopoDS_Shape()
        StlAPI_Reader().Read(mesh, str(directory / "fixture.stl"))
        write_slicing_readiness_report(
            evaluate_slicing_readiness(
                candidate_id=candidate.candidate_id,
                fixture_model=cq.Workplane().newObject([cq.Shape.cast(mesh)]),
                fixture_artifact_path=directory / "fixture.stl",
                printer_profile=load_manifest(
                    Path(f"profiles/printers/{printer_id}.json")
                ),
                material_profile=load_manifest(
                    Path(f"profiles/materials/{material_id}.json")
                ),
                slicer_profile=slicer,
            ),
            output_path=readiness_path,
        )

    write_physical_validation_record(
        create_pending_physical_validation_record(
            candidate_report_path=directory / "automated-validation.json",
            fixture_stl_path=directory / "fixture.stl",
            printer_profile=printer_id,
            material_profile=material_id,
            slicer_profile=str(slicer["profile_id"]),
        ),
        output_path=trial / "physical-validation.json",
    )
    (trial / "observations.json").write_text(
        json.dumps(
            {
                check.value: {"passed": False, "notes": ""}
                for check in PhysicalValidationCheck
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "candidate_id": candidate.candidate_id,
                "export_validation": str(record_path),
                "design_review_passed": review.passed,
                "rigid_installation_path_verified": install.rigid_path_verified,
                "trial": str(trial),
            },
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
