"""Reusable board, edge-connector, and display assemblies."""

from typing import Protocol

from zcad_core.assemblies.assembly import (
    DeviceAssembly,
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
from zcad_core.assemblies.hardware import (
    build_rectangular_hardware_component,
)
from zcad_core.assemblies.interference import (
    InterferenceReport,
    component_pair,
)
from zcad_core.assemblies.mounting import (
    rectangular_board_mounting_metadata,
)
from zcad_core.assemblies.placement import (
    Placement,
)
from zcad_core.assemblies.retention import (
    board_retention_metadata,
)
from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
)


class RectangularBoardSpec(Protocol):
    """Structural interface required for a rectangular board."""

    @property
    def identifier(self) -> str: ...

    @property
    def board_width_mm(self) -> float: ...
    @property
    def board_length_mm(self) -> float: ...
    @property
    def board_thickness_mm(self) -> float: ...

    @property
    def usb_connector(self) -> RectangularConnectorSpec: ...


class RectangularDisplaySpec(Protocol):
    """Structural interface required for a rectangular display."""

    @property
    def identifier(self) -> str: ...

    @property
    def module_width_mm(self) -> float: ...
    @property
    def module_height_mm(self) -> float: ...
    @property
    def module_depth_mm(self) -> float: ...

    @property
    def mount_style(self) -> str: ...


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

    _require_unique_identifiers(
        (board_identifier, connector_identifier, display_identifier)
    )

    return DeviceAssembly(
        (
            *_board_components(
                board=board,
                board_placement=board_placement,
                board_clearance=ClearanceEnvelope(
                    positive_z_mm=board_display_clearance_mm,
                ),
                connector_access_clearance_mm=connector_access_clearance_mm,
                board_identifier=board_identifier,
                connector_identifier=connector_identifier,
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


def build_board_assembly(
    *,
    board: RectangularBoardSpec,
    board_placement: Placement,
    connector_access_clearance_mm: float = 0.0,
    board_identifier: str = "board",
    connector_identifier: str = "board_connector",
) -> DeviceAssembly:
    """Build a rectangular board and its edge connector, with no display."""
    _require_unique_identifiers((board_identifier, connector_identifier))

    return DeviceAssembly(
        _board_components(
            board=board,
            board_placement=board_placement,
            board_clearance=ClearanceEnvelope(),
            connector_access_clearance_mm=connector_access_clearance_mm,
            board_identifier=board_identifier,
            connector_identifier=connector_identifier,
        )
    )


def _require_unique_identifiers(identifiers: tuple[str, ...]) -> None:
    for identifier in identifiers:
        if not identifier.strip():
            raise ValueError("component identifiers must not be empty")

    if len(set(identifiers)) != len(identifiers):
        raise ValueError("component identifiers must be unique")


def _board_components(
    *,
    board: RectangularBoardSpec,
    board_placement: Placement,
    board_clearance: ClearanceEnvelope,
    connector_access_clearance_mm: float,
    board_identifier: str,
    connector_identifier: str,
) -> tuple[AssemblyComponent, AssemblyComponent]:
    """The board, with its mounting and retention metadata, and its connector."""
    if connector_access_clearance_mm < 0:
        raise ValueError("connector_access_clearance_mm must not be negative")

    connector = board.usb_connector
    board_mounting = rectangular_board_mounting_metadata(board)
    board_retention = board_retention_metadata(board)

    resolved_board_metadata: dict[str, object] = {}

    if board_mounting is not None:
        resolved_board_metadata["mounting"] = board_mounting

    if board_retention is not None:
        resolved_board_metadata["retention"] = board_retention

    board_metadata = resolved_board_metadata if resolved_board_metadata else None

    return (
        build_rectangular_hardware_component(
            identifier=board_identifier,
            hardware_identifier=board.identifier,
            kind="pcb",
            width_mm=board.board_width_mm,
            depth_mm=board.board_length_mm,
            height_mm=board.board_thickness_mm,
            placement=board_placement,
            clearance_envelope=board_clearance,
            metadata=board_metadata,
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
