"""Tests for profile loading."""

from pathlib import Path

from zcad_core.profiles.loading import (
    load_material_profile,
    load_printer_profile,
)


def test_default_printer_profile_loads() -> None:
    profile = load_printer_profile(Path("profiles/printers/default-fdm.json"))

    assert profile["profile_id"] == "default-fdm"

    assert profile["build_volume_mm"]["x"] == 256


def test_default_material_profile_loads() -> None:
    profile = load_material_profile(Path("profiles/materials/petg.json"))

    assert profile["profile_id"] == "petg"

    assert profile["density_g_cm3"] > 1
