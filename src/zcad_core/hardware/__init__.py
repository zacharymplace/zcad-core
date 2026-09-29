"""Reusable engineering hardware specifications."""

from zcad_core.hardware.electronics.displays import (
    REFERENCE_OLED_128X64,
    DisplayMountStyle,
    DisplaySpec,
    get_reference_oled_128x64,
)
from zcad_core.hardware.fasteners import (
    FastenerSpec,
    get_fastener,
    list_fasteners,
)

__all__ = [
    "BOARD_CATALOG",
    "DISPLAY_CATALOG",
    "REFERENCE_OLED_128X64",
    "AdafruitFeatherRp2040Spec",
    "ArduinoUnoR4WifiSpec",
    "BoardComponentSpec",
    "BoardEdge",
    "BoardSpec",
    "DexcomG7Spec",
    "DisplayMountStyle",
    "DisplaySpec",
    "FastenerSpec",
    "HardwareCatalog",
    "HardwareSpec",
    "MagnetSpec",
    "RaspberryPiPico2Spec",
    "RectangularConnectorSpec",
    "SeeedXiaoEsp32S3Spec",
    "TandemMobiSpec",
    "get_adafruit_feather_rp2040",
    "get_arduino_uno_r4_wifi",
    "get_board",
    "get_dexcom_g7",
    "get_display",
    "get_fastener",
    "get_magnet",
    "get_raspberry_pi_pico2",
    "get_reference_oled_128x64",
    "get_seeed_xiao_esp32s3",
    "get_tandem_mobi",
    "list_boards",
    "list_displays",
    "list_fasteners",
    "list_magnets",
    "load_board_components",
]

from zcad_core.hardware.catalog import (
    HardwareCatalog,
    HardwareSpec,
)
from zcad_core.hardware.electronics import (
    BOARD_CATALOG,
    DISPLAY_CATALOG,
    AdafruitFeatherRp2040Spec,
    ArduinoUnoR4WifiSpec,
    BoardComponentSpec,
    BoardEdge,
    BoardSpec,
    RaspberryPiPico2Spec,
    RectangularConnectorSpec,
    SeeedXiaoEsp32S3Spec,
    get_adafruit_feather_rp2040,
    get_arduino_uno_r4_wifi,
    get_board,
    get_display,
    get_raspberry_pi_pico2,
    get_seeed_xiao_esp32s3,
    list_boards,
    list_displays,
    load_board_components,
)
from zcad_core.hardware.magnets import (
    MagnetSpec,
    get_magnet,
    list_magnets,
)
from zcad_core.hardware.wearables import (
    DexcomG7Spec,
    TandemMobiSpec,
    get_dexcom_g7,
    get_tandem_mobi,
)
