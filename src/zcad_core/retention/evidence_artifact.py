from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.backend import (
    CornerCaptureFitCheck,
    as_corner_capture_fit_report,
)
from zcad_core.retention.capture_interference import (
    GeometryInterferenceResult,
    measure_capture_interference,
)
from zcad_core.retention.corner_capture import (
    as_corner_capture_parameters,
)
from zcad_core.retention.evidence_report import (
    evidence_report,
    require_manufacturing,
    write_evidence_report,
)
from zcad_core.retention.manufacturing import (
    ManufacturingPolicy,
    ManufacturingReport,
    validate_corner_capture_manufacturing,
)
from zcad_core.retention.production_execution import (
    ProductionCornerExecutionRequest,
    ProductionCornerExecutionResult,
    execute_production_corner_capture,
)
from zcad_core.retention.synthetic_backend import (
    SyntheticCornerCaptureBackend,
)


@dataclass(frozen=True)
class ProductionEvidenceArtifact:
    """Durable evidence files for one production retention run."""

    step_path: Path
    report_path: Path
    execution: ProductionCornerExecutionResult
    interference: GeometryInterferenceResult

    @property
    def passed(self) -> bool:
        """Whether execution and interference verification passed."""

        return self.execution.passed and self.interference.passed


def generate_production_evidence_artifact(
    request: ProductionCornerExecutionRequest,
    *,
    report_path: Path,
    manufacturing_policy: ManufacturingPolicy | None = None,
) -> ProductionEvidenceArtifact:
    """Execute, verify, and record production retention evidence."""

    execution = execute_production_corner_capture(request)

    interference = analyze_capture_interference(execution)

    if not interference.passed:
        raise ValueError(
            "Generated capture geometry intersects production board material"
        )

    manufacturing = validate_corner_capture_manufacturing(
        as_corner_capture_parameters(execution.execution.parameters),
        policy=(manufacturing_policy or ManufacturingPolicy()),
    )
    require_manufacturing(manufacturing)

    write_evidence_report(
        build_evidence_report(
            execution=execution,
            interference=interference,
            manufacturing=manufacturing,
        ),
        report_path,
        generation={
            "corner_keepout_mm": request.corner_keepout_mm,
            "vertical_margin_mm": request.vertical_margin_mm,
        },
    )

    return ProductionEvidenceArtifact(
        step_path=execution.output_step,
        report_path=report_path,
        execution=execution,
        interference=interference,
    )


def analyze_capture_interference(
    execution: ProductionCornerExecutionResult,
) -> GeometryInterferenceResult:
    """Measure capture-only intersection with PCB and components."""

    parameters = as_corner_capture_parameters(execution.execution.parameters)

    return measure_capture_interference(
        workplane_shape(SyntheticCornerCaptureBackend().build_geometry(parameters)),
        execution.board_model,
    )


def build_evidence_report(
    *,
    execution: ProductionCornerExecutionResult,
    interference: GeometryInterferenceResult,
    manufacturing: ManufacturingReport,
) -> dict[str, object]:
    """Build a deterministic, inspectable evidence record."""

    return evidence_report(
        execution_passed=execution.passed,
        board_model=execution.board_model,
        output_step=execution.output_step,
        fit_results=as_corner_capture_fit_report(execution.execution.report).results,
        required_checks=CornerCaptureFitCheck,
        parameters=as_corner_capture_parameters(execution.execution.parameters),
        interference=interference,
        manufacturing=manufacturing,
        selection={
            "selected_corners": [
                corner.value for corner in execution.derivation.selected_corners
            ],
        },
    )


def recorded_generation_parameters(evidence_path: Path) -> dict[str, float]:
    """The adapter settings a candidate's automated evidence recorded.

    Evidence written before these were recorded, or missing entirely, yields
    an empty mapping, so callers can tell "not recorded" from any recorded
    value.
    """

    if not evidence_path.is_file():
        return {}

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    generation = payload.get("generation") if isinstance(payload, dict) else None

    if not isinstance(generation, dict):
        return {}

    return {
        str(name): float(value)
        for name, value in generation.items()
        if isinstance(value, int | float)
    }
