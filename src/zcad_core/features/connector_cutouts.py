"""Reusable enclosure connector-cutout features."""

from dataclasses import dataclass

import cadquery as cq

from zcad_core.assemblies.component import (
    AssemblyComponent,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
)


@dataclass(frozen=True)
class ConnectorCutoutParameters:
    """Geometry parameters for one enclosure connector cutout."""

    edge: BoardEdge
    center_offset_mm: float
    bottom_z_mm: float
    width_mm: float
    height_mm: float
    width_clearance_mm: float = 0.6
    height_clearance_mm: float = 0.6
    cutter_depth_mm: float = 10.0
    cutter_overtravel_mm: float = 1.0

    @classmethod
    def from_connector(
        cls,
        *,
        connector: RectangularConnectorSpec,
        board_top_z_mm: float,
        width_clearance_mm: float = 0.6,
        height_clearance_mm: float = 0.6,
        cutter_depth_mm: float = 10.0,
        cutter_overtravel_mm: float = 1.0,
    ) -> "ConnectorCutoutParameters":
        """Derive cutout geometry from connector metadata."""
        connector.validate()

        return cls(
            edge=connector.board_edge,
            center_offset_mm=(connector.center_offset_mm),
            bottom_z_mm=(board_top_z_mm + connector.bottom_offset_from_board_top_mm),
            width_mm=connector.width_mm,
            height_mm=connector.height_mm,
            width_clearance_mm=width_clearance_mm,
            height_clearance_mm=height_clearance_mm,
            cutter_depth_mm=cutter_depth_mm,
            cutter_overtravel_mm=cutter_overtravel_mm,
        )

    @classmethod
    def from_component(
        cls,
        *,
        component: AssemblyComponent,
        connector: RectangularConnectorSpec,
        width_clearance_mm: float = 0.6,
        height_clearance_mm: float = 0.6,
        cutter_depth_mm: float = 10.0,
        cutter_overtravel_mm: float = 1.0,
    ) -> "ConnectorCutoutParameters":
        """Derive a cutout from one placed connector component."""
        component.validate()
        connector.validate()

        if connector.board_edge in {
            "negative_y",
            "positive_y",
        }:
            center_offset_mm = component.placement.x_mm
        else:
            center_offset_mm = component.placement.y_mm

        return cls(
            edge=connector.board_edge,
            center_offset_mm=center_offset_mm,
            bottom_z_mm=(component.placement.z_mm),
            width_mm=connector.width_mm,
            height_mm=connector.height_mm,
            width_clearance_mm=(width_clearance_mm),
            height_clearance_mm=(height_clearance_mm),
            cutter_depth_mm=cutter_depth_mm,
            cutter_overtravel_mm=(cutter_overtravel_mm),
        )

    @property
    def opening_width_mm(self) -> float:
        """Return finished opening width."""
        return self.width_mm + self.width_clearance_mm

    @property
    def opening_height_mm(self) -> float:
        """Return finished opening height."""
        return self.height_mm + self.height_clearance_mm

    def validate(self) -> None:
        """Validate connector-cutout geometry."""
        positive_values = {
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "cutter_depth_mm": self.cutter_depth_mm,
            "cutter_overtravel_mm": (self.cutter_overtravel_mm),
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.width_clearance_mm < 0:
            raise ValueError("width_clearance_mm must not be negative")

        if self.height_clearance_mm < 0:
            raise ValueError("height_clearance_mm must not be negative")


def cut_connector_opening(
    model: cq.Workplane,
    *,
    parameters: ConnectorCutoutParameters,
) -> cq.Workplane:
    """Cut a rectangular opening through one enclosure edge."""
    parameters.validate()

    bounds = workplane_shape(model).BoundingBox()
    opening_width = parameters.opening_width_mm
    opening_height = parameters.opening_height_mm
    cutter_depth = parameters.cutter_depth_mm + (2 * parameters.cutter_overtravel_mm)
    center_z = parameters.bottom_z_mm + (opening_height / 2)

    if parameters.edge in {
        "negative_y",
        "positive_y",
    }:
        center_x = parameters.center_offset_mm
        center_y = (
            bounds.ymin - parameters.cutter_overtravel_mm
            if parameters.edge == "negative_y"
            else bounds.ymax + parameters.cutter_overtravel_mm
        )

        cutter = (
            cq.Workplane("XY")
            .box(
                opening_width,
                cutter_depth,
                opening_height,
            )
            .translate(
                (
                    center_x,
                    center_y,
                    center_z,
                )
            )
        )

        return model.cut(cutter)

    center_x = (
        bounds.xmin - parameters.cutter_overtravel_mm
        if parameters.edge == "negative_x"
        else bounds.xmax + parameters.cutter_overtravel_mm
    )
    center_y = parameters.center_offset_mm

    cutter = (
        cq.Workplane("XY")
        .box(
            cutter_depth,
            opening_width,
            opening_height,
        )
        .translate(
            (
                center_x,
                center_y,
                center_z,
            )
        )
    )

    return model.cut(cutter)
