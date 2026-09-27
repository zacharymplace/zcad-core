"""Product-agnostic STEP, STL, and metadata export service."""

import hashlib
import json
import re
import tempfile
from pathlib import Path

import cadquery as cq
from zcad_core.exporters.models import (
    ExportedPart,
    ExportRequest,
    ExportResult,
)
from zcad_core.exporters.publication import publish_files
from zcad_core.metadata.build_record import build_part_record
from zcad_core.validation.design_report import (
    DesignValidationError,
    report_from_geometry,
)
from zcad_core.validation.export_geometry import (
    InspectedGeometry,
    inspect_export_geometry,
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _validate_name(
    *,
    field: str,
    value: str,
) -> None:
    if not _SAFE_NAME.fullmatch(value):
        raise ValueError(
            f"{field} may contain only letters, numbers, hyphens, and underscores"
        )


def _output_stem(
    *,
    design_name: str,
    part_name: str,
    part_count: int,
) -> str:
    if part_count == 1 and part_name == "main":
        return design_name

    return f"{design_name}-{part_name}"


def _validate_parts(
    parts: dict[str, cq.Workplane],
) -> dict[str, InspectedGeometry]:
    if not parts:
        raise ValueError("Export request contains no parts")

    inspected = {}
    for part_name, model in parts.items():
        _validate_name(
            field="part_name",
            value=part_name,
        )

        inspected[part_name] = inspect_export_geometry(model, part_name)
    return inspected


def _feature_checks(request, inspected):
    try:
        checks = request.feature_validator(
            design_type=request.design_type,
            parts={
                name: cq.Workplane().newObject([geometry.shape.copy()])
                for name, geometry in inspected.items()
            },
            parameters=request.parameters or {},
        )
        if (
            not isinstance(checks, list)
            or not checks
            or any(
                not isinstance(check, dict)
                or not isinstance(check.get("code"), str)
                or not isinstance(check.get("message"), str)
                or check.get("status") not in {"PASS", "FAIL", "NOT_CHECKED"}
                for check in checks
            )
        ):
            raise ValueError("Invalid feature-check results")
        json.dumps(checks, allow_nan=False)
    except Exception as error:
        checks = [
            {
                "code": "feature_validation",
                "status": "FAIL",
                "message": (
                    f"Feature validation error: {type(error).__name__}: {error}"
                ),
            }
        ]
    return checks


def _prepare_exports(
    request: ExportRequest,
    staging: Path,
) -> ExportResult:
    """Export all requested parts and their metadata."""
    _validate_name(
        field="design_name",
        value=request.design_name,
    )
    _validate_name(
        field="design_type",
        value=request.design_type,
    )
    inspected = _validate_parts(request.parts)
    validation_report = report_from_geometry(
        design_name=request.design_name,
        design_type=request.design_type,
        geometry=inspected,
        printer_profile=request.printer_profile,
        parameters=request.parameters,
    )
    if request.feature_validator is not None:
        checks = _feature_checks(request, inspected)
        validation_report["checks"].extend(checks)
        validation_report["scope"] += "; application feature checks (see check details)"
        if any(check["status"] == "FAIL" for check in checks):
            validation_report["evaluated_status"] = "FAIL"
    if validation_report["evaluated_status"] == "FAIL":
        raise DesignValidationError(validation_report)

    staged_steps = {}
    if request.feature_validator is not None:
        try:
            with tempfile.TemporaryDirectory(prefix="zcad-step-check-") as folder:
                imported = {}
                for index, (name, geometry) in enumerate(inspected.items()):
                    path = Path(folder) / f"part-{index}.step"
                    cq.exporters.export(geometry.shape, str(path))
                    staged_steps[name] = path.read_bytes()
                    imported[name] = inspect_export_geometry(
                        cq.importers.importStep(str(path)), name
                    )
                roundtrip_checks = _feature_checks(request, imported)
        except Exception as error:
            roundtrip_checks = [
                {
                    "code": "step_reimport",
                    "status": "FAIL",
                    "message": (
                        f"STEP round-trip error: {type(error).__name__}: {error}"
                    ),
                }
            ]
        failed = any(c["status"] == "FAIL" for c in roundtrip_checks)
        status = (
            "FAIL"
            if failed
            else (
                "PASS"
                if any(c["status"] == "PASS" for c in roundtrip_checks)
                else "NOT_CHECKED"
            )
        )
        validation_report["step_round_trip"] = {
            "status": status,
            "scope": "Reimported STEP features; not STL or full shape equivalence",
            "checks": roundtrip_checks,
            "step_sha256_by_part": {
                name: hashlib.sha256(data).hexdigest()
                for name, data in staged_steps.items()
            },
        }
        if failed:
            validation_report["evaluated_status"] = "FAIL"
            validation_report["checks"].append(
                {
                    "code": "step_round_trip",
                    "status": "FAIL",
                    "message": "Reimported STEP failed validation; see step_round_trip",
                }
            )
            raise DesignValidationError(validation_report)

    exported: list[ExportedPart] = []
    part_count = len(request.parts)

    for part_name, geometry in inspected.items():
        bounds_mm = geometry.bounds_mm
        volume_mm3 = geometry.volume_mm3
        valid_solid = True

        stem = _output_stem(
            design_name=request.design_name,
            part_name=part_name,
            part_count=part_count,
        )

        step_path = request.output_directory / f"{stem}.step"
        stl_path = request.output_directory / f"{stem}.stl"
        metadata_path = request.output_directory / f"{stem}.metadata.json"
        staged_step = staging / step_path.name
        staged_stl = staging / stl_path.name
        staged_metadata = staging / metadata_path.name

        if part_name in staged_steps:
            staged_step.write_bytes(staged_steps[part_name])
        else:
            cq.exporters.export(geometry.shape, str(staged_step))
        cq.exporters.export(
            geometry.shape,
            str(staged_stl),
        )

        record = build_part_record(
            design_name=request.design_name,
            design_type=request.design_type,
            part_name=part_name,
            valid_solid=valid_solid,
            volume_mm3=volume_mm3,
            bounds_mm=bounds_mm,
            step_path=step_path,
            stl_path=stl_path,
            printer_profile=(request.printer_profile),
            material_profile=(request.material_profile),
            repository_root=(request.repository_root),
        )

        record["validation"] = geometry.report
        record["design_validation"] = validation_report
        staged_metadata.write_text(
            json.dumps(
                record,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        exported.append(
            ExportedPart(
                part_name=part_name,
                stem=stem,
                step_path=step_path,
                stl_path=stl_path,
                metadata_path=metadata_path,
                volume_mm3=volume_mm3,
                bounds_mm=bounds_mm,
            )
        )

    return ExportResult(
        design_name=request.design_name,
        parts=tuple(exported),
        validation_report=validation_report,
    )


def export_parts(request: ExportRequest) -> ExportResult:
    """Prepare all artifacts before publishing with caught-failure rollback."""
    with tempfile.TemporaryDirectory(prefix="zcad-export-stage-") as folder:
        staging = Path(folder)
        result = _prepare_exports(request, staging)
        publish_files(staging, request.output_directory)
        return result
