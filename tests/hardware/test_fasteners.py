"""Tests for reusable fastener specifications."""

import pytest

from zcad_core.hardware import (
    get_fastener,
    list_fasteners,
)


def test_m3_spec() -> None:
    spec = get_fastener("M3")

    assert spec.nominal_diameter_mm == 3.0
    assert spec.clearance_hole_mm == 3.4
    assert spec.tap_hole_mm == 2.5
    assert spec.heat_set_insert_diameter_mm == 4.6


def test_supported_fasteners() -> None:
    assert list_fasteners() == (
        "M2",
        "M2.5",
        "M3",
        "M4",
    )


def test_unknown_fastener() -> None:
    with pytest.raises(ValueError):
        get_fastener("M7")
