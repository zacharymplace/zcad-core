"""Reusable multi-part CAD assembly framework."""

from zcad_core.assemblies.assembly import (
    AssemblyBounds,
    DeviceAssembly,
)
from zcad_core.assemblies.boundary import (
    EnclosureBoundary,
    analyze_boundary_clearance,
)
from zcad_core.assemblies.clearance import (
    ClearanceEnvelope,
    ClearancePolicy,
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
    "ClearancePolicy",
    "ComponentPair",
    "DeviceAssembly",
    "EnclosureBoundary",
    "InterferenceFinding",
    "InterferenceReport",
    "Placement",
    "analyze_boundary_clearance",
    "analyze_component_interference",
    "component_pair",
]
