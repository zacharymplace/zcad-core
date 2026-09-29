from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zcad_core.retention.edge_backend import (
    EdgeCaptureFitCheck,
    as_edge_capture_fit_report,
)
from zcad_core.retention.edge_capture import (
    as_edge_capture_parameters,
)
from zcad_core.retention.evidence_artifact import GeometryInterferenceResult
from zcad_core.retention.evidence_report import (
    evidence_report,
    require_manufacturing,
    write_evidence_report,
)
from zcad_core.retention.manufacturing import (
    ManufacturingPolicy,
    ManufacturingReport,
    validate_edge_capture_manufacturing,
)
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionRequest,
    ProductionEdgeExecutionResult,
    execute_production_edge_capture,
)


@dataclass(frozen=True)
class ProductionEdgeEvidenceArtifact:
    """Durable evidence files for one production edge-capture retention run."""

    step_path: Path
    report_path: Path
    execution: ProductionEdgeExecutionResult
    interference: GeometryInterferenceResult

    @property
    def passed(self) -> bool:
        """Whether execution and interference verification passed."""

        return self.execution.passed and self.interference.passed


def generate_production_edge_evidence_artifact(
    request: ProductionEdgeExecutionRequest,
    *,
    report_path: Path,
    manufacturing_policy: ManufacturingPolicy | None = None,
) -> ProductionEdgeEvidenceArtifact:
    """Execute, verify, and record production edge-capture retention evidence.

    :func:`~zcad_core.retention.production_edge_execution.execute_production_edge_capture`
    already computes and fails closed on exact-geometry interference against
    the real PCB and every component solid; this layer reuses that result
    rather than recomputing it, then adds manufacturing validation and
    writes the inspectable JSON report - mirroring
    :func:`~zcad_core.retention.evidence_artifact.generate_production_evidence_artifact`'s
    corner-capture structure.
    """

    execution = execute_production_edge_capture(request)
    interference = execution.interference

    manufacturing = validate_edge_capture_manufacturing(
        as_edge_capture_parameters(execution.execution.parameters),
        policy=(manufacturing_policy or ManufacturingPolicy()),
    )
    require_manufacturing(manufacturing)

    write_evidence_report(
        build_edge_evidence_report(
            execution=execution,
            interference=interference,
            manufacturing=manufacturing,
        ),
        report_path,
        generation={
            "engagement_depth_mm": request.engagement_depth_mm,
            "vertical_margin_mm": request.vertical_margin_mm,
        },
    )

    return ProductionEdgeEvidenceArtifact(
        step_path=execution.output_step,
        report_path=report_path,
        execution=execution,
        interference=interference,
    )


def build_edge_evidence_report(
    *,
    execution: ProductionEdgeExecutionResult,
    interference: GeometryInterferenceResult,
    manufacturing: ManufacturingReport,
) -> dict[str, object]:
    """Build a deterministic, inspectable evidence record.

    ``selected_corners`` is populated with the selected edge's name (a
    single-item list) to keep the same JSON shape corner-capture's
    evidence report produces, so callers that read it generically (the
    ``zcad-validation candidate register`` CLI command) do not need a
    strategy-specific parsing path. ``selected_edge`` and
    ``capture_locations`` carry the same information with honest field
    names for anything reading this report directly.
    """

    derivation = execution.derivation

    return evidence_report(
        execution_passed=execution.passed,
        board_model=execution.board_model,
        output_step=execution.output_step,
        fit_results=as_edge_capture_fit_report(execution.execution.report).results,
        required_checks=EdgeCaptureFitCheck,
        parameters=as_edge_capture_parameters(execution.execution.parameters),
        interference=interference,
        manufacturing=manufacturing,
        selection={
            "selected_corners": [derivation.selected_edge.value],
            "selected_edge": derivation.selected_edge.value,
            "capture_locations": [
                {
                    "edge": location.edge.value,
                    "position_mm": location.position_mm,
                    "edge_coordinate_mm": location.edge_coordinate_mm,
                }
                for location in derivation.request.locations
            ],
        },
    )
