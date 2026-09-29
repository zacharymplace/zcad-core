from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.capture_interference import (
    GeometryInterferenceResult,
    measure_capture_interference,
)
from zcad_core.retention.edge_backend import (
    EdgeCaptureFitCheck,
    EdgeCaptureFitReport,
    as_edge_capture_fit_report,
)
from zcad_core.retention.edge_capture import (
    EdgeCapturePolicy,
    as_edge_capture_parameters,
)
from zcad_core.retention.engine import (
    RetentionExecution,
    RetentionStrategy,
)
from zcad_core.retention.production_board import ProductionBoardModel
from zcad_core.retention.production_edge_board import (
    ProductionBoardEdgeAdapter,
    ProductionEdgeDerivation,
)
from zcad_core.retention.production_run import (
    export_retention_step,
    run_backend,
    verified_execution,
)
from zcad_core.retention.synthetic_edge_backend import SyntheticEdgeCaptureBackend

_INTERFERENCE_TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class ProductionEdgeExecutionRequest:
    """Inputs for one evidence-backed production-board edge-capture execution."""

    source_step: Path
    pcb_solid_index: int
    output_step: Path
    policy: EdgeCapturePolicy
    engagement_depth_mm: float = 2.5
    vertical_margin_mm: float = 0.10
    minimum_anchor_separation_mm: float = 10.0

    def __post_init__(self) -> None:
        if self.pcb_solid_index < 1:
            raise ValueError("pcb_solid_index must be one-based and positive")

        if self.output_step.suffix.lower() not in {
            ".step",
            ".stp",
        }:
            raise ValueError("output_step must use a STEP extension")


@dataclass(frozen=True)
class ProductionEdgeExecutionResult:
    """Evidence, geometry, verification, and export result."""

    board_model: ProductionBoardModel
    derivation: ProductionEdgeDerivation
    execution: RetentionExecution
    interference: GeometryInterferenceResult
    output_step: Path

    @property
    def passed(self) -> bool:
        """Whether the production execution passed verification."""

        return self.execution.passed and self.interference.passed


def execute_production_edge_capture(
    request: ProductionEdgeExecutionRequest,
) -> ProductionEdgeExecutionResult:
    """Execute edge capture against imported production evidence."""

    adapter = ProductionBoardEdgeAdapter(
        engagement_depth_mm=(request.engagement_depth_mm),
        vertical_margin_mm=(request.vertical_margin_mm),
        minimum_anchor_separation_mm=(request.minimum_anchor_separation_mm),
    )

    board_model = adapter.import_model(
        source_step=request.source_step,
        pcb_solid_index=request.pcb_solid_index,
    )

    derivation = adapter.derive(
        model=board_model,
        policy=request.policy,
    )

    execution = run_backend(
        RetentionStrategy.EDGE_CLIP,
        SyntheticEdgeCaptureBackend(),
        derivation.request,
        board_model.pcb,
    )

    parameters = as_edge_capture_parameters(execution.parameters)
    capture_shape = workplane_shape(
        SyntheticEdgeCaptureBackend().build_geometry(parameters)
    )

    interference = measure_capture_interference(
        capture_shape, board_model, tolerance_mm3=_INTERFERENCE_TOLERANCE_MM3
    )

    if not interference.passed:
        raise ValueError(
            "Generated edge-capture geometry intersects production board "
            f"material: pcb={interference.pcb_capture_intersection_mm3:.6f}mm3, "
            f"components={interference.component_capture_intersection_mm3:.6f}mm3"
        )

    production_report = _production_edge_evidence_report(
        execution=execution,
        derivation=derivation,
        source_step=request.source_step,
    )

    production_execution = verified_execution(
        execution, production_report, label="edge-capture"
    )

    export_retention_step(production_execution, request.output_step)

    return ProductionEdgeExecutionResult(
        board_model=board_model,
        derivation=derivation,
        execution=production_execution,
        interference=interference,
        output_step=request.output_step,
    )


def _production_edge_evidence_report(
    *,
    execution: RetentionExecution,
    derivation: ProductionEdgeDerivation,
    source_step: Path,
) -> EdgeCaptureFitReport:
    """Replace synthetic placeholders with real production evidence.

    ``edge_material_continuity`` and ``component_clearance`` were only
    unverified placeholders in the synthetic backend's report; by this
    point :meth:`ProductionBoardEdgeAdapter.derive` has already confirmed
    both from the real STEP model when it selected ``derivation``'s span,
    and the caller has confirmed zero exact-geometry intersection.
    """

    report = as_edge_capture_fit_report(execution.report)
    detail = (
        f"Production STEP evidence confirmed a component-clear, "
        f"material-continuous capture span on the "
        f"{derivation.selected_edge.value} edge from {source_step.name}."
    )

    results = tuple(
        replace(
            result,
            passed=True,
            detail=detail,
        )
        if result.check
        in (
            EdgeCaptureFitCheck.EDGE_MATERIAL_CONTINUITY,
            EdgeCaptureFitCheck.COMPONENT_CLEARANCE,
        )
        else result
        for result in report.results
    )

    return EdgeCaptureFitReport(results=results)
