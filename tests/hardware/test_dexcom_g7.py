"""Tests for Dexcom G7 specification."""

from zcad_core.hardware import (
    get_dexcom_g7,
)


def test_dexcom_g7_dimensions() -> None:
    sensor = get_dexcom_g7()

    assert sensor.identifier == "DEXCOM_G7"
    assert sensor.geometry_evidence_status == "manufacturer-published"
    assert "LBL-1002469" in sensor.geometry_source

    assert sensor.body_length_mm == 27.4
    assert sensor.body_width_mm == 24.1
    assert sensor.body_thickness_mm == 4.7
    assert sensor.wire_length_mm == 5.7
    assert sensor.adhesive_patch_diameter_mm == 42.0

    assert sensor.recommended_shell_clearance_mm == 0.5


def test_dexcom_g7_returns_canonical_spec() -> None:
    assert get_dexcom_g7() is get_dexcom_g7()
