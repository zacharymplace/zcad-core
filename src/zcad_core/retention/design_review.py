from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.retention.production_execution import (
    ProductionCornerExecutionResult,
)
from zcad_core.retention.validation_fixture import (
    ValidationFixturePolicy,
    build_validation_fixture,
)


@dataclass(frozen=True)
class DesignReviewArtifact:
    """Generated visual and machine-readable review package."""

    glb_path: Path
    step_path: Path
    three_mf_path: Path
    report_path: Path
    view_paths: tuple[Path, ...]
    passed: bool


def _bounds_payload(
    shape: cq.Shape,
) -> dict[str, float]:
    bounds = shape.BoundingBox()

    return {
        "x_mm": round(bounds.xlen, 3),
        "y_mm": round(bounds.ylen, 3),
        "z_mm": round(bounds.zlen, 3),
        "x_min_mm": round(bounds.xmin, 3),
        "x_max_mm": round(bounds.xmax, 3),
        "y_min_mm": round(bounds.ymin, 3),
        "y_max_mm": round(bounds.ymax, 3),
        "z_min_mm": round(bounds.zmin, 3),
        "z_max_mm": round(bounds.zmax, 3),
    }


def _intersection_volume(
    first: cq.Shape,
    second: cq.Shape,
) -> float:
    intersection = first.intersect(second)

    if intersection.isNull():
        return 0.0

    return float(intersection.Volume())


def _review_report(
    *,
    execution: ProductionCornerExecutionResult,
    fixture: cq.Shape,
    tolerance_mm3: float,
    paths: dict[str, Path],
) -> dict[str, Any]:
    pcb = execution.board_model.pcb
    components = execution.board_model.component_solids

    pcb_intersection_mm3 = _intersection_volume(
        fixture,
        pcb,
    )

    component_intersections = tuple(
        {
            "component_index": index,
            "intersection_mm3": round(volume, 6),
        }
        for index, component in enumerate(
            components,
            start=1,
        )
        if (
            volume := _intersection_volume(
                fixture,
                component,
            )
        )
        > tolerance_mm3
    )

    passed = pcb_intersection_mm3 <= tolerance_mm3 and not component_intersections

    return {
        "schema_version": "1.0.0",
        "decision": ("visual_review_ready" if passed else "geometry_review_blocked"),
        "passed": passed,
        "tolerance_mm3": tolerance_mm3,
        "geometry": {
            "fixture_bounds": _bounds_payload(fixture),
            "pcb_bounds": _bounds_payload(pcb),
            "component_count": len(components),
            "selected_corners": [
                corner.value for corner in (execution.derivation.selected_corners)
            ],
        },
        "interference": {
            "pcb_fixture_intersection_mm3": round(
                pcb_intersection_mm3,
                6,
            ),
            "component_fixture_intersections": list(component_intersections),
        },
        "artifacts": {name: str(path) for name, path in paths.items()},
        "review_status": {
            "automated_geometry_complete": True,
            "human_visual_review_complete": False,
            "physical_validation_complete": False,
        },
    }


def export_design_review_package(
    execution: ProductionCornerExecutionResult,
    *,
    output_directory: Path,
    fixture_policy: ValidationFixturePolicy,
    tolerance_mm3: float = 1e-6,
) -> DesignReviewArtifact:
    """Export a multi-format production design-review package."""

    if tolerance_mm3 < 0:
        raise ValueError("tolerance_mm3 cannot be negative")

    glb_path = output_directory / "design-review.glb"
    step_path = output_directory / "design-review.step"
    three_mf_path = output_directory / "design-review.3mf"
    report_path = output_directory / "design-review.json"

    view_definitions = (
        ("top", (0.0, 0.0, 1.0)),
        ("front", (0.0, -1.0, 0.0)),
        ("right", (1.0, 0.0, 0.0)),
        ("isometric", (1.0, -1.0, 1.0)),
    )
    view_paths = tuple(
        output_directory / f"design-review-{name}.svg" for name, _ in view_definitions
    )

    output_paths = (
        glb_path,
        step_path,
        three_mf_path,
        report_path,
        *view_paths,
    )
    existing = tuple(path for path in output_paths if path.exists())

    if existing:
        rendered = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"Refusing to overwrite design-review artifacts: {rendered}"
        )

    fixture_workplane = build_validation_fixture(
        execution,
        policy=fixture_policy,
    )
    fixture = fixture_workplane.val()

    if fixture is None or fixture.isNull():
        raise ValueError("Design-review fixture contains no geometry")

    pcb = execution.board_model.pcb
    components = execution.board_model.component_solids
    shapes = (
        fixture,
        pcb,
        *components,
    )

    if any(shape.isNull() for shape in shapes):
        raise ValueError("Design-review package contains null geometry")

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    assembly = cq.Assembly()
    assembly.add(
        fixture,
        name="validation-fixture",
        color=cq.Color(0.16, 0.38, 0.82),
    )
    assembly.add(
        pcb,
        name="pcb",
        color=cq.Color(0.08, 0.55, 0.22),
    )

    for index, component in enumerate(
        components,
        start=1,
    ):
        assembly.add(
            component,
            name=f"component-{index:03d}",
            color=cq.Color(0.68, 0.70, 0.74),
        )

    assembly.save(str(glb_path))
    assembly.save(str(step_path))

    cq.exporters.export(
        shapes,
        str(three_mf_path),
        exportType="3MF",
    )

    compound = cq.Compound.makeCompound(list(shapes))

    for (
        (name, projection),
        view_path,
    ) in zip(
        view_definitions,
        view_paths,
        strict=True,
    ):
        svg = cq.exporters.getSVG(
            compound,
            opts={
                "width": 1200,
                "height": 900,
                "marginLeft": 40,
                "marginTop": 40,
                "projectionDir": projection,
                "showAxes": False,
                "showHidden": True,
                "strokeWidth": 0.5,
            },
        )
        view_path.write_text(
            svg,
            encoding="utf-8",
        )

    artifact_paths = {
        "glb": glb_path,
        "step": step_path,
        "three_mf": three_mf_path,
        **{
            f"{name}_view": path
            for (name, _), path in zip(
                view_definitions,
                view_paths,
                strict=True,
            )
        },
    }

    report = _review_report(
        execution=execution,
        fixture=fixture,
        tolerance_mm3=tolerance_mm3,
        paths=artifact_paths,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    for path in output_paths:
        if not path.is_file():
            raise RuntimeError(f"Design-review artifact was not created: {path}")

        if path.stat().st_size == 0:
            raise RuntimeError(f"Design-review artifact is empty: {path}")

    return DesignReviewArtifact(
        glb_path=glb_path,
        step_path=step_path,
        three_mf_path=three_mf_path,
        report_path=report_path,
        view_paths=view_paths,
        passed=bool(report["passed"]),
    )
