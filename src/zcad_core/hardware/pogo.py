"""Spring-loaded test pins (pogo pins), each figure with its source.

A pogo pin's figures are a maker's datasheet: its barrel and tip, its length
and travel, and the force it pushes back with at a stated travel. The engine
must not invent them, so an entry goes in only when a datasheet has been read, with
each figure's source, a ``read`` flag, and the figures that no read document supports
(``unverified``), as a fan's do. A fixture can name a catalogued pin, or take the user's own
figures in its file, and the build says whose they are.

Frame of a pin: its axis is vertical, the tip at the bottom, and ``travel_mm``
is how far the plunger moves in from its free length.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["vendor", "retailer", "user"]


@dataclass(frozen=True)
class PogoSource:
    """Where a pin's figures came from."""

    kind: SourceKind
    title: str
    url: str
    detail: str
    # Whether the maker's page or drawing itself was read, rather than only an
    # excerpt of it; always false for a user's own figures, which the engine has
    # no way to read.
    read: bool
    # Figures taken by a reading of the datasheet that it does not state outright.
    unverified: tuple[str, ...] = ()


@dataclass(frozen=True)
class PogoSpec:
    """One spring pin: its barrel, its tip, and what the spring does."""

    identifier: str
    maker: str
    model: str
    barrel_diameter_mm: float
    tip_diameter_mm: float
    free_length_mm: float
    travel_mm: float
    # The force the spring pushes back with at ``force_at_travel_mm`` of travel.
    force_n: float
    force_at_travel_mm: float
    source: PogoSource

    def validate(self) -> None:
        for name in (
            "barrel_diameter_mm",
            "tip_diameter_mm",
            "free_length_mm",
            "travel_mm",
            "force_n",
            "force_at_travel_mm",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.tip_diameter_mm > self.barrel_diameter_mm:
            raise ValueError("The tip cannot be wider than the barrel")

        if self.travel_mm >= self.free_length_mm:
            raise ValueError("The travel must be less than the free length")

        if self.force_at_travel_mm > self.travel_mm:
            raise ValueError("force_at_travel_mm is beyond the pin's travel")

    @property
    def figures_from(self) -> str:
        if self.source.kind == "user":
            return "the user's file; no maker's datasheet has been read"

        note = f"{self.source.title}, " + (
            "read" if self.source.read else "from a search excerpt, not read"
        )

        if self.source.unverified:
            note += f"; unverified: {', '.join(self.source.unverified)}"

        return note


_NEWTONS_PER_GRAM_FORCE = 9.80665 / 1000.0
_IN = 25.4
_MILL_MAX_UNVERIFIED = (
    "barrel_diameter_mm",
    "force_at_travel_mm",
)


def _mill_max(
    part: str,
    url: str,
    updated: str,
    *,
    free_length_in: float,
    mid_stroke_in: float,
    full_stroke_in: float,
) -> PogoSpec:
    """A Mill-Max 0906 spring-loaded pin, from its data sheet: the drawing's diameters (tip
    .042 in, the largest .072 in), initial height, strokes, and the 60 gram-force spring."""

    return PogoSpec(
        identifier=f"MILLMAX-{part}".upper(),
        maker="Mill-Max",
        model=part,
        barrel_diameter_mm=round(0.072 * _IN, 3),
        tip_diameter_mm=round(0.042 * _IN, 3),
        free_length_mm=round(free_length_in * _IN, 3),
        travel_mm=round(full_stroke_in * _IN, 3),
        force_n=round(60 * _NEWTONS_PER_GRAM_FORCE, 4),
        force_at_travel_mm=round(mid_stroke_in * _IN, 3),
        source=PogoSource(
            kind="vendor",
            title=f"Mill-Max data sheet {part}",
            url=url,
            detail=(
                f"the maker's data sheet was read ({updated}): the drawing's diameters, "
                "initial height and strokes, and a spring of 60 grams force. The sheet "
                "names no travel for the 60 grams, so the force is taken at the mid-stroke "
                "(the maker's working travel); and the barrel is taken as the drawing's "
                "largest diameter, 0.072 in, a collar below the plunger's 0.042 in tip; the "
                "pin's tail is a solder tail for a 0.020 in hole, not a fixture socket"
            ),
            read=True,
            unverified=_MILL_MAX_UNVERIFIED,
        ),
    )


_PINS: dict[str, PogoSpec] = {
    pin.identifier: pin
    for pin in (
        _mill_max(
            "0906-0-15-20-76-14-11-0",
            "https://www.farnell.com/datasheets/3820075.pdf",
            "updated 1/6/23",
            free_length_in=0.137,
            mid_stroke_in=0.0195,
            full_stroke_in=0.039,
        ),
        _mill_max(
            "0906-1-15-20-75-14-11-0",
            "https://datasheet.octopart.com/0906-1-15-20-75-14-11-0-Mill-Max-datasheet-180665644.pdf",
            "updated 7/28/21",
            free_length_in=0.177,
            mid_stroke_in=0.0275,
            full_stroke_in=0.055,
        ),
    )
}


def list_pogo_pins() -> tuple[str, ...]:
    """The catalogued pogo pins."""

    return tuple(sorted(_PINS))


def get_pogo_pin(identifier: str) -> PogoSpec:
    """One catalogued pin."""

    try:
        return _PINS[identifier.strip().upper()]
    except KeyError:
        known = ", ".join(list_pogo_pins()) or "none yet"

        raise ValueError(
            f"Unsupported pogo pin: {identifier}; catalogued: {known}. Give a "
            "pin's own figures in the fixture file instead"
        ) from None
