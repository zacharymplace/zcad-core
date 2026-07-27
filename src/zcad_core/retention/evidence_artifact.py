from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cadquery as cq

from zcad_core.retention.backend import (
    CornerCaptureFitCheck,
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
class GeometryInterferenceResult:
    """Intersection measurements for one production execution."""

    pcb_capture_intersection_mm3: float
    component_capture_intersection_mm3: float
    tolerance_mm3: float = 1e-6

    @property
    def passed(self) -> bool:
        """Whether captures avoid PCB and component material."""

        return (
            self.pcb_capture_intersection_mm3 <= self.tolerance_mm3
            and self.component_capture_intersection_mm3 <= self.tolerance_mm3
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

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    manufacturing = validate_corner_capture_manufacturing(
        execution.execution.parameters,
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

    report = build_evidence_report(
        execution=execution,
        interference=interference,
        manufacturing=manufacturing,
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

    parameters = execution.execution.parameters

    capture_shape = SyntheticCornerCaptureBackend().build_geometry(parameters).val()

    if capture_shape is None:
        raise ValueError("Production execution contains no capture geometry")

    pcb_intersection = _intersection_volume(
        capture_shape,
        execution.board_model.pcb,
    )

    component_intersection = sum(
        _intersection_volume(
            capture_shape,
            component,
        )
        for component in (execution.board_model.component_solids)
    )

    return GeometryInterferenceResult(
        pcb_capture_intersection_mm3=(pcb_intersection),
        component_capture_intersection_mm3=(component_intersection),
    )


def build_evidence_report(
    *,
    execution: ProductionCornerExecutionResult,
    interference: GeometryInterferenceResult,
    manufacturing: ManufacturingReport,
) -> dict[str, object]:
    """Build a deterministic, inspectable evidence record."""

    source_step = execution.board_model.source_step
    source_sha256 = _sha256(source_step)
    output_sha256 = _sha256(execution.output_step)

    pcb_bounds = execution.board_model.pcb.BoundingBox()

    parameters = execution.execution.parameters

    fit_results = {
        result.check.value: {
            "passed": result.passed,
            "detail": result.detail,
        }
        for result in (execution.execution.report.results)
    }

    required_checks = {check.value for check in CornerCaptureFitCheck}

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
        "selected_corners": [
            corner.value for corner in (execution.derivation.selected_corners)
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


def _intersection_volume(
    first: cq.Shape,
    second: cq.Shape,
) -> float:
    intersection = first.intersect(second)

    if intersection.isNull():
        return 0.0

    return float(intersection.Volume())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()
