from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.corner_capture import as_corner_capture_parameters
from zcad_core.retention.edge_capture import as_edge_capture_parameters
from zcad_core.retention.production_board import ProductionBoardModel
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionResult,
)
from zcad_core.retention.production_execution import (
    ProductionCornerExecutionResult,
)
from zcad_core.retention.synthetic_backend import (
    SyntheticCornerCaptureBackend,
)
from zcad_core.retention.synthetic_edge_backend import (
    SyntheticEdgeCaptureBackend,
)


@dataclass(frozen=True)
class ValidationFixturePolicy:
    """Printable fixture dimensions."""

    base_thickness_mm: float = 2.0
    perimeter_margin_mm: float = 2.0
    # Parts reaching further below the PCB than this (through-hole pins,
    # jacks) get a clearance hole through the base; shallower bottom-side
    # pads rest on it, matching the design review's seating allowance.
    underside_seating_mm: float = 0.05
    underside_clearance_mm: float = 0.5
    # A part reaching this far past a PCB edge is a connector a cable plugs
    # into; the base is cut away beyond that edge, across the part's width
    # plus this clearance each side, so the plug can seat fully.
    connector_overhang_mm: float = 0.2
    connector_relief_clearance_mm: float = 0.5

    def __post_init__(self) -> None:
        if self.base_thickness_mm <= 0:
            raise ValueError("base_thickness_mm must be positive")

        if self.perimeter_margin_mm <= 0:
            raise ValueError("perimeter_margin_mm must be positive")

        if self.underside_seating_mm < 0:
            raise ValueError("underside_seating_mm cannot be negative")

        if self.underside_clearance_mm < 0:
            raise ValueError("underside_clearance_mm cannot be negative")

        if self.connector_overhang_mm < 0:
            raise ValueError("connector_overhang_mm cannot be negative")

        if self.connector_relief_clearance_mm < 0:
            raise ValueError("connector_relief_clearance_mm cannot be negative")


def _build_base(
    board_model: ProductionBoardModel,
    policy: ValidationFixturePolicy,
) -> cq.Workplane:
    """Base plate whose top is the PCB's underside, with clearance holes."""

    pcb_bounds = board_model.pcb.BoundingBox()
    bottom = pcb_bounds.zmin
    thickness = policy.base_thickness_mm

    base = (
        cq.Workplane("XY")
        .box(
            pcb_bounds.xlen + 2.0 * policy.perimeter_margin_mm,
            pcb_bounds.ylen + 2.0 * policy.perimeter_margin_mm,
            thickness,
        )
        .translate(
            (
                (pcb_bounds.xmin + pcb_bounds.xmax) / 2.0,
                (pcb_bounds.ymin + pcb_bounds.ymax) / 2.0,
                bottom - thickness / 2.0,
            )
        )
    )

    clearance = policy.underside_clearance_mm

    for component in board_model.component_solids:
        bounds = component.BoundingBox()

        if bounds.zmin >= bottom - policy.underside_seating_mm:
            continue

        # Cut straight through the base under the part's footprint.
        hole = cq.Solid.makeBox(
            bounds.xlen + 2.0 * clearance,
            bounds.ylen + 2.0 * clearance,
            thickness + 2.0,
            pnt=cq.Vector(
                bounds.xmin - clearance,
                bounds.ymin - clearance,
                bottom - thickness - 1.0,
            ),
        )
        base = base.cut(hole)

    return _cut_connector_reliefs(base, board_model, policy)


def _cut_connector_reliefs(
    base: cq.Workplane,
    board_model: ProductionBoardModel,
    policy: ValidationFixturePolicy,
) -> cq.Workplane:
    """Remove the base beyond each edge a connector overhangs.

    The perimeter margin would otherwise run under a connector's mouth and
    stop a plug short of seating. The relief starts at the PCB edge, so the
    base under the board is untouched.
    """

    pcb = board_model.pcb.BoundingBox()
    clearance = policy.connector_relief_clearance_mm
    depth = policy.perimeter_margin_mm + 1.0
    height = policy.base_thickness_mm + 2.0
    z0 = pcb.zmin - policy.base_thickness_mm - 1.0

    threshold = policy.connector_overhang_mm

    for component in board_model.component_solids:
        bounds = component.BoundingBox()
        # (x, y, xlen, ylen) of each relief box, one per overhung edge.
        boxes = []
        across_y = (bounds.ymin - clearance, bounds.ylen + 2.0 * clearance)
        across_x = (bounds.xmin - clearance, bounds.xlen + 2.0 * clearance)

        if pcb.xmin - bounds.xmin > threshold:
            boxes.append((pcb.xmin - depth, across_y[0], depth, across_y[1]))
        if bounds.xmax - pcb.xmax > threshold:
            boxes.append((pcb.xmax, across_y[0], depth, across_y[1]))
        if pcb.ymin - bounds.ymin > threshold:
            boxes.append((across_x[0], pcb.ymin - depth, across_x[1], depth))
        if bounds.ymax - pcb.ymax > threshold:
            boxes.append((across_x[0], pcb.ymax, across_x[1], depth))

        for x, y, xlen, ylen in boxes:
            base = base.cut(
                cq.Solid.makeBox(xlen, ylen, height, pnt=cq.Vector(x, y, z0))
            )

    return base


@dataclass(frozen=True)
class ValidationFixtureArtifact:
    """Generated physical-validation fixture."""

    model: cq.Workplane
    stl_path: Path


def build_validation_fixture(
    execution: ProductionCornerExecutionResult,
    *,
    policy: ValidationFixturePolicy,
) -> cq.Workplane:
    """Build a connected base-down validation fixture."""

    base = _build_base(execution.board_model, policy)

    parameters = as_corner_capture_parameters(execution.execution.parameters)
    capture_geometry = SyntheticCornerCaptureBackend().build_geometry(parameters)

    fixture = base.union(capture_geometry)

    if workplane_shape(fixture).isNull():
        raise ValueError("Validation fixture contains no geometry")

    return fixture


def export_validation_fixture(
    execution: ProductionCornerExecutionResult,
    *,
    output_path: Path,
    policy: ValidationFixturePolicy,
) -> ValidationFixtureArtifact:
    """Generate and export a printable STL fixture."""

    fixture = build_validation_fixture(
        execution,
        policy=policy,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    cq.exporters.export(
        fixture,
        str(output_path),
        exportType="STL",
    )

    if not output_path.is_file():
        raise ValueError("Validation fixture STL was not created")

    return ValidationFixtureArtifact(
        model=fixture,
        stl_path=output_path,
    )


def build_edge_validation_fixture(
    execution: ProductionEdgeExecutionResult,
    *,
    policy: ValidationFixturePolicy,
) -> cq.Workplane:
    """Build a connected base-down edge-capture validation fixture."""

    base = _build_base(execution.board_model, policy)

    parameters = as_edge_capture_parameters(execution.execution.parameters)
    capture_geometry = SyntheticEdgeCaptureBackend().build_geometry(parameters)

    fixture = base.union(capture_geometry)

    if workplane_shape(fixture).isNull():
        raise ValueError("Validation fixture contains no geometry")

    return fixture


def export_edge_validation_fixture(
    execution: ProductionEdgeExecutionResult,
    *,
    output_path: Path,
    policy: ValidationFixturePolicy,
) -> ValidationFixtureArtifact:
    """Generate and export a printable STL edge-capture fixture."""

    fixture = build_edge_validation_fixture(
        execution,
        policy=policy,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    cq.exporters.export(
        fixture,
        str(output_path),
        exportType="STL",
    )

    if not output_path.is_file():
        raise ValueError("Validation fixture STL was not created")

    return ValidationFixtureArtifact(
        model=fixture,
        stl_path=output_path,
    )
