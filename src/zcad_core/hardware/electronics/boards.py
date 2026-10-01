"""Catalogs of the boards and displays an enclosure can be built around."""

from pathlib import Path
from typing import Protocol

from zcad_core.hardware.catalog import HardwareCatalog
from zcad_core.hardware.electronics.adafruit import get_adafruit_feather_rp2040
from zcad_core.hardware.electronics.arduino import get_arduino_uno_r4_wifi
from zcad_core.hardware.electronics.board_components import BoardComponentSpec
from zcad_core.hardware.electronics.board_file import load_catalog_boards
from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
    WallOpeningSpec,
)
from zcad_core.hardware.electronics.displays import (
    ADAFRUIT_EINK_200X200_1_54IN,
    ADAFRUIT_OLED_128X64_1_3IN,
    ADAFRUIT_OLED_128X128_1_5IN,
    DisplaySpec,
    get_reference_oled_128x64,
)
from zcad_core.hardware.electronics.raspberry_pi import (
    get_raspberry_pi5,
    get_raspberry_pi_pico2,
)
from zcad_core.hardware.electronics.seeed import get_seeed_xiao_esp32s3


class BoardSpec(Protocol):
    """A rectangular board with one edge connector and its other parts."""

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
    @property
    def components(self) -> tuple[BoardComponentSpec, ...]: ...
    @property
    def wall_openings(self) -> tuple[WallOpeningSpec, ...]: ...


_BOARDS: tuple[BoardSpec, ...] = (
    get_adafruit_feather_rp2040(),
    get_arduino_uno_r4_wifi(),
    get_raspberry_pi_pico2(),
    get_raspberry_pi5(),
    get_seeed_xiao_esp32s3(),
)

# Boards that passed their trials are added here as files, not code; see
# ``zcad-validation board promote``.
BOARD_DATA_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "boards"


def build_board_catalog(
    directory: Path = BOARD_DATA_DIRECTORY,
) -> HardwareCatalog[BoardSpec]:
    """The coded boards and every board file in a data directory."""

    entries: dict[str, BoardSpec] = {board.identifier: board for board in _BOARDS}

    for board in load_catalog_boards(directory):
        if HardwareCatalog.normalize_identifier(board.identifier) in {
            HardwareCatalog.normalize_identifier(key) for key in entries
        }:
            raise ValueError(f"{board.identifier} is already in the board catalog")

        entries[board.identifier] = board

    return HardwareCatalog(category="board", entries=entries)


BOARD_CATALOG: HardwareCatalog[BoardSpec] = build_board_catalog()

DISPLAY_CATALOG: HardwareCatalog[DisplaySpec] = HardwareCatalog(
    category="display",
    entries={
        display.identifier: display
        for display in (
            get_reference_oled_128x64(),
            ADAFRUIT_OLED_128X64_1_3IN,
            ADAFRUIT_OLED_128X128_1_5IN,
            ADAFRUIT_EINK_200X200_1_54IN,
        )
    },
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
