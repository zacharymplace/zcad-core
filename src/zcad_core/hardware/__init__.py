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
    "get_fastener",
    "get_magnet",
    "list_fasteners",
    "list_magnets",
]

from zcad_core.hardware.catalog import (
    HardwareCatalog,
    HardwareSpec,
)
from zcad_core.hardware.magnets import (
    MagnetSpec,
    get_magnet,
    list_magnets,
)
