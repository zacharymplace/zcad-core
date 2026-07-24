"""Reusable multi-part CAD assembly framework."""

from zcad_core.assemblies.assembly import (
    AssemblyBounds,
    DeviceAssembly,
)
from zcad_core.assemblies.component import (
    AssemblyComponent,
)
from zcad_core.assemblies.placement import (
    Placement,
)

__all__ = [
    "AssemblyBounds",
    "AssemblyComponent",
    "DeviceAssembly",
    "Placement",
]
