"""Cooling fans an enclosure can carry, each figure with its source.

A fan's frame is square, with a hole at each corner on a square pattern. The
airflow is the maker's free-air figure, with no box in the way; in an
enclosure the air moves a good deal less, so it is reported and never used to
credit the temperature estimate.

Every entry says where its figures came from and whether the maker's own page
or drawing was read. ``read`` is ``True`` when the figures the build draws from
(the frame, its thickness and its holes) are from a document of the maker's that
was read. It is ``False`` when any of them is only from a search excerpt of the
maker's page: probably right, not checked, and the build says so. ``unverified``
names every figure, drawn or not, that no document read supports, so a build and a
reader can see exactly what is still an excerpt or an assumption.
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
    # Whether the maker's page or drawing itself was read, for the figures the build
    # draws from, rather than only an excerpt of it in a search result.
    read: bool
    # The figures no document read supports: from an excerpt, or an assumption.
    unverified: tuple[str, ...] = ()


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
    def unverified_note(self) -> str:
        """What no read document supports, for a warning: empty when nothing is left."""

        if not self.source.unverified:
            return ""

        return (
            f" ({', '.join(self.source.unverified)} not from a document that was read)"
        )

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
    title="Noctua NF-A4x10 5V, information sheet",
    url="https://cdn.noctua.at/media/noctua_nf_a4x10%205v_infosheet_en_web.pdf",
    detail=(
        "the maker's information sheet was read (a PDF on the maker's own site): size "
        "40 x 40 x 10 mm, 5 V, input power 0.25 W maximum (0.05 A), airflow 8.2 m3/h "
        "maximum. Not in the sheet, and from a search excerpt of the specifications "
        "page (https://noctua.at/en/products/fan/nf-a4x10-5v/specification), which "
        "could not be opened: holes 32 x 32 mm, typical input 0.22 W (0.044 A), and a "
        "thickness of 11 mm without anti-vibration pads, where the sheet says 10 mm "
        "(the larger is kept); the screw size is an assumption"
    ),
    read=False,
    unverified=("hole_spacing_mm", "thickness_mm", "current_typical_a", "screw"),
)

_NOCTUA_6X25 = FanSource(
    kind="vendor",
    title="Noctua NF-A6x25 5V, information sheet",
    url="https://www.quietpcusa.com/Assets/downloads/noctua_nf_a6x25_5v_datasheet_en.pdf",
    detail=(
        "the maker's information sheet was read, from a retailer's copy of it (the "
        "maker's site refused the request): size 60 x 60 x 25 mm, 5 V, input power "
        "1.3 W maximum (0.26 A), airflow 29.2 m3/h maximum. Not in the sheet, and from "
        "a search excerpt of the specifications page "
        "(https://www.noctua.at/en/products/nf-a6x25-5v/specifications), which could "
        "not be opened: holes 50 x 50 mm and typical input 0.935 W (0.187 A); the "
        "screw size is an assumption"
    ),
    read=False,
    unverified=("hole_spacing_mm", "current_typical_a", "screw"),
)

_SUNON_30 = FanSource(
    kind="vendor",
    title="Sunon DC Brushless Fan & Blower catalog, 30x30x10 mm (MF30100V1-1000U-A99)",
    url="https://media.digikey.com/pdf/Data%20Sheets/Sunon%20PDFs/DC_Brushless_Fan&Blower_Cat.pdf",
    detail=(
        "the maker's catalog page was read, a PDF of Sunon's catalog hosted by Digi-Key "
        "(page 17): 30 x 30 x 10 mm, holes 24 +-0.3 mm square and 3.2 +-0.3 mm across, "
        "5 V, 120 mA, 0.60 W, airflow 5.5 CFM (9.34 m3/h). The drawing is marked "
        "3-phi 3.2, while the engine builds the usual four holes; the catalog states no "
        "maximum current, and the screw size (M3, for a 3.2 mm hole) is an assumption"
    ),
    read=True,
    unverified=("current_max_a", "screw"),
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
        screw="M3",
        rated_v=5.0,
        current_typical_a=0.120,
        current_max_a=None,
        airflow_m3h=9.34,
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
