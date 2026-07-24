"""Product-agnostic STEP, STL, and metadata export service."""

import json
import re

import cadquery as cq

from zcad.exporters.models import (
    ExportedPart,
    ExportRequest,
    ExportResult,
)
from zcad.metadata.build_record import build_part_record

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
) -> None:
    if not parts:
        raise ValueError("Export request contains no parts")

    for part_name, model in parts.items():
        _validate_name(
            field="part_name",
            value=part_name,
        )

        solid = model.val()

        if not solid.isValid():
            raise ValueError(f"Part is not a valid solid: {part_name}")


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
    _validate_parts(request.parts)

    request.output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    exported: list[ExportedPart] = []
    part_count = len(request.parts)

    for part_name, model in request.parts.items():
        solid = model.val()
        bounds = solid.BoundingBox()

        stem = _output_stem(
            design_name=request.design_name,
            part_name=part_name,
            part_count=part_count,
        )

        step_path = request.output_directory / f"{stem}.step"
        stl_path = request.output_directory / f"{stem}.stl"
        metadata_path = request.output_directory / f"{stem}.metadata.json"

        cq.exporters.export(
            model,
            str(step_path),
        )
        cq.exporters.export(
            model,
            str(stl_path),
        )

        record = build_part_record(
            design_name=request.design_name,
            design_type=request.design_type,
            part_name=part_name,
            model=model,
            step_path=step_path,
            stl_path=stl_path,
            printer_profile=(request.printer_profile),
            material_profile=(request.material_profile),
            repository_root=(request.repository_root),
        )

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
                volume_mm3=solid.Volume(),
                bounds_mm=(
                    bounds.xlen,
                    bounds.ylen,
                    bounds.zlen,
                ),
            )
        )

    return ExportResult(
        design_name=request.design_name,
        parts=tuple(exported),
    )
