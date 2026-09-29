"""Catalogs of the boards and displays an enclosure can be built around."""

from typing import Protocol

from zcad_core.hardware.catalog import HardwareCatalog
from zcad_core.hardware.electronics.adafruit import get_adafruit_feather_rp2040
from zcad_core.hardware.electronics.arduino import get_arduino_uno_r4_wifi
from zcad_core.hardware.electronics.connectors import RectangularConnectorSpec
from zcad_core.hardware.electronics.displays import (
    DisplaySpec,
    get_reference_oled_128x64,
)
from zcad_core.hardware.electronics.raspberry_pi import get_raspberry_pi_pico2
from zcad_core.hardware.electronics.seeed import get_seeed_xiao_esp32s3


class BoardSpec(Protocol):
    """A rectangular board with one edge connector (the shape assemblies need)."""

    @property
    def identifier(self) -> str: ...
    @property
    def board_width_mm(self) -> float: ...
    @property
    def board_length_mm(self) -> float: ...
    @property
    def board_thickness_mm(self) -> float: ...
    @property
    def usb_connector(self) -> RectangularConnectorSpec: ...


_BOARDS: tuple[BoardSpec, ...] = (
    get_adafruit_feather_rp2040(),
    get_arduino_uno_r4_wifi(),
    get_raspberry_pi_pico2(),
    get_seeed_xiao_esp32s3(),
)

BOARD_CATALOG: HardwareCatalog[BoardSpec] = HardwareCatalog(
    category="board",
    entries={board.identifier: board for board in _BOARDS},
)

DISPLAY_CATALOG: HardwareCatalog[DisplaySpec] = HardwareCatalog(
    category="display",
    entries={display.identifier: display for display in (get_reference_oled_128x64(),)},
)


def get_board(identifier: str) -> BoardSpec:
    """Return one catalogued board."""
    return BOARD_CATALOG.get(identifier)


def list_boards() -> tuple[str, ...]:
    """Return catalogued board identifiers."""
    return BOARD_CATALOG.identifiers()


def get_display(identifier: str) -> DisplaySpec:
    """Return one catalogued display."""
    return DISPLAY_CATALOG.get(identifier)


def list_displays() -> tuple[str, ...]:
    """Return catalogued display identifiers."""
    return DISPLAY_CATALOG.identifiers()
