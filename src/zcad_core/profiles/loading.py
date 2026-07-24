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

    return profile
