"""Product-agnostic STEP, STL, and metadata export service."""

import hashlib
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.exporters.models import (
    ExportedPart,
    ExportRequest,
    ExportResult,
)
from zcad_core.exporters.publication import publish_files
from zcad_core.metadata.build_record import build_part_record
from zcad_core.metadata.producer import producer_provenance
from zcad_core.validation.design_report import (
    DesignValidationError,
    report_from_geometry,
)
from zcad_core.validation.export_geometry import (
    InspectedGeometry,
    inspect_export_geometry,
)
from zcad_core.validation.stl_mesh import read_stl

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


def _feature_checks(
    request: ExportRequest,
    validator: Callable[..., list[dict[str, Any]]],
    inspected: dict[str, InspectedGeometry],
) -> list[dict[str, Any]]:
    try:
        checks = validator(
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
    # Application validators are arbitrary code; any failure must fail closed.
    except Exception as error:  # noqa: BLE001
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


def _design_report(
    request: ExportRequest, inspected: dict[str, InspectedGeometry]
) -> dict[str, Any]:
    """Geometry and profile checks, plus feature checks; raise on failure."""

    validation_report = report_from_geometry(
        design_name=request.design_name,
        design_type=request.design_type,
        geometry=inspected,
        printer_profile=request.printer_profile,
        parameters=request.parameters,
    )
    if request.feature_validator is not None:
        checks = _feature_checks(request, request.feature_validator, inspected)
        validation_report["checks"].extend(checks)
        validation_report["scope"] += "; application feature checks (see check details)"
        if any(check["status"] == "FAIL" for check in checks):
            validation_report["evaluated_status"] = "FAIL"
    if validation_report["evaluated_status"] == "FAIL":
        raise DesignValidationError(validation_report)

    return validation_report


def _step_round_trip(
    request: ExportRequest,
    inspected: dict[str, InspectedGeometry],
    validation_report: dict[str, Any],
) -> dict[str, bytes]:
    """Re-run feature checks on reimported STEP; return the STEP bytes by part.

    Without a feature validator there is nothing to re-check, and each part's
    STEP is exported later.
    """

    staged_steps: dict[str, bytes] = {}

    if request.feature_validator is None:
        return staged_steps

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
            roundtrip_checks = _feature_checks(
                request, request.feature_validator, imported
            )
    # OCC export/import failures surface as varied exception types.
    except Exception as error:  # noqa: BLE001
        roundtrip_checks = [
            {
                "code": "step_reimport",
                "status": "FAIL",
                "message": (f"STEP round-trip error: {type(error).__name__}: {error}"),
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

    return staged_steps


def _stl_feature_checks(
    request: ExportRequest, meshes: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run the registered STL feature validator; any failure fails closed."""

    if request.stl_feature_validator is None:
        return [
            {
                "code": "stl_features",
                "status": "NOT_CHECKED",
                "message": "No STL feature validator registered",
            }
        ]

    try:
        checks = request.stl_feature_validator(
            design_type=request.design_type,
            parts=meshes,
            parameters=request.parameters or {},
        )
        if (
            not isinstance(checks, list)
            or not checks
            or any(
                not isinstance(c, dict)
                or c.get("status") not in {"PASS", "FAIL", "NOT_CHECKED"}
                or not isinstance(c.get("code"), str)
                or not isinstance(c.get("message"), str)
                for c in checks
            )
        ):
            raise ValueError("Invalid STL feature checks")
        json.dumps(checks, allow_nan=False)
    # Application validators are arbitrary code; any failure must fail closed.
    except Exception as error:  # noqa: BLE001
        return [{"code": "stl_features", "status": "FAIL", "message": str(error)}]

    return checks


def _stl_round_trip(
    request: ExportRequest,
    inspected: dict[str, InspectedGeometry],
    staging: Path,
    validation_report: dict[str, Any],
) -> None:
    """Stage each part's STL and check the reread mesh; raise on failure."""

    part_count = len(request.parts)
    meshes, mesh_checks, mesh_hashes = {}, [], {}
    for name, geometry in inspected.items():
        stem = _output_stem(
            design_name=request.design_name, part_name=name, part_count=part_count
        )
        path = staging / f"{stem}.stl"
        cq.exporters.export(geometry.shape, str(path))
        data = path.read_bytes()
        mesh_hashes[name] = hashlib.sha256(data).hexdigest()
        try:
            meshes[name], check = read_stl(data)
            mesh_checks.append({**check, "part_name": name})
        except ValueError as error:
            mesh_checks.append(
                {
                    "code": "stl_topology",
                    "status": "FAIL",
                    "part_name": name,
                    "message": str(error),
                }
            )
    if not any(c["status"] == "FAIL" for c in mesh_checks):
        mesh_checks.extend(_stl_feature_checks(request, meshes))
    failed = any(c["status"] == "FAIL" for c in mesh_checks)
    validation_report["stl_round_trip"] = {
        "status": "FAIL" if failed else "PASS",
        "coverage": "PARTIAL",
        "scope": (
            "Binary mesh topology plus registered feature probes; "
            "see individual coverage"
        ),
        "checks": mesh_checks,
        "stl_sha256_by_part": mesh_hashes,
    }
    if failed:
        validation_report["evaluated_status"] = "FAIL"
        validation_report["checks"].append(
            {
                "code": "stl_round_trip",
                "status": "FAIL",
                "message": "STL round-trip checks failed",
            }
        )
        raise DesignValidationError(validation_report)


def _stage_part(
    request: ExportRequest,
    part_name: str,
    geometry: InspectedGeometry,
    staging: Path,
    staged_steps: dict[str, bytes],
    validation_report: dict[str, Any],
    producer: dict[str, str | None],
) -> ExportedPart:
    """Stage one part's STEP and metadata beside its STL."""

    bounds_mm = geometry.bounds_mm
    volume_mm3 = geometry.volume_mm3
    valid_solid = True

    stem = _output_stem(
        design_name=request.design_name,
        part_name=part_name,
        part_count=len(request.parts),
    )

    step_path = request.output_directory / f"{stem}.step"
    stl_path = request.output_directory / f"{stem}.stl"
    metadata_path = request.output_directory / f"{stem}.metadata.json"
    staged_step = staging / step_path.name
    staged_metadata = staging / metadata_path.name

    if part_name in staged_steps:
        staged_step.write_bytes(staged_steps[part_name])
    else:
        cq.exporters.export(geometry.shape, str(staged_step))

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
        producer=producer,
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

    return ExportedPart(
        part_name=part_name,
        stem=stem,
        step_path=step_path,
        stl_path=stl_path,
        metadata_path=metadata_path,
        volume_mm3=volume_mm3,
        bounds_mm=bounds_mm,
    )


def _prepare_exports(
    request: ExportRequest,
    staging: Path,
) -> ExportResult:
    """Export all requested parts and their metadata.

    Each stage raises DesignValidationError before anything later is
    written, so a failing design leaves only discarded staging files.
    """
    _validate_name(
        field="design_name",
        value=request.design_name,
    )
    _validate_name(
        field="design_type",
        value=request.design_type,
    )
    inspected = _validate_parts(request.parts)
    validation_report = _design_report(request, inspected)
    staged_steps = _step_round_trip(request, inspected, validation_report)
    _stl_round_trip(request, inspected, staging, validation_report)

    producer = producer_provenance()
    return ExportResult(
        design_name=request.design_name,
        parts=tuple(
            _stage_part(
                request,
                name,
                geometry,
                staging,
                staged_steps,
                validation_report,
                producer,
            )
            for name, geometry in inspected.items()
        ),
        validation_report=validation_report,
    )


def export_parts(request: ExportRequest) -> ExportResult:
    """Prepare all artifacts before publishing with caught-failure rollback.
    Refused before anything is written when the build record the caller will
    write is already in the output directory."""

    if request.build_record_name is not None:
        record = request.output_directory / request.build_record_name

        if record.exists():
            raise FileExistsError(
                f"Refusing to overwrite build record: {record}; nothing was written. "
                "Build into a new output directory"
            )

    with tempfile.TemporaryDirectory(prefix="zcad-export-stage-") as folder:
        staging = Path(folder)
        result = _prepare_exports(request, staging)
        publish_files(staging, request.output_directory)
        return result
