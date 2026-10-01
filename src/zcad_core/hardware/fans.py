"""Cooling fans an enclosure can carry, each figure with its source.

A fan's frame is square, with a hole at each corner on a square pattern. The
airflow is the maker's free-air figure, with no box in the way; in an
enclosure the air moves a good deal less, so it is reported and never used to
credit the temperature estimate.

Every entry says where its figures came from and whether the maker's own page
or drawing was read. ``read`` is ``False`` when the figures are from search
excerpts of the maker's page and not from the page itself: they are probably
right and have not been checked, and the build says so. Replace such an entry
with one read from the datasheet when it can be.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zcad_core.hardware.catalog import HardwareCatalog

SourceKind = Literal["vendor", "retailer"]


@dataclass(frozen=True)
class FanSource:
    """Where a fan's figures came from."""

    kind: SourceKind
    title: str
    url: str
    detail: str
    # Whether the maker's page or drawing itself was read, rather than only an
    # excerpt of it in a search result.
    read: bool


@dataclass(frozen=True)
class FanSpec:
    """One fan: its frame, its mounting holes, and what it draws and moves."""

    identifier: str
    maker: str
    model: str
    size_mm: float
    thickness_mm: float
    hole_spacing_mm: float
    # The catalog fastener that mounts it, through the enclosure into the
    # frame's holes. This is an assumption to confirm with the maker's screws.
    screw: str
    rated_v: float
    current_typical_a: float | None
    current_max_a: float | None
    airflow_m3h: float | None
    source: FanSource

    def validate(self) -> None:
        for name in ("size_mm", "thickness_mm", "hole_spacing_mm", "rated_v"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.hole_spacing_mm >= self.size_mm:
            raise ValueError("The holes must lie inside the frame")

    @property
    def opening_diameter_mm(self) -> float:
        """The round opening in the enclosure: 90 per cent of the frame, which
        leaves the blades' tips their room and a rim for the frame to seat on."""

        return 0.9 * self.size_mm

    @property
    def typical_w(self) -> float | None:
        return (
            self.rated_v * self.current_typical_a
            if self.current_typical_a is not None
            else None
        )

    @property
    def peak_w(self) -> float | None:
        return (
            self.rated_v * self.current_max_a
            if self.current_max_a is not None
            else None
        )


_NOCTUA_4X10 = FanSource(
    kind="vendor",
    title="Noctua NF-A4x10 5V, specifications",
    url="https://noctua.at/en/products/fan/nf-a4x10-5v/specification",
    detail=(
        "from a search excerpt of the page, which could not be opened: 40 x 40 x "
        "11 mm without anti-vibration pads, holes 32 x 32 mm, 5 V, input current "
        "0.044 A typical and 0.05 A maximum, airflow 8.2 m3/h maximum; the screw "
        "size is an assumption"
    ),
    read=False,
)

_NOCTUA_6X25 = FanSource(
    kind="vendor",
    title="Noctua NF-A6x25 5V, specifications",
    url="https://www.noctua.at/en/products/nf-a6x25-5v/specifications",
    detail=(
        "from a search excerpt of the page, which could not be opened: 60 x 60 x "
        "25 mm without anti-vibration pads, holes 50 x 50 mm, 5 V, input current "
        "0.187 A typical and 0.26 A maximum (0.935 W typical), airflow 29.2 m3/h "
        "maximum; the screw size is an assumption"
    ),
    read=False,
)

_SUNON_30 = FanSource(
    kind="vendor",
    title="Sunon MF30100V1-1000U-A99 (as listed by Digi-Key)",
    url=(
        "https://www.digikey.com/en/products/detail/sunon-fans/"
        "4132-MF30100V1-1000U-A99/9838571"
    ),
    detail=(
        "from a search excerpt of the listing, which could not be opened: 30 x 30 "
        "x 10 mm, 5 V, 0.120 A, 600 mW, 5.5 CFM (0.154 m3/min); the 24 mm hole "
        "spacing is the usual pattern for a 30 mm fan, from retailers' listings, "
        "and Sunon's drawing was not read; the screw size is an assumption"
    ),
    read=False,
)

_ENTRIES = {
    "NOCTUA_NF_A4X10_5V": FanSpec(
        identifier="NOCTUA_NF_A4X10_5V",
        maker="Noctua",
        model="NF-A4x10 5V",
        size_mm=40.0,
        thickness_mm=11.0,
        hole_spacing_mm=32.0,
        screw="M3",
        rated_v=5.0,
        current_typical_a=0.044,
        current_max_a=0.05,
        airflow_m3h=8.2,
        source=_NOCTUA_4X10,
    ),
    "NOCTUA_NF_A6X25_5V": FanSpec(
        identifier="NOCTUA_NF_A6X25_5V",
        maker="Noctua",
        model="NF-A6x25 5V",
        size_mm=60.0,
        thickness_mm=25.0,
        hole_spacing_mm=50.0,
        screw="M3",
        rated_v=5.0,
        current_typical_a=0.187,
        current_max_a=0.26,
        airflow_m3h=29.2,
        source=_NOCTUA_6X25,
    ),
    "SUNON_MF30100V1_1000U_A99": FanSpec(
        identifier="SUNON_MF30100V1_1000U_A99",
        maker="Sunon",
        model="MF30100V1-1000U-A99",
        size_mm=30.0,
        thickness_mm=10.0,
        hole_spacing_mm=24.0,
        screw="M2",
        rated_v=5.0,
        current_typical_a=0.120,
        current_max_a=None,
        airflow_m3h=9.24,
        source=_SUNON_30,
    ),
}

FAN_CATALOG: HardwareCatalog[FanSpec] = HardwareCatalog(
    category="fan", entries=_ENTRIES
)


def get_fan(identifier: str) -> FanSpec:
    """Return one catalogued fan."""
    fan = FAN_CATALOG.get(identifier)
    fan.validate()

    return fan


def list_fans() -> tuple[str, ...]:
    """Return catalogued fan identifiers."""
    return FAN_CATALOG.identifiers()
