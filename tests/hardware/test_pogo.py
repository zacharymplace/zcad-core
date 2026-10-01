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


def test_the_catalog_is_empty_until_a_datasheet_has_been_read() -> None:
    assert list_pogo_pins() == ()

    with pytest.raises(ValueError, match="catalogued: none yet"):
        get_pogo_pin("P75-E2")


def test_where_the_figures_came_from_is_said() -> None:
    assert PIN.figures_from == "A maker's datasheet, read"
    assert (
        replace(PIN, source=replace(SOURCE, read=False)).figures_from
        == "A maker's datasheet, from a search excerpt, not read"
    )
    user = replace(PIN, source=replace(SOURCE, kind="user"))

    assert "the user's file" in user.figures_from
