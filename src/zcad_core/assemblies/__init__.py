"""Reusable multi-part CAD assembly framework."""

from zcad_core.assemblies.assembly import (
    AssemblyBounds,
    DeviceAssembly,
)
from zcad_core.assemblies.board_display import (
    RectangularBoardSpec,
    RectangularDisplaySpec,
    analyze_board_display_assembly,
    board_component_identifier,
    board_component_identifiers,
    build_board_assembly,
    build_board_display_assembly,
    lowest_display_height_mm,
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
from zcad_core.assemblies.connectors import (
    build_board_edge_connector_component,
)
from zcad_core.assemblies.enclosure import (
    EnclosureSpecification,
    derive_enclosure_specification,
)
from zcad_core.assemblies.hardware import (
    build_rectangular_hardware_component,
)
from zcad_core.assemblies.interference import (
    ComponentPair,
    InterferenceFinding,
    InterferenceReport,
    analyze_component_interference,
    component_pair,
)
from zcad_core.assemblies.mounting import (
    RectangularMountingMetadata,
    assembly_mounting_hole_positions,
    rectangular_board_mounting_metadata,
)
from zcad_core.assemblies.placement import (
    Placement,
)
from zcad_core.assemblies.retention import (
    BoardClipRegion,
    BoardKeepoutRegion,
    BoardRetentionMetadata,
    board_retention_metadata,
)

__all__ = [
    "AssemblyBounds",
    "AssemblyComponent",
    "BoardClipRegion",
    "BoardKeepoutRegion",
    "BoardRetentionMetadata",
    "ClearanceEnvelope",
    "ClearancePolicy",
    "ComponentPair",
    "DeviceAssembly",
    "EnclosureBoundary",
    "EnclosureSpecification",
    "InterferenceFinding",
    "InterferenceReport",
    "Placement",
    "RectangularBoardSpec",
    "RectangularDisplaySpec",
    "RectangularMountingMetadata",
    "analyze_board_display_assembly",
    "analyze_boundary_clearance",
    "analyze_component_interference",
    "assembly_mounting_hole_positions",
    "board_component_identifier",
    "board_component_identifiers",
    "board_retention_metadata",
    "build_board_assembly",
    "build_board_display_assembly",
    "build_board_edge_connector_component",
    "build_rectangular_hardware_component",
    "component_pair",
    "derive_enclosure_specification",
    "lowest_display_height_mm",
    "rectangular_board_mounting_metadata",
]
