"""Reusable board, edge-connector, and display assemblies."""

from typing import Protocol

from zcad_core.assemblies.assembly import (
    DeviceAssembly,
)
from zcad_core.assemblies.clearance import (
    ClearanceEnvelope,
    ClearancePolicy,
)
from zcad_core.assemblies.connectors import (
    build_board_edge_connector_component,
)
from zcad_core.assemblies.hardware import (
    build_rectangular_hardware_component,
)
from zcad_core.assemblies.interference import (
    InterferenceReport,
    component_pair,
)
from zcad_core.assemblies.placement import (
    Placement,
)
from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
)


class RectangularBoardSpec(Protocol):
    """Structural interface required for a rectangular board."""

    identifier: str

    board_width_mm: float
    board_length_mm: float
    board_thickness_mm: float

    usb_connector: RectangularConnectorSpec


class RectangularDisplaySpec(Protocol):
    """Structural interface required for a rectangular display."""

    identifier: str

    module_width_mm: float
    module_height_mm: float
    module_depth_mm: float

    mount_style: str


def build_board_display_assembly(
    *,
    board: RectangularBoardSpec,
    display: RectangularDisplaySpec,
    board_placement: Placement,
    display_placement: Placement,
    board_display_clearance_mm: float = 0.0,
    connector_access_clearance_mm: float = 0.0,
    board_identifier: str = "board",
    connector_identifier: str = "board_connector",
    display_identifier: str = "display",
) -> DeviceAssembly:
    """Build a rectangular board, connector, and display assembly."""
    if board_display_clearance_mm < 0:
        raise ValueError("board_display_clearance_mm must not be negative")

    if connector_access_clearance_mm < 0:
        raise ValueError("connector_access_clearance_mm must not be negative")

    component_identifiers = (
        board_identifier,
        connector_identifier,
        display_identifier,
    )

    for identifier in component_identifiers:
        if not identifier.strip():
            raise ValueError("component identifiers must not be empty")

    if len(set(component_identifiers)) != len(component_identifiers):
        raise ValueError("component identifiers must be unique")

    connector = board.usb_connector

    return DeviceAssembly(
        (
            build_rectangular_hardware_component(
                identifier=board_identifier,
                hardware_identifier=board.identifier,
                kind="pcb",
                width_mm=board.board_width_mm,
                depth_mm=board.board_length_mm,
                height_mm=board.board_thickness_mm,
                placement=board_placement,
                clearance_envelope=ClearanceEnvelope(
                    positive_z_mm=board_display_clearance_mm,
                ),
            ),
            build_board_edge_connector_component(
                identifier=connector_identifier,
                connector=connector,
                board_width_mm=board.board_width_mm,
                board_length_mm=board.board_length_mm,
                board_thickness_mm=board.board_thickness_mm,
                board_placement=board_placement,
                clearance_envelope=ClearanceEnvelope.for_edge(
                    edge=connector.board_edge,
                    clearance_mm=connector_access_clearance_mm,
                ),
            ),
            build_rectangular_hardware_component(
                identifier=display_identifier,
                hardware_identifier=display.identifier,
                kind="display",
                width_mm=display.module_width_mm,
                depth_mm=display.module_height_mm,
                height_mm=display.module_depth_mm,
                placement=display_placement,
                metadata={
                    "mount_style": display.mount_style,
                },
            ),
        )
    )


def analyze_board_display_assembly(
    assembly: DeviceAssembly,
    *,
    minimum_board_display_clearance_mm: float = 0.0,
    board_identifier: str = "board",
    connector_identifier: str = "board_connector",
    display_identifier: str = "display",
) -> InterferenceReport:
    """Analyze board attachment and board-to-display clearance."""
    if minimum_board_display_clearance_mm < 0:
        raise ValueError("minimum_board_display_clearance_mm must not be negative")

    expected_identifiers = {
        board_identifier,
        connector_identifier,
        display_identifier,
    }

    if any(not identifier.strip() for identifier in expected_identifiers):
        raise ValueError("component identifiers must not be empty")

    if len(expected_identifiers) != 3:
        raise ValueError("component identifiers must be unique")

    actual_identifiers = set(assembly.identifiers)

    if actual_identifiers != expected_identifiers:
        rendered = ", ".join(sorted(expected_identifiers))

        raise ValueError(f"board-display assembly must contain exactly: {rendered}")

    return assembly.analyze_interference(
        allowed_contact_pairs=(
            component_pair(
                board_identifier,
                connector_identifier,
            ),
        ),
        clearance_policy=ClearancePolicy(
            component_envelopes={
                board_identifier: ClearanceEnvelope(
                    positive_z_mm=(minimum_board_display_clearance_mm),
                ),
            }
        ),
    )
