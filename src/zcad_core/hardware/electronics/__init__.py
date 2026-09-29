"""Electronics hardware specifications."""

from zcad_core.hardware.electronics.adafruit import (
    AdafruitFeatherRp2040Spec,
    get_adafruit_feather_rp2040,
)
from zcad_core.hardware.electronics.arduino import (
    ArduinoUnoR4WifiSpec,
    get_arduino_uno_r4_wifi,
)
from zcad_core.hardware.electronics.board_components import (
    BoardComponentSpec,
    load_board_components,
)
from zcad_core.hardware.electronics.boards import (
    BOARD_CATALOG,
    DISPLAY_CATALOG,
    BoardSpec,
    get_board,
    get_display,
    list_boards,
    list_displays,
)
from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
)
from zcad_core.hardware.electronics.displays import (
    ADAFRUIT_EINK_200X200_1_54IN,
    ADAFRUIT_OLED_128X64_1_3IN,
    ADAFRUIT_OLED_128X128_1_5IN,
    REFERENCE_OLED_128X64,
    DisplayMountStyle,
    DisplaySpec,
    get_reference_oled_128x64,
)
from zcad_core.hardware.electronics.raspberry_pi import (
    RaspberryPi5Spec,
    RaspberryPiPico2Spec,
    get_raspberry_pi5,
    get_raspberry_pi_pico2,
)
from zcad_core.hardware.electronics.seeed import (
    SeeedXiaoEsp32S3Spec,
    get_seeed_xiao_esp32s3,
)

__all__ = [
    "ADAFRUIT_EINK_200X200_1_54IN",
    "ADAFRUIT_OLED_128X64_1_3IN",
    "ADAFRUIT_OLED_128X128_1_5IN",
    "BOARD_CATALOG",
    "DISPLAY_CATALOG",
    "REFERENCE_OLED_128X64",
    "AdafruitFeatherRp2040Spec",
    "ArduinoUnoR4WifiSpec",
    "BoardComponentSpec",
    "BoardEdge",
    "BoardSpec",
    "DisplayMountStyle",
    "DisplaySpec",
    "RaspberryPi5Spec",
    "RaspberryPiPico2Spec",
    "RectangularConnectorSpec",
    "SeeedXiaoEsp32S3Spec",
    "get_adafruit_feather_rp2040",
    "get_arduino_uno_r4_wifi",
    "get_board",
    "get_display",
    "get_raspberry_pi5",
    "get_raspberry_pi_pico2",
    "get_reference_oled_128x64",
    "get_seeed_xiao_esp32s3",
    "list_boards",
    "list_displays",
    "load_board_components",
]
