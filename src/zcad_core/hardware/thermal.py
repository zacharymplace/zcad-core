"""Power that catalogued hardware dissipates, each figure with its source.

A part with no figure has no entry. The thermal estimate reports it as
unknown, and never as zero: a box with an unsourced part can only be given a
lower bound on its temperature.

Each figure is the power drawn, which a board turns into heat, apart from
what it passes on to anything plugged into it. ``typical_w`` is a figure for
ordinary use; ``peak_w`` is a higher figure for load, or ``None`` where the
source gives none. A ``vendor`` source is the maker's own document; a
``community`` source is a measurement someone posted, and is weaker: it says
who measured what and how, and is to be replaced by a vendor figure when one
appears. A ``user`` source is a figure from a board file, the user's own, with
whatever source they state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zcad_core.hardware.fans import FAN_CATALOG

SourceKind = Literal["vendor", "community", "user"]


@dataclass(frozen=True)
class PowerSource:
    """Where a power figure came from."""

    kind: SourceKind
    title: str
    url: str
    # Where in the source the figure is, and how it was measured.
    detail: str

    def describe(self) -> str:
        return f"{self.kind}: {self.title} ({self.detail})"


@dataclass(frozen=True)
class PowerFigure:
    """One part's dissipation, in watts."""

    identifier: str
    typical_w: float
    peak_w: float | None
    source: PowerSource

    def __post_init__(self) -> None:
        if self.typical_w <= 0:
            raise ValueError("typical_w must be positive")

        if self.peak_w is not None and self.peak_w < self.typical_w:
            raise ValueError("peak_w cannot be below typical_w")


_PICO_2_DATASHEET = PowerSource(
    kind="vendor",
    title="Raspberry Pi Pico 2 Datasheet, release 5 (3 July 2026)",
    url="https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf",
    detail=(
        "section 4.1.2, Table 2, typical VBUS (5 V) consumption with nothing "
        "on the GPIOs: Hello_serial 62.1 mW; highest entry, USB boot mode "
        "peak during boot, 71.3 mW"
    ),
)

_PI_5_FORUM = PowerSource(
    kind="community",
    title="Raspberry Pi Forums, thread 'RPi 5 read supply currents?'",
    url="https://forums.raspberrypi.com/viewtopic.php?t=359249",
    detail=(
        "idle, at the USB-C input with a POWER-Z KM003C meter, 'between 2.9 "
        "and 3.1 W', posted by hqcamuser on 17 April 2024; other posters "
        "measured 1.7 to 2.3 W at the PMIC, before conversion losses, and "
        "the thread has no load figure that held up"
    ),
)

_FIGURES = (
    PowerFigure(
        identifier="RASPBERRY_PI_PICO_2",
        typical_w=0.0621,
        peak_w=0.0713,
        source=_PICO_2_DATASHEET,
    ),
    # No peak: the only load figures found were one poster's 'never above 7 W'
    # on a board that was throttling, and summaries that could not be traced.
    PowerFigure(
        identifier="RASPBERRY_PI_5",
        typical_w=3.0,
        peak_w=None,
        source=_PI_5_FORUM,
    ),
)


def _fan_figures() -> tuple[PowerFigure, ...]:
    """A fan's draw is the heat it adds to the box: its rated voltage times
    its input current, as the maker lists them."""

    figures = []

    for fan in FAN_CATALOG.entries.values():
        if fan.typical_w is None:
            continue

        figures.append(
            PowerFigure(
                identifier=fan.identifier,
                typical_w=fan.typical_w,
                peak_w=fan.peak_w,
                source=PowerSource(
                    kind="vendor",
                    title=fan.source.title,
                    url=fan.source.url,
                    detail=(
                        f"{fan.rated_v:g} V times the listed input current"
                        + (
                            ""
                            if fan.source.read
                            else "; from an excerpt, the page itself not read"
                        )
                    ),
                ),
            )
        )

    return tuple(figures)


POWER_FIGURES: dict[str, PowerFigure] = {
    figure.identifier: figure for figure in (*_FIGURES, *_fan_figures())
}


def get_power_figure(identifier: str) -> PowerFigure | None:
    """The catalogued figure for a part, or ``None`` if it has none."""

    return POWER_FIGURES.get(identifier)
