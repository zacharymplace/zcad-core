"""Inspect the complete Workplane stack before any export side effects."""

import math
from dataclasses import dataclass
from typing import Any

import cadquery as cq


class GeometryValidationError(ValueError):
    """Rejected geometry with machine-readable check results."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        failed = next(c for c in report["checks"] if c["status"] == "FAIL")
        super().__init__(
            f"Part '{report['part_name']}': {failed['code']}: {failed['message']}"
        )


@dataclass(frozen=True)
class InspectedGeometry:
    """Owned shape snapshot and measurements taken before triangulation."""

    shape: cq.Shape
    volume_mm3: float
    bounds_mm: tuple[float, float, float]
    report: dict[str, Any]


def _solid_leaves(shape: cq.Shape) -> list[cq.Shape]:
    if shape.ShapeType() == "Solid":
        return [shape]
    if shape.ShapeType() in {"Compound", "CompSolid"}:
        children = list(shape)
        if children:
            return [solid for child in children for solid in _solid_leaves(child)]
    raise ValueError(
        "Every stack item must contain only solids; no loose faces or wires"
    )


def inspect_export_geometry(model: cq.Workplane, part_name: str) -> InspectedGeometry:
    """Allow one or more solids, reject mixed topology, and measure all items.

    Multiple solids are retained as a compound, not fused. Their intersections
    and physical suitability are outside this inspection's scope.
    """
    codes = (
        "shape_stack",
        "solid_topology",
        "brep_validity",
        "positive_volume",
        "finite_bounds",
    )
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "part_name": part_name,
        "scope": "pre-export geometry; complete Workplane stack",
        "checks": [
            {"code": code, "status": "NOT_CHECKED", "message": "Prerequisite not met"}
            for code in codes
        ],
    }

    def check(index: int, passed: bool, message: str) -> None:
        report["checks"][index].update(
            status="PASS" if passed else "FAIL", message=message
        )
        if not passed:
            raise GeometryValidationError(report)

    values = model.vals()
    check(
        0,
        bool(values) and all(isinstance(v, cq.Shape) for v in values),
        "Expected a nonempty stack of shapes",
    )
    # Own the snapshot so exporter triangulation does not pollute caller geometry.
    shapes = [v.copy() for v in values if isinstance(v, cq.Shape)]
    solids: list[cq.Shape] = []
    try:
        for shape in shapes:
            solids.extend(_solid_leaves(shape))
    except ValueError as error:
        check(1, False, str(error))
    check(1, bool(solids), "All stack items contain only solids")
    shape = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
    check(2, shape.isValid() and all(s.isValid() for s in solids), "BRep validity")
    volumes = [s.Volume() for s in solids]
    volume = shape.Volume()
    check(
        3,
        all(math.isfinite(v) and v > 0 for v in [volume, *volumes]),
        "Aggregate and individual solid volumes must be finite and positive",
    )
    bounds = shape.BoundingBox()
    dimensions = (bounds.xlen, bounds.ylen, bounds.zlen)
    coordinates = (
        bounds.xmin,
        bounds.xmax,
        bounds.ymin,
        bounds.ymax,
        bounds.zmin,
        bounds.zmax,
    )
    check(
        4,
        all(math.isfinite(v) for v in coordinates)
        and all(math.isfinite(v) and v > 0 for v in dimensions),
        "Finite bounds with positive XYZ dimensions",
    )
    report["solid_count"] = len(solids)
    report["checks"].extend(
        {
            "code": code,
            "status": "NOT_CHECKED",
            "message": "Outside export geometry inspection",
        }
        for code in (
            "solid_intersections",
            "printer_fit",
            "manufacturing",
            "physical_fit",
            "artifact_integrity",
        )
    )
    return InspectedGeometry(shape, volume, dimensions, report)
