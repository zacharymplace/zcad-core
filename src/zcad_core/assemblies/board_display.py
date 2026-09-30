"""Reusable board, edge-connector, and display assemblies."""

import math
from dataclasses import replace
from typing import Protocol, runtime_checkable

import cadquery as cq

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
from zcad_core.geometry.cadquery_support import workplane_shape
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


@runtime_checkable
class LayeredDisplaySpec(RectangularDisplaySpec, Protocol):
    """A display modelled as a panel on a PCB over the parts behind it."""

    @property
    def pcb_thickness_mm(self) -> float | None: ...
    @property
    def panel_width_mm(self) -> float | None: ...
    @property
    def panel_height_mm(self) -> float | None: ...
    @property
    def panel_thickness_mm(self) -> float | None: ...
    @property
    def panel_center_x_mm(self) -> float: ...
    @property
    def panel_center_y_mm(self) -> float: ...


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
            _display_component(display, display_placement, display_identifier),
        )
    )


def _display_component(
    display: RectangularDisplaySpec, placement: Placement, identifier: str
) -> AssemblyComponent:
    """The display as a block, or, for a layered spec, as its panel on its
    PCB over the envelope of the parts behind it."""

    component = build_rectangular_hardware_component(
        identifier=identifier,
        hardware_identifier=display.identifier,
        kind="display",
        width_mm=display.module_width_mm,
        depth_mm=display.module_height_mm,
        height_mm=display.module_depth_mm,
        placement=placement,
        metadata={"mount_style": display.mount_style},
    )
    if not isinstance(display, LayeredDisplaySpec) or display.pcb_thickness_mm is None:
        return component

    assert display.panel_width_mm is not None
    assert display.panel_height_mm is not None
    assert display.panel_thickness_mm is not None
    panel_thickness = display.panel_thickness_mm
    below_panel = display.module_depth_mm - panel_thickness
    body = cq.Workplane("XY").box(
        display.module_width_mm,
        display.module_height_mm,
        below_panel,
        centered=(True, True, False),
    )
    panel = (
        cq.Workplane("XY")
        .box(
            display.panel_width_mm,
            display.panel_height_mm,
            panel_thickness,
            centered=(True, True, False),
        )
        .translate(
            (
                display.panel_center_x_mm,
                display.panel_center_y_mm,
                below_panel,
            )
        )
    )

    return replace(component, geometry=body.union(panel))


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


def board_component_identifier(board_identifier: str, component_identifier: str) -> str:
    """The assembly identifier of one of a board's catalogued components."""
    return f"{board_identifier}_{component_identifier}"


def board_component_identifiers(
    assembly: DeviceAssembly, board_identifier: str = "board"
) -> tuple[str, ...]:
    """The identifiers of the parts an assembly places on a board."""
    return tuple(
        component.identifier
        for component in assembly.components
        if component.metadata.get("board_identifier") == board_identifier
    )


def _board_components(
    *,
    board: RectangularBoardSpec,
    board_placement: Placement,
    board_clearance: ClearanceEnvelope,
    connector_access_clearance_mm: float,
    board_identifier: str,
    connector_identifier: str,
) -> tuple[AssemblyComponent, ...]:
    """The board, with its mounting and retention metadata, its connector,
    and each of its catalogued components."""
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

    board_top = board_placement.z_mm + board.board_thickness_mm
    parts: list[AssemblyComponent] = []

    for part in getattr(board, "components", ()):
        part.validate_against_board(board.board_thickness_mm)
        parts.append(
            build_rectangular_hardware_component(
                identifier=board_component_identifier(
                    board_identifier, part.identifier
                ),
                hardware_identifier=f"{board.identifier}:{part.identifier}",
                kind="board_component",
                width_mm=part.width_mm,
                depth_mm=part.depth_mm,
                height_mm=part.height_mm,
                placement=Placement(
                    x_mm=board_placement.x_mm + part.center_x_mm,
                    y_mm=board_placement.y_mm + part.center_y_mm,
                    z_mm=board_top + part.bottom_offset_from_board_top_mm,
                ),
                metadata={
                    "board_identifier": board_identifier,
                    "access_edge": part.access_edge,
                    "lid_vent": part.lid_vent,
                },
            )
        )

    if board_placement.rotation_z_deg and parts:
        raise ValueError("a board with catalogued components must not be rotated")

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
        *parts,
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

    parts = board_component_identifiers(assembly, board_identifier)
    actual_identifiers = set(assembly.identifiers)

    if actual_identifiers != expected_identifiers | set(parts):
        rendered = ", ".join(sorted(expected_identifiers))

        raise ValueError(
            f"board-display assembly must contain exactly: {rendered}, "
            "and the board's catalogued components"
        )

    # The board's own parts touch it and each other; only the display must
    # keep its distance from all of them.
    on_board = (board_identifier, connector_identifier, *parts)
    display_clearance = ClearanceEnvelope(
        positive_z_mm=minimum_board_display_clearance_mm
    )

    return assembly.analyze_interference(
        allowed_contact_pairs=tuple(
            component_pair(first, second)
            for index, first in enumerate(on_board)
            for second in on_board[index + 1 :]
        ),
        clearance_policy=ClearancePolicy(
            component_envelopes={
                identifier: display_clearance
                for identifier in (board_identifier, *parts)
            }
        ),
    )


def lowest_display_height_mm(
    *,
    board: RectangularBoardSpec,
    display: RectangularDisplaySpec,
    board_placement: Placement,
    display_placement: Placement,
    board_display_clearance_mm: float = 0.0,
    connector_access_clearance_mm: float = 0.0,
    minimum_mm: float = 0.0,
    step_mm: float = 0.5,
    limit_mm: float = 60.0,
) -> float:
    """The lowest display height, at least ``minimum_mm`` and otherwise a
    multiple of ``step_mm``, at which the display clears the board and every
    part on it by the clearance.

    It starts just above the tallest part under the display's footprint and
    rises until the board-to-display analysis finds nothing, since a layered
    display can reach lower than its footprint's top suggests. Raises
    ``ValueError`` when no height up to ``limit_mm`` clears.
    """

    if step_mm <= 0:
        raise ValueError("step_mm must be greater than zero")

    def assembly_at(height: float) -> DeviceAssembly:
        return build_board_display_assembly(
            board=board,
            display=display,
            board_placement=board_placement,
            display_placement=replace(display_placement, z_mm=height),
            board_display_clearance_mm=board_display_clearance_mm,
            connector_access_clearance_mm=connector_access_clearance_mm,
        )

    probe = assembly_at(limit_mm)
    footprint = workplane_shape(
        probe.get("display").transformed_geometry()
    ).BoundingBox()
    tallest = board_placement.z_mm + board.board_thickness_mm

    for component in probe.components:
        if component.identifier == "display":
            continue

        bounds = workplane_shape(component.transformed_geometry()).BoundingBox()

        if (
            bounds.xmin < footprint.xmax
            and footprint.xmin < bounds.xmax
            and bounds.ymin < footprint.ymax
            and footprint.ymin < bounds.ymax
        ):
            tallest = max(tallest, bounds.zmax)

    height = max(
        minimum_mm,
        math.ceil((tallest + board_display_clearance_mm) / step_mm) * step_mm,
    )

    while height <= limit_mm:
        report = analyze_board_display_assembly(
            assembly_at(height),
            minimum_board_display_clearance_mm=board_display_clearance_mm,
        )

        if not report.has_findings:
            return height

        height += step_mm

    raise ValueError(
        f"No display height up to {limit_mm:g} mm clears {board.identifier}'s parts"
    )
