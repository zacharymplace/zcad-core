from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionResult,
)
from zcad_core.retention.production_execution import (
    ProductionCornerExecutionResult,
)
from zcad_core.retention.validation_fixture import (
    ValidationFixturePolicy,
    build_edge_validation_fixture,
    build_validation_fixture,
)

# Bounding boxes of meshed shapes (the review exports meshes before measuring)
# read up to ~0.3 um loose, so seating comparisons allow 1 um.
_SEATING_EPSILON_MM = 1e-3

ProductionExecutionResult = (
    ProductionCornerExecutionResult | ProductionEdgeExecutionResult
)


def _selected_locations(execution: ProductionExecutionResult) -> list[str]:
    if isinstance(execution, ProductionEdgeExecutionResult):
        return [execution.derivation.selected_edge.value]

    return [corner.value for corner in execution.derivation.selected_corners]


def _build_fixture(
    execution: ProductionExecutionResult,
    policy: ValidationFixturePolicy,
) -> cq.Workplane:
    if isinstance(execution, ProductionEdgeExecutionResult):
        return build_edge_validation_fixture(execution, policy=policy)

    return build_validation_fixture(execution, policy=policy)


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


def _overlap_box(first: cq.Shape, second: cq.Shape) -> cq.Shape | None:
    a, b = first.BoundingBox(), second.BoundingBox()
    low = (max(a.xmin, b.xmin), max(a.ymin, b.ymin), max(a.zmin, b.zmin))
    high = (min(a.xmax, b.xmax), min(a.ymax, b.ymax), min(a.zmax, b.zmax))

    if any(h <= lo for lo, h in zip(low, high, strict=True)):
        return None

    return cq.Solid.makeBox(
        high[0] - low[0],
        high[1] - low[1],
        high[2] - low[2],
        pnt=cq.Vector(*low),
    )


def _intersection(first: cq.Shape, second: cq.Shape) -> cq.Shape | None:
    """Largest of several boolean formulations, so a silent failure cannot pass.

    OCC can return an empty intersection for defective vendor solids (for
    example, multi-shell PCBs) while a clipped formulation finds the overlap.
    Interference must fail closed, so the largest result wins.
    """

    box = _overlap_box(first, second)

    if box is None:
        return None

    candidates = []

    for chain in (
        (first, second),
        (second, first),
        (first, box, second),
        (second, box, first),
    ):
        shape: cq.Shape | None = chain[0]

        for other in chain[1:]:
            try:
                shape = shape.intersect(other) if shape is not None else None
            except ValueError:
                # cadquery raises on a null boolean result: no overlap here.
                shape = None

            if shape is None or shape.isNull():
                shape = None
                break

        if shape is not None and shape.Volume() > 0:
            candidates.append(shape)

    return max(candidates, key=lambda shape: shape.Volume(), default=None)


def _intersection_volume(
    first: cq.Shape,
    second: cq.Shape,
) -> float:
    intersection = _intersection(first, second)

    return 0.0 if intersection is None else float(intersection.Volume())


def _review_report(
    *,
    execution: ProductionExecutionResult,
    fixture: cq.Shape,
    tolerance_mm3: float,
    seating_contact_mm: float,
    paths: dict[str, Path],
) -> dict[str, Any]:
    pcb = execution.board_model.pcb
    components = execution.board_model.component_solids

    pcb_intersection_mm3 = _intersection_volume(
        fixture,
        pcb,
    )

    pcb_bottom = pcb.BoundingBox().zmin
    component_intersections = []
    seating_contacts = []

    for index, component in enumerate(components, start=1):
        intersection = _intersection(fixture, component)

        if intersection is None or intersection.Volume() <= tolerance_mm3:
            continue

        box = intersection.BoundingBox()
        entry = {
            "component_index": index,
            "intersection_mm3": round(float(intersection.Volume()), 6),
        }

        # Bottom-side pads proud of the PCB rest on the base: accepted as
        # seating contact when the overlap lies wholly under the board and
        # is no deeper than seating_contact_mm.
        if (
            box.zmax <= pcb_bottom + _SEATING_EPSILON_MM
            and pcb_bottom - box.zmin <= seating_contact_mm + _SEATING_EPSILON_MM
        ):
            seating_contacts.append(
                {**entry, "depth_mm": round(pcb_bottom - box.zmin, 6)}
            )
        else:
            component_intersections.append(entry)

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
            # Edge-clip candidates list their selected edge here, as their
            # candidate manifests do.
            "selected_corners": _selected_locations(execution),
        },
        "interference": {
            "pcb_fixture_intersection_mm3": round(
                pcb_intersection_mm3,
                6,
            ),
            "component_fixture_intersections": component_intersections,
            "seating_contact_mm": seating_contact_mm,
            "underside_seating_contacts": seating_contacts,
        },
        "artifacts": {name: str(path) for name, path in paths.items()},
        "review_status": {
            "automated_geometry_complete": True,
            "human_visual_review_complete": False,
            "physical_validation_complete": False,
        },
    }


def export_design_review_package(
    execution: ProductionExecutionResult,
    *,
    output_directory: Path,
    fixture_policy: ValidationFixturePolicy,
    tolerance_mm3: float = 1e-6,
    seating_contact_mm: float = 0.05,
) -> DesignReviewArtifact:
    """Export a multi-format production design-review package."""

    if tolerance_mm3 < 0:
        raise ValueError("tolerance_mm3 cannot be negative")

    if seating_contact_mm < 0:
        raise ValueError("seating_contact_mm cannot be negative")

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

    fixture_workplane = _build_fixture(execution, fixture_policy)
    fixture = workplane_shape(fixture_workplane)

    if fixture.isNull():
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

    assembly.export(str(glb_path))
    assembly.export(str(step_path))

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
        seating_contact_mm=seating_contact_mm,
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
