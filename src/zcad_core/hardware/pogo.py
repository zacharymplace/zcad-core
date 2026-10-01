"""Spring-loaded test pins (pogo pins), each figure with its source.

A pogo pin's figures are a maker's datasheet: its barrel and tip, its length
and travel, and the force it pushes back with at a stated travel. The engine
must not invent them, so the **catalog is empty**. An entry goes in only when a
datasheet has been read, with each figure's source and a ``read`` flag, as a fan's
do. Until one is, a fixture takes the user's own figures in its file, and the
build says they are the user's.

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

        return f"{self.source.title}, " + (
            "read" if self.source.read else "from a search excerpt, not read"
        )


_PINS: dict[str, PogoSpec] = {}


def list_pogo_pins() -> tuple[str, ...]:
    """The catalogued pogo pins; none until a datasheet has been read."""

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
