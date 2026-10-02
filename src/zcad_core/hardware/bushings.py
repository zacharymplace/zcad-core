"""Headless press-fit drill bushings, each figure with its source.

A drill guide's bushing bore takes a steel bushing's sizes: the hole the drill goes through, the
outer diameter the pocket is sized to, and the length. A guide file can name one of these
instead of giving its own figures (``"bushing": {"catalog": "DIN179A-4X12"}``).

The entries are the headless bushings of DIN 179 type A, from a manufacturer's listing of the
standard. Each is named ``DIN179A-<bore>X<length>``, bore and length in millimetres. The
bore is the **nominal** size: DIN 179 makes it an F7 fit, a little over nominal, so a drill of
the nominal size passes. The outer diameter is the nominal size of an n6 fit.

The manufacturer's page lists the outer diameters in inches, and they are converted
here: 0.276 in is 7.0 mm. Headed bushings (DIN 172) are not catalogued.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BushingSource:
    """Where a bushing's figures came from."""

    title: str
    url: str
    detail: str
    # Whether the manufacturer's listing itself was read.
    read: bool
    # The figures no document read supports.
    unverified: tuple[str, ...] = ()


@dataclass(frozen=True)
class BushingSpec:
    """One catalogued bushing: its bore, its outside, its length."""

    identifier: str
    standard: str
    bore_mm: float
    outer_mm: float
    length_mm: float
    source: BushingSource

    def validate(self) -> None:
        for name in ("bore_mm", "outer_mm", "length_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.outer_mm <= self.bore_mm:
            raise ValueError("The outer diameter must exceed the bore")

    @property
    def figures_from(self) -> str:
        note = f"{self.source.title}, " + (
            "read" if self.source.read else "from a search excerpt, not read"
        )

        if self.source.unverified:
            note += f"; unverified: {', '.join(self.source.unverified)}"

        return note


_SOURCE = BushingSource(
    title="JW Winco, DIN 179 press-fit drill bushings (type A)",
    url=(
        "https://www.jwwinco.com/en-us/products/3.2-Mounting-positioning-levelling-with-"
        "screws-clamping-and-supporting-elements/Positioning-elements-Clamping-pads/"
        "DIN-179-Stainless-Steel-Press-Fit-Drill-Bushings"
    ),
    detail=(
        "the manufacturer's part table was read: bore d1 (F7), outer diameter d2 (n6) and "
        "length l1 for each part, where the page gives d2 in inches and the engine converts "
        "them to millimetres (0.276 in is 7.0 mm); the listing is of the stainless-steel parts, and the sizes are the standard's; the bore is taken at its nominal size"
    ),
    read=True,
)

# (bore, outer diameter, lengths), from the part table.
_TABLE = (
    (2.0, 5.0, (6.0, 9.0)),
    (3.0, 6.0, (8.0, 12.0)),
    (4.0, 7.0, (8.0, 12.0, 16.0)),
    (5.0, 8.0, (8.0, 12.0, 16.0)),
    (6.0, 10.0, (10.0, 16.0, 20.0)),
    (7.0, 12.0, (10.0, 16.0)),
    (8.0, 12.0, (10.0, 16.0, 20.0)),
)


def _entries() -> dict[str, BushingSpec]:
    entries = {}

    for bore, outer, lengths in _TABLE:
        for length in lengths:
            identifier = f"DIN179A-{bore:g}X{length:g}"
            entries[identifier] = BushingSpec(
                identifier=identifier,
                standard="DIN 179 type A, headless",
                bore_mm=bore,
                outer_mm=outer,
                length_mm=length,
                source=_SOURCE,
            )

    return entries


_BUSHINGS = _entries()


def list_bushings() -> tuple[str, ...]:
    """The catalogued bushings."""

    return tuple(_BUSHINGS)


def get_bushing(identifier: str) -> BushingSpec:
    """One catalogued bushing."""

    try:
        bushing = _BUSHINGS[identifier.strip().upper()]
    except KeyError:
        raise ValueError(
            f"Unsupported bushing: {identifier}; catalogued: {', '.join(list_bushings())}. "
            "Give a bushing's own figures in the guide file instead"
        ) from None

    bushing.validate()

    return bushing
