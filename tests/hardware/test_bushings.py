"""The catalogue of headless press-fit drill bushings."""

from __future__ import annotations

from dataclasses import replace

import pytest

from zcad_core.hardware import get_bushing, list_bushings


def test_the_catalog_lists_the_parts_of_the_table() -> None:
    names = list_bushings()

    assert len(names) == 18
    assert names[0] == "DIN179A-2X6" and names[-1] == "DIN179A-8X20"
    assert "DIN179A-4X12" in names and "DIN179A-7X20" not in names


@pytest.mark.parametrize(
    ("identifier", "bore", "outer", "length"),
    [
        ("DIN179A-2X9", 2.0, 5.0, 9.0),
        ("DIN179A-3X8", 3.0, 6.0, 8.0),
        ("DIN179A-4X16", 4.0, 7.0, 16.0),
        ("DIN179A-5X12", 5.0, 8.0, 12.0),
        ("DIN179A-6X20", 6.0, 10.0, 20.0),
        ("DIN179A-7X10", 7.0, 12.0, 10.0),
        ("din179a-8x16", 8.0, 12.0, 16.0),
    ],
)
def test_a_bushing_carries_the_figures_of_its_row(
    identifier: str, bore: float, outer: float, length: float
) -> None:
    bushing = get_bushing(identifier)

    assert (bushing.bore_mm, bushing.outer_mm, bushing.length_mm) == (
        bore,
        outer,
        length,
    )
    assert bushing.standard == "DIN 179 type A, headless"


def test_every_bushing_is_valid_and_says_where_it_came_from() -> None:
    for identifier in list_bushings():
        bushing = get_bushing(identifier)

        assert bushing.outer_mm > bushing.bore_mm
        assert bushing.source.read is True
        assert bushing.source.url.startswith("https://www.jwwinco.com/")
        assert "converts them to millimetres" in bushing.source.detail
        assert bushing.figures_from.endswith(", read")


def test_a_bushing_that_cannot_be_right_is_refused() -> None:
    bushing = get_bushing("DIN179A-4X12")

    with pytest.raises(ValueError, match="must exceed the bore"):
        replace(bushing, outer_mm=3.0).validate()

    with pytest.raises(ValueError, match="greater than zero"):
        replace(bushing, length_mm=0.0).validate()


def test_an_unknown_bushing_names_what_is_catalogued() -> None:
    with pytest.raises(ValueError, match="catalogued: DIN179A-2X6"):
        get_bushing("ISO8020-4X12")
