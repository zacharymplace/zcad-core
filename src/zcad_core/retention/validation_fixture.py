from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.corner_capture import as_corner_capture_parameters
from zcad_core.retention.production_execution import (
    ProductionCornerExecutionResult,
)
from zcad_core.retention.synthetic_backend import (
    SyntheticCornerCaptureBackend,
)


@dataclass(frozen=True)
class ValidationFixturePolicy:
    """Printable fixture dimensions."""

    base_thickness_mm: float = 2.0
    perimeter_margin_mm: float = 2.0

    def __post_init__(self) -> None:
        if self.base_thickness_mm <= 0:
            raise ValueError("base_thickness_mm must be positive")

        if self.perimeter_margin_mm <= 0:
            raise ValueError("perimeter_margin_mm must be positive")


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

    pcb_bounds = execution.board_model.pcb.BoundingBox()

    base_x_mm = pcb_bounds.xlen + 2.0 * policy.perimeter_margin_mm
    base_y_mm = pcb_bounds.ylen + 2.0 * policy.perimeter_margin_mm

    center_x_mm = (pcb_bounds.xmin + pcb_bounds.xmax) / 2.0
    center_y_mm = (pcb_bounds.ymin + pcb_bounds.ymax) / 2.0

    base = (
        cq.Workplane("XY")
        .box(
            base_x_mm,
            base_y_mm,
            policy.base_thickness_mm,
        )
        .translate(
            (
                center_x_mm,
                center_y_mm,
                -policy.base_thickness_mm / 2.0,
            )
        )
    )

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
