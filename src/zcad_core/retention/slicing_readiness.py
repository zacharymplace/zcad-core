from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape


class SlicingReadinessCheck(str, Enum):
    """Required pre-slice readiness checks."""

    FIXTURE_ARTIFACT_EXISTS = "fixture_artifact_exists"
    BUILD_VOLUME_FIT = "build_volume_fit"
    PRINTER_PROFILE_MATCH = "printer_profile_match"
    MATERIAL_PROFILE_MATCH = "material_profile_match"
    MATERIAL_SUPPORTED = "material_supported"
    NOZZLE_MATCH = "nozzle_match"
    BASE_DOWN_ORIENTATION = "base_down_orientation"
    SLICE_METRICS_PENDING = "slice_metrics_pending"


@dataclass(frozen=True)
class SlicingReadinessResult:
    """One pre-slice readiness result."""

    check: SlicingReadinessCheck
    passed: bool
    detail: str


@dataclass(frozen=True)
class SlicingReadinessReport:
    """Fail-closed readiness packet for slicing."""

    schema_version: str
    candidate_id: str
    fixture_artifact_path: str
    printer_profile_id: str
    material_profile_id: str
    slicer_profile_id: str
    fixture_bounds_mm: dict[str, float]
    build_volume_mm: dict[str, float]
    build_margin_mm: dict[str, float]
    results: tuple[SlicingReadinessResult, ...]
    slice_completed: bool
    physical_validation_satisfied: bool

    @property
    def ready_for_slicing(self) -> bool:
        """Whether the fixture may enter a slicer."""

        return (
            bool(self.results)
            and all(result.passed for result in self.results)
            and not self.slice_completed
            and not self.physical_validation_satisfied
        )


def _positive_number(
    mapping: dict[str, Any],
    key: str,
) -> float:
    value = mapping.get(key)

    if not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{key} must be greater than zero")

    return float(value)


def evaluate_slicing_readiness(
    *,
    candidate_id: str,
    fixture_model: cq.Workplane,
    fixture_artifact_path: Path,
    printer_profile: dict[str, Any],
    material_profile: dict[str, Any],
    slicer_profile: dict[str, Any],
) -> SlicingReadinessReport:
    """Evaluate readiness without claiming a slice."""

    if not candidate_id.strip():
        raise ValueError("candidate_id cannot be empty")

    shape = workplane_shape(fixture_model)

    if shape.isNull():
        raise ValueError("Fixture model contains no geometry")

    bounds = shape.BoundingBox()
    fixture_bounds = {
        "x": round(bounds.xlen, 3),
        "y": round(bounds.ylen, 3),
        "z": round(bounds.zlen, 3),
    }

    raw_build_volume = printer_profile.get("build_volume_mm")

    if not isinstance(raw_build_volume, dict):
        raise TypeError("build_volume_mm must be an object")

    build_volume = {
        axis: _positive_number(
            raw_build_volume,
            axis,
        )
        for axis in ("x", "y", "z")
    }
    build_margin = {
        axis: round(
            build_volume[axis] - fixture_bounds[axis],
            3,
        )
        for axis in ("x", "y", "z")
    }
    build_fit = all(margin >= 0 for margin in build_margin.values())

    printer_id = str(printer_profile.get("profile_id", ""))
    material_id = str(material_profile.get("profile_id", ""))
    slicer_id = str(slicer_profile.get("profile_id", ""))

    slicer_printer_match = slicer_profile.get("printer_profile_id") == printer_id
    slicer_material_match = slicer_profile.get("material_profile_id") == material_id

    supported_materials = printer_profile.get(
        "supported_material_profile_ids",
        [],
    )
    material_supported = (
        isinstance(supported_materials, list) and material_id in supported_materials
    )

    printer_nozzle = printer_profile.get("configured_nozzle_diameter_mm")
    slicer_nozzle = slicer_profile.get("nozzle_diameter_mm")
    nozzle_match = (
        isinstance(
            printer_nozzle,
            int | float,
        )
        and isinstance(
            slicer_nozzle,
            int | float,
        )
        and float(printer_nozzle) == float(slicer_nozzle)
    )

    orientation_passed = slicer_profile.get("orientation") == "base_down"
    slice_completed = slicer_profile.get("slice_completed") is True
    metrics_pending = (
        not slice_completed
        and slicer_profile.get("estimated_print_time_seconds") is None
        and slicer_profile.get("estimated_material_grams") is None
    )

    results = (
        SlicingReadinessResult(
            check=(SlicingReadinessCheck.FIXTURE_ARTIFACT_EXISTS),
            passed=fixture_artifact_path.is_file(),
            detail=(
                "Fixture STL exists."
                if fixture_artifact_path.is_file()
                else "Fixture STL is missing."
            ),
        ),
        SlicingReadinessResult(
            check=(SlicingReadinessCheck.BUILD_VOLUME_FIT),
            passed=build_fit,
            detail=(
                "Fixture fits the declared build volume."
                if build_fit
                else "Fixture exceeds the declared build volume."
            ),
        ),
        SlicingReadinessResult(
            check=(SlicingReadinessCheck.PRINTER_PROFILE_MATCH),
            passed=slicer_printer_match,
            detail=(
                "Slicer and printer profiles match."
                if slicer_printer_match
                else "Slicer and printer profile IDs do not match."
            ),
        ),
        SlicingReadinessResult(
            check=(SlicingReadinessCheck.MATERIAL_PROFILE_MATCH),
            passed=slicer_material_match,
            detail=(
                "Slicer and material profiles match."
                if slicer_material_match
                else "Slicer and material profile IDs do not match."
            ),
        ),
        SlicingReadinessResult(
            check=(SlicingReadinessCheck.MATERIAL_SUPPORTED),
            passed=material_supported,
            detail=(
                "Material is declared compatible."
                if material_supported
                else "Material is not declared compatible."
            ),
        ),
        SlicingReadinessResult(
            check=SlicingReadinessCheck.NOZZLE_MATCH,
            passed=nozzle_match,
            detail=(
                "Configured nozzle diameters match."
                if nozzle_match
                else "Configured nozzle diameters do not match."
            ),
        ),
        SlicingReadinessResult(
            check=(SlicingReadinessCheck.BASE_DOWN_ORIENTATION),
            passed=orientation_passed,
            detail=(
                "Base-down orientation is planned."
                if orientation_passed
                else "Base-down orientation is required."
            ),
        ),
        SlicingReadinessResult(
            check=(SlicingReadinessCheck.SLICE_METRICS_PENDING),
            passed=metrics_pending,
            detail=(
                "Slice metrics remain pending."
                if metrics_pending
                else "Pre-slice metrics must remain null."
            ),
        ),
    )

    return SlicingReadinessReport(
        schema_version="1.0.0",
        candidate_id=candidate_id,
        fixture_artifact_path=str(fixture_artifact_path),
        printer_profile_id=printer_id,
        material_profile_id=material_id,
        slicer_profile_id=slicer_id,
        fixture_bounds_mm=fixture_bounds,
        build_volume_mm=build_volume,
        build_margin_mm=build_margin,
        results=results,
        slice_completed=slice_completed,
        physical_validation_satisfied=False,
    )


def write_slicing_readiness_report(
    report: SlicingReadinessReport,
    *,
    output_path: Path,
) -> None:
    """Write an immutable slicing-readiness report."""

    payload = asdict(report)
    payload["ready_for_slicing"] = report.ready_for_slicing
    serialized = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")

        if existing == serialized:
            return

        raise FileExistsError(
            f"Refusing to overwrite immutable slicing-readiness report: {output_path}"
        )

    output_path.write_text(
        serialized,
        encoding="utf-8",
    )
