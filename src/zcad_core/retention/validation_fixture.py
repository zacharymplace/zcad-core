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

    def __post_init__(self) -> None:
        if self.base_thickness_mm <= 0:
            raise ValueError("base_thickness_mm must be positive")

        if self.perimeter_margin_mm <= 0:
            raise ValueError("perimeter_margin_mm must be positive")

        if self.underside_seating_mm < 0:
            raise ValueError("underside_seating_mm cannot be negative")

        if self.underside_clearance_mm < 0:
            raise ValueError("underside_clearance_mm cannot be negative")


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
