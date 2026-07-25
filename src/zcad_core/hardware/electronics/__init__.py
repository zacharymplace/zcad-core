"""Electronics hardware specifications."""

from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
)
from zcad_core.hardware.electronics.displays import (
    REFERENCE_OLED_128X64,
    DisplayMountStyle,
    DisplaySpec,
    get_reference_oled_128x64,
)
from zcad_core.hardware.electronics.raspberry_pi import (
    RaspberryPiPico2Spec,
    get_raspberry_pi_pico2,
)
from zcad_core.hardware.electronics.seeed import (
    SeeedXiaoEsp32S3Spec,
    get_seeed_xiao_esp32s3,
)

__all__ = [
    "REFERENCE_OLED_128X64",
    "BoardEdge",
    "DisplayMountStyle",
    "DisplaySpec",
    "RaspberryPiPico2Spec",
    "RectangularConnectorSpec",
    "SeeedXiaoEsp32S3Spec",
    "get_raspberry_pi_pico2",
    "get_reference_oled_128x64",
    "get_seeed_xiao_esp32s3",
]
