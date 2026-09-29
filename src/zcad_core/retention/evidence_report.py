"""The automated-evidence record shared by corner capture and edge clip.

Both strategies write the same JSON shape; each supplies only its fit
results, required checks, and how it names the selected capture locations.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from zcad_core.retention.capture_interference import GeometryInterferenceResult
from zcad_core.retention.generator import GENERATOR_VERSION
from zcad_core.retention.manufacturing import ManufacturingReport
from zcad_core.retention.production_board import ProductionBoardModel
from zcad_core.retention.validation_lab import sha256_file

POLICY_FIELDS = (
    "arm_width_mm",
    "engagement_depth_mm",
    "board_clearance_mm",
    "vertical_overlap_mm",
    "minimum_wall_mm",
)


class _FitResult(Protocol):
    @property
    def check(self) -> object: ...
    @property
    def passed(self) -> bool: ...
    @property
    def detail(self) -> str: ...


def require_manufacturing(manufacturing: ManufacturingReport) -> None:
    """Refuse generated geometry that fails manufacturing validation."""

    if not manufacturing.passed:
        failed_checks = ", ".join(
            result.check.value for result in manufacturing.failures
        )

        raise ValueError(
            "Generated capture geometry failed "
            f"manufacturing validation: {failed_checks}"
        )


def evidence_report(
    *,
    execution_passed: bool,
    board_model: ProductionBoardModel,
    output_step: Path,
    fit_results: Iterable[_FitResult],
    required_checks: Iterable[object],
    parameters: object,
    interference: GeometryInterferenceResult,
    manufacturing: ManufacturingReport,
    selection: dict[str, object],
) -> dict[str, object]:
    """Build a deterministic, inspectable evidence record."""

    pcb_bounds = board_model.pcb.BoundingBox()
    fit_checks = {
        _value(result.check): {"passed": result.passed, "detail": result.detail}
        for result in fit_results
    }

    return {
        "schema_version": "1.0.0",
        "generated_at_utc": (datetime.now(UTC).isoformat()),
        "decision": (
            "verified_candidate"
            if execution_passed
            and interference.passed
            and manufacturing.passed
            and set(fit_checks) == {_value(check) for check in required_checks}
            else "rejected"
        ),
        "source": {
            "step_path": str(board_model.source_step),
            "step_sha256": sha256_file(board_model.source_step),
            "pcb_solid_index": board_model.pcb_solid_index,
        },
        "output": {
            "step_path": str(output_step),
            "step_sha256": sha256_file(output_step),
        },
        "pcb": {
            "x_length_mm": pcb_bounds.xlen,
            "y_length_mm": pcb_bounds.ylen,
            "z_length_mm": pcb_bounds.zlen,
            "component_solid_count": len(board_model.component_solids),
        },
        **selection,
        "policy": {name: getattr(parameters, name) for name in POLICY_FIELDS},
        "fit_checks": fit_checks,
        "interference": {
            "passed": interference.passed,
            "pcb_capture_intersection_mm3": interference.pcb_capture_intersection_mm3,
            "component_capture_intersection_mm3": (
                interference.component_capture_intersection_mm3
            ),
            "tolerance_mm3": interference.tolerance_mm3,
        },
        "manufacturing": {
            "passed": manufacturing.passed,
            "checks": {
                result.check.value: {
                    "passed": result.passed,
                    "measured_value": result.measured_value,
                    "required_value": result.required_value,
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


def write_evidence_report(
    report: dict[str, object],
    report_path: Path,
    *,
    generation: dict[str, float],
) -> None:
    """Stamp the generator and the settings that chose the capture locations,
    so the candidate can be regenerated exactly, then write the report."""

    report["generator_version"] = GENERATOR_VERSION
    report["generation"] = generation
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _value(check: object) -> str:
    return str(getattr(check, "value", check))
