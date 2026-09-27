"""Product-agnostic STEP, STL, and metadata export service."""

import json
import re

import cadquery as cq

from zcad_core.exporters.models import (
    ExportedPart,
    ExportRequest,
    ExportResult,
)
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


def export_parts(
    request: ExportRequest,
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
    if validation_report["evaluated_status"] == "FAIL":
        raise DesignValidationError(validation_report)

    request.output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

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

        cq.exporters.export(
            geometry.shape,
            str(step_path),
        )
        cq.exporters.export(
            geometry.shape,
            str(stl_path),
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
        metadata_path.write_text(
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
