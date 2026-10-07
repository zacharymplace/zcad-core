from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume, solid_intersection
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

DESIGN_REVIEW_SCHEMA_VERSION = "1.3.0"

# How many nearest parts the clearance section lists, and how close (by
# bounding box) a part must be to a capture before its exact gap is measured.
_CLOSEST_LISTED = 5
_CAPTURE_SEARCH_MM = 3.0
# A part overhangs an edge when it extends this far past the PCB outline.
_OVERHANG_MM = 0.2

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


def _rests_under_board(component: cq.Shape, pcb_bounds: cq.BoundBox) -> bool:
    """Whether a component sits within the board footprint and reaches its
    underside, so touching the base top is seating rather than a clash."""

    bounds = component.BoundingBox()

    return (
        bounds.xmin >= pcb_bounds.xmin - _SEATING_EPSILON_MM
        and bounds.xmax <= pcb_bounds.xmax + _SEATING_EPSILON_MM
        and bounds.ymin >= pcb_bounds.ymin - _SEATING_EPSILON_MM
        and bounds.ymax <= pcb_bounds.ymax + _SEATING_EPSILON_MM
        and bounds.zmin <= pcb_bounds.zmin + _SEATING_EPSILON_MM
    )


def _round(value: float) -> float:
    return round(value, 3)


def _part_entry(index: int, component: cq.Shape, gap: float) -> dict[str, Any]:
    bounds = component.BoundingBox()

    return {
        "component_index": index,
        "gap_mm": _round(gap),
        "center_mm": [_round(bounds.center.x), _round(bounds.center.y)],
        "size_mm": [_round(bounds.xlen), _round(bounds.ylen), _round(bounds.zlen)],
        "z_range_mm": [_round(bounds.zmin), _round(bounds.zmax)],
    }


def _within(first: cq.BoundBox, second: cq.BoundBox, margin: float) -> bool:
    return (
        first.xmin <= second.xmax + margin
        and second.xmin <= first.xmax + margin
        and first.ymin <= second.ymax + margin
        and second.ymin <= first.ymax + margin
        and first.zmin <= second.zmax + margin
        and second.zmin <= first.zmax + margin
    )


def _base_lip(
    fixture: cq.Shape,
    fixture_bounds: cq.BoundBox,
    pcb_bounds: cq.BoundBox,
    part: cq.BoundBox,
    edge: str,
) -> float:
    """How far the base below a part runs past its outer face.

    Measured from the base's material within the part's span, from the PCB
    edge outwards, not from the fixture's bounds: a connector relief notches
    the base under the part and leaves the bounds where they were. Negative
    when the base stops short of the face; at the PCB edge when none is left.
    The base is the fixture below the PCB's underside, so a capture beside
    the part is not counted.
    """

    reach = 2.0 + max(fixture_bounds.xlen, fixture_bounds.ylen)
    z0 = fixture_bounds.zmin - 1.0
    height = pcb_bounds.zmin - z0

    if edge == "negative_x":
        box = (pcb_bounds.xmin - reach, part.ymin, reach, part.ylen)
    elif edge == "positive_x":
        box = (pcb_bounds.xmax, part.ymin, reach, part.ylen)
    elif edge == "negative_y":
        box = (part.xmin, pcb_bounds.ymin - reach, part.xlen, reach)
    else:
        box = (part.xmin, pcb_bounds.ymax, part.xlen, reach)

    x, y, xlen, ylen = box
    below = solid_intersection(
        fixture, cq.Solid.makeBox(xlen, ylen, height, pnt=cq.Vector(x, y, z0))
    )
    material = None if below is None else below.BoundingBox()

    if edge == "negative_x":
        return part.xmin - (pcb_bounds.xmin if material is None else material.xmin)
    if edge == "positive_x":
        return (pcb_bounds.xmax if material is None else material.xmax) - part.xmax
    if edge == "negative_y":
        return part.ymin - (pcb_bounds.ymin if material is None else material.ymin)

    return (pcb_bounds.ymax if material is None else material.ymax) - part.ymax


def _edge_overhangs(
    components: Sequence[cq.Shape],
    *,
    fixture: cq.Shape,
    pcb_bounds: cq.BoundBox,
    fixture_bounds: cq.BoundBox,
    gaps: dict[int, float],
) -> list[dict[str, Any]]:
    """Parts that overhang the PCB edge, and how far the base runs past them.

    A positive ``base_lip_mm`` is fixture extending beyond the part's outer
    face; with a small ``height_above_base_mm`` a cable plug seated in the
    part can bind on it. A negative one is a relief: the base stops that far
    short of the face.
    """

    overhangs = []

    for index, component in enumerate(components, start=1):
        bounds = component.BoundingBox()
        faces = (
            ("negative_x", pcb_bounds.xmin - bounds.xmin),
            ("positive_x", bounds.xmax - pcb_bounds.xmax),
            ("negative_y", pcb_bounds.ymin - bounds.ymin),
            ("positive_y", bounds.ymax - pcb_bounds.ymax),
        )

        for edge, overhang in faces:
            if overhang > _OVERHANG_MM:
                lip = _base_lip(fixture, fixture_bounds, pcb_bounds, bounds, edge)
                overhangs.append(
                    {
                        "component_index": index,
                        "edge": edge,
                        "overhang_mm": _round(overhang),
                        "base_lip_mm": _round(lip),
                        "height_above_base_mm": _round(bounds.zmin - pcb_bounds.zmin),
                        "gap_mm": _round(gaps.get(index, 0.0)),
                        "size_mm": [
                            _round(bounds.xlen),
                            _round(bounds.ylen),
                            _round(bounds.zlen),
                        ],
                    }
                )

    return overhangs


def _clearance_report(
    *,
    fixture: cq.Shape,
    pcb: cq.Shape,
    components: Sequence[cq.Shape],
    gaps: dict[int, float],
    seating_indices: set[int],
    seating_contact_mm: float,
) -> dict[str, Any]:
    """Measured clearances a human reviewer needs, beyond pass or fail.

    ``gaps`` holds the exact fixture distance of every part that does not
    overlap it. Captures are the fixture above the PCB's underside; the
    base is everything below.
    """

    pcb_bounds = pcb.BoundingBox()
    fixture_bounds = fixture.BoundingBox()

    closest = sorted(
        (gap, index) for index, gap in gaps.items() if index not in seating_indices
    )[:_CLOSEST_LISTED]

    lift = pcb_bounds.zmin + _SEATING_EPSILON_MM
    above = cq.Solid.makeBox(
        fixture_bounds.xlen + 2.0,
        fixture_bounds.ylen + 2.0,
        max(fixture_bounds.zmax - lift, 0.0) + 1.0,
        pnt=cq.Vector(fixture_bounds.xmin - 1.0, fixture_bounds.ymin - 1.0, lift),
    )
    captures = solid_intersection(fixture, above)
    capture_gaps: list[tuple[float, int]] = []

    if captures is not None:
        # Filter per capture: the captures sit at opposite corners or ends,
        # so their combined bounding box would cover the whole board.
        capture_bounds = [solid.BoundingBox() for solid in captures.Solids()]

        for index, component in enumerate(components, start=1):
            bounds = component.BoundingBox()

            if index in seating_indices or not any(
                _within(bounds, capture, _CAPTURE_SEARCH_MM)
                for capture in capture_bounds
            ):
                continue

            capture_gaps.append((captures.distance(component), index))

    underside = []

    for index, component in enumerate(components, start=1):
        depth = pcb_bounds.zmin - component.BoundingBox().zmin

        if depth > seating_contact_mm + _SEATING_EPSILON_MM:
            underside.append(
                {
                    "component_index": index,
                    "depth_below_pcb_mm": _round(depth),
                    "hole_clearance_mm": _round(gaps.get(index, 0.0)),
                }
            )

    return {
        "closest_components": [
            _part_entry(index, components[index - 1], gap) for gap, index in closest
        ],
        "capture_volume_mm3": (
            None if captures is None else _round(float(captures.Volume()))
        ),
        "pcb_to_capture_gap_mm": (
            None if captures is None else _round(captures.distance(pcb))
        ),
        "closest_to_captures": [
            _part_entry(index, components[index - 1], gap)
            for gap, index in sorted(capture_gaps)[:_CLOSEST_LISTED]
        ],
        "edge_overhangs": _edge_overhangs(
            components,
            fixture=fixture,
            pcb_bounds=pcb_bounds,
            fixture_bounds=fixture_bounds,
            gaps=gaps,
        ),
        "underside_passthroughs": underside,
    }


def _review_report(
    *,
    execution: ProductionExecutionResult,
    fixture: cq.Shape,
    tolerance_mm3: float,
    seating_contact_mm: float,
    minimum_component_gap_mm: float,
    paths: dict[str, Path],
) -> dict[str, Any]:
    pcb = execution.board_model.pcb
    components = execution.board_model.component_solids

    pcb_intersection_mm3 = intersection_volume(
        fixture,
        pcb,
    )

    pcb_bounds = pcb.BoundingBox()
    pcb_bottom = pcb_bounds.zmin
    component_intersections = []
    clearance_violations = []
    seating_contacts = []
    gaps: dict[int, float] = {}

    for index, component in enumerate(components, start=1):
        intersection = solid_intersection(fixture, component)

        if intersection is None or intersection.Volume() <= tolerance_mm3:
            gap = fixture.distance(component)
            gaps[index] = gap

            # No overlapping volume, but flush or near-flush faces still clash
            # once printed: UNO R4 r004's clip ended flush against a header.
            if gap < minimum_component_gap_mm:
                if _rests_under_board(component, pcb_bounds):
                    seating_contacts.append(
                        {
                            "component_index": index,
                            "intersection_mm3": 0.0,
                            "depth_mm": 0.0,
                        }
                    )
                else:
                    clearance_violations.append(
                        {"component_index": index, "gap_mm": round(gap, 6)}
                    )

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

    passed = (
        pcb_intersection_mm3 <= tolerance_mm3
        and not component_intersections
        and not clearance_violations
    )

    return {
        "schema_version": DESIGN_REVIEW_SCHEMA_VERSION,
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
            "minimum_component_gap_mm": minimum_component_gap_mm,
            "component_clearance_violations": clearance_violations,
            "seating_contact_mm": seating_contact_mm,
            "underside_seating_contacts": seating_contacts,
        },
        "clearance": _clearance_report(
            fixture=fixture,
            pcb=pcb,
            components=components,
            gaps=gaps,
            seating_indices={
                int(contact["component_index"]) for contact in seating_contacts
            },
            seating_contact_mm=seating_contact_mm,
        ),
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
    minimum_component_gap_mm: float = 0.1,
) -> DesignReviewArtifact:
    """Export a multi-format production design-review package.

    The review blocks on any fixture overlap with the PCB or a component
    (beyond seating contact under the board), and on any component closer
    to the fixture than ``minimum_component_gap_mm``, which catches faces
    that touch with zero overlapping volume.
    """

    if tolerance_mm3 < 0:
        raise ValueError("tolerance_mm3 cannot be negative")

    if seating_contact_mm < 0:
        raise ValueError("seating_contact_mm cannot be negative")

    if minimum_component_gap_mm < 0:
        raise ValueError("minimum_component_gap_mm cannot be negative")

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
        minimum_component_gap_mm=minimum_component_gap_mm,
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
