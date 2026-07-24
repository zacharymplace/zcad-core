"""Reusable enclosure-boundary proxies and clearance analysis."""

from dataclasses import dataclass

import cadquery as cq

from zcad_core.assemblies.component import (
    AssemblyComponent,
)
from zcad_core.assemblies.interference import (
    InterferenceReport,
    analyze_component_interference,
)
from zcad_core.assemblies.placement import (
    Placement,
)
from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
)


@dataclass(frozen=True)
class EnclosureBoundary:
    """Rectangular cavity boundary used for wall-specific analysis."""

    inner_width_mm: float
    inner_depth_mm: float
    wall_height_mm: float
    wall_thickness_mm: float

    center_x_mm: float = 0.0
    center_y_mm: float = 0.0
    bottom_z_mm: float = 0.0

    def __post_init__(self) -> None:
        """Validate boundary dimensions."""
        positive_values = {
            "inner_width_mm": self.inner_width_mm,
            "inner_depth_mm": self.inner_depth_mm,
            "wall_height_mm": self.wall_height_mm,
            "wall_thickness_mm": self.wall_thickness_mm,
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

    def wall_component(
        self,
        *,
        edge: BoardEdge,
        identifier: str | None = None,
    ) -> AssemblyComponent:
        """Return one narrow wall proxy for a lateral cavity edge."""
        resolved_identifier = identifier if identifier is not None else f"{edge}_wall"

        if not resolved_identifier.strip():
            raise ValueError("wall identifier must not be empty")

        if edge in {
            "negative_x",
            "positive_x",
        }:
            size_x_mm = self.wall_thickness_mm
            size_y_mm = self.inner_depth_mm

            offset_x_mm = (self.inner_width_mm / 2) + (self.wall_thickness_mm / 2)

            placement = Placement(
                x_mm=(
                    self.center_x_mm - offset_x_mm
                    if edge == "negative_x"
                    else self.center_x_mm + offset_x_mm
                ),
                y_mm=self.center_y_mm,
                z_mm=self.bottom_z_mm,
            )
        elif edge in {
            "negative_y",
            "positive_y",
        }:
            size_x_mm = self.inner_width_mm
            size_y_mm = self.wall_thickness_mm

            offset_y_mm = (self.inner_depth_mm / 2) + (self.wall_thickness_mm / 2)

            placement = Placement(
                x_mm=self.center_x_mm,
                y_mm=(
                    self.center_y_mm - offset_y_mm
                    if edge == "negative_y"
                    else self.center_y_mm + offset_y_mm
                ),
                z_mm=self.bottom_z_mm,
            )
        else:
            raise ValueError(f"unsupported enclosure boundary edge: {edge}")

        return AssemblyComponent(
            identifier=resolved_identifier,
            geometry=cq.Workplane("XY").box(
                size_x_mm,
                size_y_mm,
                self.wall_height_mm,
                centered=(True, True, False),
            ),
            placement=placement,
            metadata={
                "kind": "enclosure_wall",
                "edge": edge,
                "inner_width_mm": self.inner_width_mm,
                "inner_depth_mm": self.inner_depth_mm,
                "wall_height_mm": self.wall_height_mm,
                "wall_thickness_mm": (self.wall_thickness_mm),
            },
        )


def analyze_boundary_clearance(
    *,
    component: AssemblyComponent,
    boundary: EnclosureBoundary,
    edge: BoardEdge,
    wall_identifier: str | None = None,
) -> InterferenceReport:
    """Analyze one component against one enclosure wall."""
    wall = boundary.wall_component(
        edge=edge,
        identifier=wall_identifier,
    )

    return analyze_component_interference(
        (
            component,
            wall,
        )
    )
