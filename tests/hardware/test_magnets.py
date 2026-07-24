"""Tests for cylindrical magnet specifications."""

import pytest

from zcad_core.hardware import (
    get_magnet,
    list_magnets,
)


def test_six_by_two_magnet() -> None:
    magnet = get_magnet("d6x2")

    assert magnet.identifier == "D6X2"
    assert magnet.diameter_mm == 6.0
    assert magnet.thickness_mm == 2.0
    assert magnet.pocket_diameter_mm == pytest.approx(6.3)
    assert magnet.pocket_depth_mm == pytest.approx(2.1)


def test_supported_magnets_are_sorted() -> None:
    assert list_magnets() == (
        "D10X3",
        "D12X3",
        "D6X2",
        "D8X3",
    )


def test_unknown_magnet() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported magnet",
    ):
        get_magnet("D7X2")


def test_negative_pocket_allowance_is_rejected() -> None:
    magnet = get_magnet("D8X3")

    invalid = type(magnet)(
        identifier="INVALID",
        diameter_mm=magnet.diameter_mm,
        thickness_mm=magnet.thickness_mm,
        radial_pocket_oversize_mm=-0.1,
    )

    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        invalid.validate()
