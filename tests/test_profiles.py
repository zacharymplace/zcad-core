"""Tests for profile loading."""

from pathlib import Path

from zcad_core.profiles.loading import (
    load_material_profile,
    load_printer_profile,
    load_slicer_profile,
)


def test_default_printer_profile_loads() -> None:
    profile = load_printer_profile(Path("profiles/printers/default-fdm.json"))

    assert profile["profile_id"] == "default-fdm"

    assert profile["build_volume_mm"]["x"] == 256


def test_default_material_profile_loads() -> None:
    profile = load_material_profile(Path("profiles/materials/petg.json"))

    assert profile["profile_id"] == "petg"

    assert profile["density_g_cm3"] > 1


def test_a1_mini_printer_profile_loads() -> None:
    profile = load_printer_profile(Path("profiles/printers/bambu-lab-a1-mini.json"))

    assert profile["profile_id"] == ("bambu-lab-a1-mini")
    assert profile["build_volume_mm"] == {
        "x": 180,
        "y": 180,
        "z": 180,
    }
    assert profile["calibration_status"] == ("uncalibrated")


def test_planned_slicer_profile_loads() -> None:
    profile = load_slicer_profile(
        Path("profiles/slicers/bambu-studio-a1-mini-petg-validation.json")
    )

    assert profile["status"] == "planned"
    assert profile["slice_completed"] is False
    assert profile["estimated_material_grams"] is None


def test_package_exports_the_loaders() -> None:
    from zcad_core import profiles
    from zcad_core.profiles import loading

    for name in (
        "load_json_object",
        "load_material_profile",
        "load_printer_profile",
        "load_slicer_profile",
    ):
        assert getattr(profiles, name) is getattr(loading, name)
        assert name in profiles.__all__
