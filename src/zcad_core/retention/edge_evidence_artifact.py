from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from zcad_core.retention.edge_backend import (
    EdgeCaptureFitCheck,
    as_edge_capture_fit_report,
)
from zcad_core.retention.edge_capture import (
    as_edge_capture_parameters,
)
from zcad_core.retention.evidence_artifact import GeometryInterferenceResult
from zcad_core.retention.generator import GENERATOR_VERSION
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

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    parameters = as_edge_capture_parameters(execution.execution.parameters)

    manufacturing = validate_edge_capture_manufacturing(
        parameters,
        policy=(manufacturing_policy or ManufacturingPolicy()),
    )

    if not manufacturing.passed:
        failed_checks = ", ".join(
            result.check.value for result in manufacturing.failures
        )

        raise ValueError(
            "Generated capture geometry failed "
            f"manufacturing validation: {failed_checks}"
        )

    report = build_edge_evidence_report(
        execution=execution,
        interference=interference,
        manufacturing=manufacturing,
    )
    report["generator_version"] = GENERATOR_VERSION
    report["generation"] = {
        "engagement_depth_mm": request.engagement_depth_mm,
        "vertical_margin_mm": request.vertical_margin_mm,
    }

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
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

    source_step = execution.board_model.source_step
    source_sha256 = _sha256(source_step)
    output_sha256 = _sha256(execution.output_step)

    pcb_bounds = execution.board_model.pcb.BoundingBox()

    parameters = as_edge_capture_parameters(execution.execution.parameters)
    report = as_edge_capture_fit_report(execution.execution.report)

    fit_results = {
        result.check.value: {
            "passed": result.passed,
            "detail": result.detail,
        }
        for result in report.results
    }

    required_checks = {check.value for check in EdgeCaptureFitCheck}

    observed_checks = set(fit_results)

    return {
        "schema_version": "1.0.0",
        "generated_at_utc": (datetime.now(UTC).isoformat()),
        "decision": (
            "verified_candidate"
            if execution.passed
            and interference.passed
            and manufacturing.passed
            and observed_checks == required_checks
            else "rejected"
        ),
        "source": {
            "step_path": str(source_step),
            "step_sha256": source_sha256,
            "pcb_solid_index": (execution.board_model.pcb_solid_index),
        },
        "output": {
            "step_path": str(execution.output_step),
            "step_sha256": output_sha256,
        },
        "pcb": {
            "x_length_mm": pcb_bounds.xlen,
            "y_length_mm": pcb_bounds.ylen,
            "z_length_mm": pcb_bounds.zlen,
            "component_solid_count": len(execution.board_model.component_solids),
        },
        "selected_corners": [execution.derivation.selected_edge.value],
        "selected_edge": execution.derivation.selected_edge.value,
        "capture_locations": [
            {
                "edge": location.edge.value,
                "position_mm": location.position_mm,
                "edge_coordinate_mm": location.edge_coordinate_mm,
            }
            for location in execution.derivation.request.locations
        ],
        "policy": {
            "arm_width_mm": (parameters.arm_width_mm),
            "engagement_depth_mm": (parameters.engagement_depth_mm),
            "board_clearance_mm": (parameters.board_clearance_mm),
            "vertical_overlap_mm": (parameters.vertical_overlap_mm),
            "minimum_wall_mm": (parameters.minimum_wall_mm),
        },
        "fit_checks": fit_results,
        "interference": {
            "passed": interference.passed,
            "pcb_capture_intersection_mm3": (interference.pcb_capture_intersection_mm3),
            "component_capture_intersection_mm3": (
                interference.component_capture_intersection_mm3
            ),
            "tolerance_mm3": (interference.tolerance_mm3),
        },
        "manufacturing": {
            "passed": manufacturing.passed,
            "checks": {
                result.check.value: {
                    "passed": result.passed,
                    "measured_value": (result.measured_value),
                    "required_value": (result.required_value),
                    "detail": result.detail,
                }
                for result in manufacturing.results
            },
        },
        "metadata_publication": {
            "approved": False,
            "reason": (
                "Visual inspection and physical fit validation are still required."
            ),
        },
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()
