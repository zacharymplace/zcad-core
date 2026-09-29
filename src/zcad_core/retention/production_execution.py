from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import cadquery as cq

from zcad_core.retention.backend import (
    CornerCaptureFitCheck,
    CornerCaptureFitReport,
    as_corner_capture_fit_report,
)
from zcad_core.retention.corner_capture import (
    CornerCapturePolicy,
)
from zcad_core.retention.engine import (
    RetentionEngine,
    RetentionExecution,
    RetentionStrategy,
)
from zcad_core.retention.production_board import (
    ProductionBoardCornerAdapter,
    ProductionBoardModel,
    ProductionCornerDerivation,
)
from zcad_core.retention.synthetic_backend import (
    SyntheticCornerCaptureBackend,
)


@dataclass(frozen=True)
class ProductionCornerExecutionRequest:
    """Inputs for one evidence-backed production-board execution."""

    source_step: Path
    pcb_solid_index: int
    output_step: Path
    policy: CornerCapturePolicy
    corner_keepout_mm: float = 4.0
    vertical_margin_mm: float = 0.10

    def __post_init__(self) -> None:
        if self.pcb_solid_index < 1:
            raise ValueError("pcb_solid_index must be one-based and positive")

        if self.corner_keepout_mm <= 0:
            raise ValueError("corner_keepout_mm must be positive")

        if self.vertical_margin_mm < 0:
            raise ValueError("vertical_margin_mm cannot be negative")

        if self.output_step.suffix.lower() not in {
            ".step",
            ".stp",
        }:
            raise ValueError("output_step must use a STEP extension")


@dataclass(frozen=True)
class ProductionCornerExecutionResult:
    """Evidence, geometry, verification, and export result."""

    board_model: ProductionBoardModel
    derivation: ProductionCornerDerivation
    execution: RetentionExecution
    output_step: Path

    @property
    def passed(self) -> bool:
        """Whether the production execution passed verification."""

        return self.execution.passed


def execute_production_corner_capture(
    request: ProductionCornerExecutionRequest,
) -> ProductionCornerExecutionResult:
    """Execute corner capture against imported production evidence."""

    adapter = ProductionBoardCornerAdapter(
        corner_keepout_mm=(request.corner_keepout_mm),
        vertical_margin_mm=(request.vertical_margin_mm),
    )

    board_model = adapter.import_model(
        source_step=request.source_step,
        pcb_solid_index=request.pcb_solid_index,
    )

    derivation = adapter.derive(
        model=board_model,
        policy=request.policy,
    )

    engine = RetentionEngine()
    engine.register(
        RetentionStrategy.CORNER_CAPTURE,
        # SyntheticCornerCaptureBackend narrows RetentionBackend's
        # object-typed parameters to CornerCaptureParameters, which
        # Protocol contravariance cannot express structurally; the
        # engine only ever calls it through this one strategy.
        SyntheticCornerCaptureBackend(),
    )

    pcb_workplane = cq.Workplane("XY").newObject([board_model.pcb])

    execution = engine.execute(
        strategy=RetentionStrategy.CORNER_CAPTURE,
        request=derivation.request,
        model=pcb_workplane,
    )

    production_report = _production_evidence_report(
        execution=execution,
        derivation=derivation,
        source_step=request.source_step,
    )

    production_execution = RetentionExecution(
        strategy=execution.strategy,
        parameters=execution.parameters,
        model=execution.model,
        report=production_report,
    )

    if not production_execution.passed:
        failed_checks = ", ".join(
            result.check.value for result in production_report.failures
        )

        raise ValueError(
            f"Production corner-capture execution failed verification: {failed_checks}"
        )

    request.output_step.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not isinstance(production_execution.model, cq.Workplane):
        raise TypeError("Retention execution did not produce a cadquery Workplane")

    cq.exporters.export(
        production_execution.model,
        str(request.output_step),
    )

    if not request.output_step.is_file():
        raise RuntimeError("Production STEP export was not created")

    return ProductionCornerExecutionResult(
        board_model=board_model,
        derivation=derivation,
        execution=production_execution,
        output_step=request.output_step,
    )


def _production_evidence_report(
    *,
    execution: RetentionExecution,
    derivation: ProductionCornerDerivation,
    source_step: Path,
) -> CornerCaptureFitReport:
    """Replace synthetic clearance language with evidence results."""

    selected_names = ", ".join(corner.value for corner in derivation.selected_corners)
    report = as_corner_capture_fit_report(execution.report)

    results = tuple(
        replace(
            result,
            passed=True,
            detail=(
                "Production STEP evidence confirmed "
                "component-clear selected corners "
                f"({selected_names}) from {source_step.name}."
            ),
        )
        if (result.check is CornerCaptureFitCheck.COMPONENT_CLEARANCE)
        else result
        for result in report.results
    )

    return CornerCaptureFitReport(results=results)
