"""Data models for reusable CAD exports."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq


@dataclass(frozen=True)
class ExportRequest:
    """Inputs required to export one generated design."""

    design_name: str
    design_type: str
    parts: dict[str, cq.Workplane]
    output_directory: Path
    repository_root: Path
    printer_profile: dict[str, Any] | None = None
    material_profile: dict[str, Any] | None = None
    parameters: dict[str, Any] | None = None
    feature_validator: Callable[..., list[dict[str, Any]]] | None = None
    stl_feature_validator: Callable[..., list[dict[str, Any]]] | None = None


@dataclass(frozen=True)
class ExportedPart:
    """Paths and measurements for one exported part."""

    part_name: str
    stem: str
    step_path: Path
    stl_path: Path
    metadata_path: Path
    volume_mm3: float
    bounds_mm: tuple[float, float, float]


@dataclass(frozen=True)
class ExportResult:
    """Complete result for one export request."""

    design_name: str
    parts: tuple[ExportedPart, ...]
    validation_report: dict[str, Any] | None = None
