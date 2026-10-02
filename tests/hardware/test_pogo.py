"""Spring pins: a type for sourced figures, and a catalog that starts empty."""

from __future__ import annotations

from dataclasses import replace

import pytest

from zcad_core.hardware import PogoSource, PogoSpec, get_pogo_pin, list_pogo_pins

SOURCE = PogoSource(
    kind="vendor",
    title="A maker's datasheet",
    url="https://example.invalid",
    detail="p. 2",
    read=True,
)
PIN = PogoSpec(
    identifier="EXAMPLE",
    maker="Example",
    model="P1",
    barrel_diameter_mm=1.0,
    tip_diameter_mm=0.6,
    free_length_mm=8.0,
    travel_mm=2.0,
    force_n=1.0,
    force_at_travel_mm=1.5,
    source=SOURCE,
)


def test_a_pin_with_sane_figures_validates() -> None:
    PIN.validate()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"barrel_diameter_mm": 0}, "barrel_diameter_mm must be greater than zero"),
        ({"force_n": -1.0}, "force_n must be greater than zero"),
        ({"tip_diameter_mm": 1.2}, "tip cannot be wider than the barrel"),
        ({"travel_mm": 9.0}, "travel must be less than the free length"),
        ({"force_at_travel_mm": 3.0}, "beyond the pin's travel"),
    ],
)
def test_a_pin_that_cannot_be_right_is_refused(
    change: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(PIN, **change).validate()  # type: ignore[arg-type]


def test_the_catalog_holds_only_pins_whose_datasheets_were_read() -> None:
    assert list_pogo_pins() == (
        "MILLMAX-0906-0-15-20-76-14-11-0",
        "MILLMAX-0906-1-15-20-75-14-11-0",
    )

    for identifier in list_pogo_pins():
        pin = get_pogo_pin(identifier)
        pin.validate()

        assert pin.maker == "Mill-Max" and pin.source.kind == "vendor"
        assert pin.source.read is True
        assert pin.source.url.startswith("https://")
        assert pin.source.unverified == ("barrel_diameter_mm", "force_at_travel_mm")
        assert "unverified: barrel_diameter_mm, force_at_travel_mm" in pin.figures_from
        assert "names no travel for the 60 grams" in pin.source.detail

    with pytest.raises(ValueError, match="catalogued: MILLMAX-0906-0"):
        get_pogo_pin("P75-E2")


def test_the_mill_max_pins_carry_the_figures_of_their_data_sheets() -> None:
    short = get_pogo_pin("millmax-0906-0-15-20-76-14-11-0")
    long = get_pogo_pin("MILLMAX-0906-1-15-20-75-14-11-0")

    # Drawing: .042 in tip, .072 in largest diameter. Initial height .137 in with a .039 in
    # stroke (mid-stroke .0195 in) for the 76 spring; .177 in with .055 in (.0275 in) for 75.
    assert short.tip_diameter_mm == pytest.approx(1.067, abs=0.001)
    assert short.barrel_diameter_mm == pytest.approx(1.829, abs=0.001)
    assert short.free_length_mm == pytest.approx(3.480, abs=0.001)
    assert short.travel_mm == pytest.approx(0.991, abs=0.001)
    assert short.force_at_travel_mm == pytest.approx(0.495, abs=0.001)
    assert long.free_length_mm == pytest.approx(4.496, abs=0.001)
    assert long.travel_mm == pytest.approx(1.397, abs=0.001)
    assert long.force_at_travel_mm == pytest.approx(0.699, abs=0.001)
    # Both springs are 60 grams force.
    assert short.force_n == pytest.approx(0.5884, abs=0.0001) == long.force_n


def test_where_the_figures_came_from_is_said() -> None:
    assert PIN.figures_from == "A maker's datasheet, read"
    assert (
        replace(PIN, source=replace(SOURCE, read=False)).figures_from
        == "A maker's datasheet, from a search excerpt, not read"
    )
    user = replace(PIN, source=replace(SOURCE, kind="user"))

    assert "the user's file" in user.figures_from
