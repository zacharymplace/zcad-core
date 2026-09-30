"""Load and validate manufacturing profiles."""

import json
from pathlib import Path
from typing import Any


def load_json_object(
    path: Path,
) -> dict[str, Any]:
    """Load a JSON object from disk."""
    if not path.is_file():
        raise FileNotFoundError(f"Profile does not exist: {path}")

    with path.open(
        encoding="utf-8",
    ) as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise TypeError(f"Profile must contain a JSON object: {path}")

    return data


def load_printer_profile(
    path: Path,
) -> dict[str, Any]:
    """Load and minimally validate a printer profile."""
    profile = load_json_object(path)

    required = {
        "profile_id",
        "name",
        "build_volume_mm",
        "tolerances_mm",
    }

    missing = required.difference(profile)

    if missing:
        raise ValueError(
            "Printer profile is missing fields: " + ", ".join(sorted(missing))
        )

    build_volume = profile["build_volume_mm"]

    if not isinstance(build_volume, dict):
        raise TypeError("build_volume_mm must be an object")

    for axis in ("x", "y", "z"):
        value = build_volume.get(axis)

        if (
            not isinstance(
                value,
                int | float,
            )
            or value <= 0
        ):
            raise ValueError(f"build_volume_mm.{axis} must be greater than zero")

    return profile


def load_material_profile(
    path: Path,
) -> dict[str, Any]:
    """Load and minimally validate a material profile."""
    profile = load_json_object(path)

    required = {
        "profile_id",
        "name",
        "density_g_cm3",
    }

    missing = required.difference(profile)

    if missing:
        raise ValueError(
            "Material profile is missing fields: " + ", ".join(sorted(missing))
        )

    density = profile["density_g_cm3"]

    if (
        not isinstance(
            density,
            int | float,
        )
        or density <= 0
    ):
        raise ValueError("density_g_cm3 must be greater than zero")

    limit = profile.get("max_service_c")

    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int | float) or limit <= 0
    ):
        raise ValueError("max_service_c must be greater than zero")

    return profile


def material_service_limit_c(
    material_profile_id: str, directory: Path = Path("profiles/materials")
) -> float | None:
    """The continuous air temperature a material profile allows, or ``None``
    when the profile is absent or sets none."""

    path = directory / f"{material_profile_id}.json"

    if not path.is_file():
        return None

    limit = load_material_profile(path).get("max_service_c")

    return float(limit) if limit is not None else None


def load_slicer_profile(
    path: Path,
) -> dict[str, Any]:
    """Load and validate a slicer profile."""

    profile = load_json_object(path)

    required = {
        "profile_id",
        "name",
        "status",
        "software",
        "printer_profile_id",
        "material_profile_id",
        "nozzle_diameter_mm",
        "orientation",
        "layer_height_mm",
        "wall_loops",
        "infill",
        "supports",
        "slice_completed",
        "estimated_print_time_seconds",
        "estimated_material_grams",
    }
    missing = required.difference(profile)

    if missing:
        raise ValueError(
            "Slicer profile is missing fields: " + ", ".join(sorted(missing))
        )

    for field in (
        "nozzle_diameter_mm",
        "layer_height_mm",
        "wall_loops",
    ):
        value = profile[field]

        if not isinstance(value, int | float) or value <= 0:
            raise ValueError(f"{field} must be greater than zero")

    if not isinstance(
        profile["slice_completed"],
        bool,
    ):
        raise TypeError("slice_completed must be boolean")

    if not profile["slice_completed"]:
        for field in (
            "estimated_print_time_seconds",
            "estimated_material_grams",
        ):
            if profile[field] is not None:
                raise ValueError(f"{field} must remain null before slicing")

    return profile
