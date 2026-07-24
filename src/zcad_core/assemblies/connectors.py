"""Reusable assembly components for board-edge connectors."""

import cadquery as cq

from zcad_core.assemblies.clearance import (
    ClearanceEnvelope,
)
from zcad_core.assemblies.component import (
    AssemblyComponent,
)
from zcad_core.assemblies.placement import (
    Placement,
)
from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
)


def build_board_edge_connector_component(
    *,
    identifier: str,
    connector: RectangularConnectorSpec,
    board_width_mm: float,
    board_length_mm: float,
    board_thickness_mm: float,
    board_placement: Placement,
    clearance_envelope: ClearanceEnvelope | None = None,
) -> AssemblyComponent:
    """Build and place a rectangular connector on one board edge."""
    if not identifier.strip():
        raise ValueError("connector component identifier must not be empty")

    dimensions = {
        "board_width_mm": board_width_mm,
        "board_length_mm": board_length_mm,
        "board_thickness_mm": board_thickness_mm,
    }

    for name, value in dimensions.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")

    connector.validate()

    if connector.board_edge in {
        "negative_y",
        "positive_y",
    }:
        size_x_mm = connector.width_mm
        size_y_mm = connector.depth_mm
    else:
        size_x_mm = connector.depth_mm
        size_y_mm = connector.width_mm

    if connector.board_edge == "negative_y":
        x_mm = board_placement.x_mm + connector.center_offset_mm
        y_mm = board_placement.y_mm - (board_length_mm / 2) + (connector.depth_mm / 2)
    elif connector.board_edge == "positive_y":
        x_mm = board_placement.x_mm + connector.center_offset_mm
        y_mm = board_placement.y_mm + (board_length_mm / 2) - (connector.depth_mm / 2)
    elif connector.board_edge == "negative_x":
        x_mm = board_placement.x_mm - (board_width_mm / 2) + (connector.depth_mm / 2)
        y_mm = board_placement.y_mm + connector.center_offset_mm
    elif connector.board_edge == "positive_x":
        x_mm = board_placement.x_mm + (board_width_mm / 2) - (connector.depth_mm / 2)
        y_mm = board_placement.y_mm + connector.center_offset_mm
    else:
        raise ValueError(f"unsupported connector board edge: {connector.board_edge}")

    placement = Placement(
        x_mm=x_mm,
        y_mm=y_mm,
        z_mm=(
            board_placement.z_mm
            + board_thickness_mm
            + connector.bottom_offset_from_board_top_mm
        ),
    )

    return AssemblyComponent(
        identifier=identifier,
        geometry=cq.Workplane("XY").box(
            size_x_mm,
            size_y_mm,
            connector.height_mm,
            centered=(True, True, False),
        ),
        placement=placement,
        metadata={
            "kind": "connector",
            "hardware_identifier": connector.identifier,
            "board_edge": connector.board_edge,
            "width_mm": connector.width_mm,
            "depth_mm": connector.depth_mm,
            "height_mm": connector.height_mm,
        },
        clearance_envelope=(
            clearance_envelope
            if clearance_envelope is not None
            else ClearanceEnvelope()
        ),
    )
