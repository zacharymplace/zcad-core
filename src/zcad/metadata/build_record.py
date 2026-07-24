"""Create reproducible metadata records for generated parts."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cadquery as cq


def current_git_commit(
    repository_root: Path,
) -> str | None:
    """Return the current Git commit when available."""
    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return None

    return result.stdout.strip() or None


def estimate_mass_grams(
    volume_mm3: float,
    density_g_cm3: float,
) -> float:
    """Estimate solid mass from model volume and material density."""
    if volume_mm3 < 0:
        raise ValueError("volume_mm3 cannot be negative")

    if density_g_cm3 <= 0:
        raise ValueError("density_g_cm3 must be greater than zero")

    volume_cm3 = volume_mm3 / 1000

    return volume_cm3 * density_g_cm3


def build_part_record(
    *,
    design_name: str,
    design_type: str,
    part_name: str,
    model: cq.Workplane,
    step_path: Path,
    stl_path: Path,
    printer_profile: dict[str, Any] | None,
    material_profile: dict[str, Any] | None,
    repository_root: Path,
) -> dict[str, Any]:
    """Build metadata for one exported part."""
    solid = model.val()
    bounds = solid.BoundingBox()
    volume_mm3 = solid.Volume()

    density = None
    estimated_mass = None

    if material_profile is not None:
        density = material_profile["density_g_cm3"]
        estimated_mass = estimate_mass_grams(
            volume_mm3,
            density,
        )

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": current_git_commit(repository_root),
        "design": {
            "name": design_name,
            "type": design_type,
        },
        "part": {
            "name": part_name,
            "valid_solid": solid.isValid(),
            "volume_mm3": round(
                volume_mm3,
                3,
            ),
            "bounding_box_mm": {
                "x": round(
                    bounds.xlen,
                    3,
                ),
                "y": round(
                    bounds.ylen,
                    3,
                ),
                "z": round(
                    bounds.zlen,
                    3,
                ),
            },
            "estimated_mass_g": (
                round(
                    estimated_mass,
                    3,
                )
                if estimated_mass is not None
                else None
            ),
        },
        "manufacturing": {
            "printer_profile": (printer_profile),
            "material_profile": (material_profile),
            "density_g_cm3": density,
        },
        "outputs": {
            "step": str(step_path),
            "stl": str(stl_path),
        },
    }
