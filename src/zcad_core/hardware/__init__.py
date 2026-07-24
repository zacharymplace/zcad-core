"""Reusable engineering hardware specifications."""

from zcad_core.hardware.fasteners import (
    FastenerSpec,
    get_fastener,
    list_fasteners,
)

__all__ = [
    "FastenerSpec",
    "HardwareCatalog",
    "HardwareSpec",
    "MagnetSpec",
    "RaspberryPiPico2Spec",
    "get_fastener",
    "get_magnet",
    "get_raspberry_pi_pico2",
    "list_fasteners",
    "list_magnets",
]

from zcad_core.hardware.catalog import (
    HardwareCatalog,
    HardwareSpec,
)
from zcad_core.hardware.electronics import (
    RaspberryPiPico2Spec,
    get_raspberry_pi_pico2,
)
from zcad_core.hardware.magnets import (
    MagnetSpec,
    get_magnet,
    list_magnets,
)
