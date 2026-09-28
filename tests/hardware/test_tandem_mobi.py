"""Tests for Tandem Mobi specification."""

from zcad_core.hardware import (
    get_tandem_mobi,
)


def test_tandem_mobi_dimensions() -> None:
    pump = get_tandem_mobi()

    assert pump.identifier == "TANDEM_MOBI"
    assert pump.geometry_evidence_status == "manufacturer-published"
    assert "PMC13089864" in pump.geometry_source
    assert "diabetesnet.com" in pump.geometry_source

    assert pump.body_length_mm == 51.3
    assert pump.body_width_mm == 37.3
    assert pump.body_thickness_mm == 14.2

    assert pump.recommended_clip_clearance_mm == 0.5


def test_tandem_mobi_returns_canonical_spec() -> None:
    assert get_tandem_mobi() is get_tandem_mobi()
