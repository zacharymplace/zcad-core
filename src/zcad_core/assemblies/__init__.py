"""Reusable multi-part CAD assembly framework."""

from zcad_core.assemblies.assembly import (
    AssemblyBounds,
    DeviceAssembly,
)
from zcad_core.assemblies.clearance import (
    ClearanceEnvelope,
)
from zcad_core.assemblies.component import (
    AssemblyComponent,
)
from zcad_core.assemblies.interference import (
    ComponentPair,
    InterferenceFinding,
    InterferenceReport,
    analyze_component_interference,
    component_pair,
)
from zcad_core.assemblies.placement import (
    Placement,
)

__all__ = [
    "AssemblyBounds",
    "AssemblyComponent",
    "ClearanceEnvelope",
    "ComponentPair",
    "DeviceAssembly",
    "InterferenceFinding",
    "InterferenceReport",
    "Placement",
    "analyze_component_interference",
    "component_pair",
]
