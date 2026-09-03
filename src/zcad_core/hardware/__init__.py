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
    "REFERENCE_OLED_128X64",
    "BoardEdge",
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
    "get_dexcom_g7",
    "get_fastener",
    "get_magnet",
    "get_raspberry_pi_pico2",
    "get_reference_oled_128x64",
    "get_seeed_xiao_esp32s3",
    "get_tandem_mobi",
    "list_fasteners",
    "list_magnets",
]

from zcad_core.hardware.catalog import (
    HardwareCatalog,
    HardwareSpec,
)
from zcad_core.hardware.electronics import (
    BoardEdge,
    RaspberryPiPico2Spec,
    RectangularConnectorSpec,
    SeeedXiaoEsp32S3Spec,
    get_raspberry_pi_pico2,
    get_seeed_xiao_esp32s3,
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
