"""Tests for manufacturing profiles and build metadata."""

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad.metadata.build_record import (
    build_part_record,
    estimate_mass_grams,
)
from zcad.profiles.loading import (
    load_material_profile,
    load_printer_profile,
)


def test_default_profiles_load() -> None:
    printer = load_printer_profile(Path("profiles/printers/default-fdm.json"))
    material = load_material_profile(Path("profiles/materials/petg.json"))

    assert printer["profile_id"] == "default-fdm"
    assert material["profile_id"] == "petg"


def test_mass_estimation() -> None:
    assert estimate_mass_grams(
        1000,
        1.27,
    ) == pytest.approx(1.27)


def test_build_part_record() -> None:
    model = cq.Workplane("XY").box(
        10,
        10,
        10,
    )

    record = build_part_record(
        design_name="test-cube",
        design_type="cube",
        part_name="main",
        model=model,
        step_path=Path("exports/test-cube.step"),
        stl_path=Path("exports/test-cube.stl"),
        printer_profile={
            "profile_id": "test-printer",
        },
        material_profile={
            "profile_id": "test-material",
            "density_g_cm3": 1.0,
        },
        repository_root=Path.cwd(),
    )

    assert record["part"]["volume_mm3"] == pytest.approx(1000)
    assert record["part"]["estimated_mass_g"] == pytest.approx(1)
    assert record["part"]["valid_solid"]


def test_profiles_are_valid_json() -> None:
    paths = [
        Path("profiles/printers/default-fdm.json"),
        Path("profiles/materials/petg.json"),
    ]

    for path in paths:
        with path.open(
            encoding="utf-8",
        ) as handle:
            assert isinstance(
                json.load(handle),
                dict,
            )
