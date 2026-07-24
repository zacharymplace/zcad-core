"""Reusable display-window and bezel features."""

from dataclasses import dataclass

import cadquery as cq

from zcad_core.hardware.electronics.displays import (
    DisplaySpec,
)


@dataclass(frozen=True)
class DisplayWindowParameters:
    """Geometry parameters for one display window."""

    x: float
    y: float
    panel_base_z_mm: float
    panel_thickness_mm: float

    opening_width_mm: float
    opening_height_mm: float

    corner_radius_mm: float = 1.0
    cutter_overtravel_mm: float = 0.5

    @classmethod
    def from_display(
        cls,
        *,
        display: DisplaySpec,
        panel_base_z_mm: float,
        panel_thickness_mm: float,
        x: float = 0.0,
        y: float = 0.0,
        window_clearance_mm: float | None = None,
        corner_radius_mm: float = 1.0,
        cutter_overtravel_mm: float = 0.5,
    ) -> "DisplayWindowParameters":
        """Derive a visible window from display metadata."""
        display.validate()

        clearance = (
            display.recommended_window_clearance_mm
            if window_clearance_mm is None
            else window_clearance_mm
        )

        if clearance < 0:
            raise ValueError("window_clearance_mm must not be negative")

        return cls(
            x=x + display.active_center_x_mm,
            y=y + display.active_center_y_mm,
            panel_base_z_mm=panel_base_z_mm,
            panel_thickness_mm=panel_thickness_mm,
            opening_width_mm=(display.active_width_mm + (2 * clearance)),
            opening_height_mm=(display.active_height_mm + (2 * clearance)),
            corner_radius_mm=corner_radius_mm,
            cutter_overtravel_mm=cutter_overtravel_mm,
        )

    def validate(self) -> None:
        """Validate display-window geometry."""
        positive_values = {
            "panel_thickness_mm": self.panel_thickness_mm,
            "opening_width_mm": self.opening_width_mm,
            "opening_height_mm": self.opening_height_mm,
            "cutter_overtravel_mm": (self.cutter_overtravel_mm),
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.corner_radius_mm < 0:
            raise ValueError("corner_radius_mm must not be negative")

        maximum_radius = (
            min(
                self.opening_width_mm,
                self.opening_height_mm,
            )
            / 2
        )

        if self.corner_radius_mm >= maximum_radius:
            raise ValueError("corner_radius_mm is too large for the display opening")


@dataclass(frozen=True)
class DisplayBezelParameters:
    """Geometry parameters for a raised display bezel."""

    x: float
    y: float
    panel_top_z_mm: float

    inner_width_mm: float
    inner_height_mm: float

    bezel_wall_mm: float = 1.5
    bezel_height_mm: float = 0.8
    corner_radius_mm: float = 1.0

    @classmethod
    def from_window(
        cls,
        *,
        window: DisplayWindowParameters,
        bezel_wall_mm: float = 1.5,
        bezel_height_mm: float = 0.8,
    ) -> "DisplayBezelParameters":
        """Derive bezel geometry from a display window."""
        window.validate()

        return cls(
            x=window.x,
            y=window.y,
            panel_top_z_mm=(window.panel_base_z_mm + window.panel_thickness_mm),
            inner_width_mm=window.opening_width_mm,
            inner_height_mm=window.opening_height_mm,
            bezel_wall_mm=bezel_wall_mm,
            bezel_height_mm=bezel_height_mm,
            corner_radius_mm=window.corner_radius_mm,
        )

    def validate(self) -> None:
        """Validate display-bezel geometry."""
        positive_values = {
            "inner_width_mm": self.inner_width_mm,
            "inner_height_mm": self.inner_height_mm,
            "bezel_wall_mm": self.bezel_wall_mm,
            "bezel_height_mm": self.bezel_height_mm,
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.corner_radius_mm < 0:
            raise ValueError("corner_radius_mm must not be negative")

        maximum_radius = (
            min(
                self.inner_width_mm,
                self.inner_height_mm,
            )
            / 2
        )

        if self.corner_radius_mm >= maximum_radius:
            raise ValueError("corner_radius_mm is too large for the display bezel")


def _rounded_prism(
    *,
    width_mm: float,
    height_mm: float,
    depth_mm: float,
    base_z_mm: float,
    x: float,
    y: float,
    radius_mm: float,
) -> cq.Workplane:
    """Build a positioned rectangular or rounded prism."""
    prism = cq.Workplane("XY").box(
        width_mm,
        height_mm,
        depth_mm,
        centered=(True, True, False),
    )

    if radius_mm > 0:
        prism = prism.edges("|Z").fillet(radius_mm)

    return prism.translate(
        (
            x,
            y,
            base_z_mm,
        )
    )


def cut_display_window(
    model: cq.Workplane,
    *,
    parameters: DisplayWindowParameters,
) -> cq.Workplane:
    """Cut a rounded display window through a panel."""
    parameters.validate()

    cutter = _rounded_prism(
        width_mm=parameters.opening_width_mm,
        height_mm=parameters.opening_height_mm,
        depth_mm=(
            parameters.panel_thickness_mm + (2 * parameters.cutter_overtravel_mm)
        ),
        base_z_mm=(parameters.panel_base_z_mm - parameters.cutter_overtravel_mm),
        x=parameters.x,
        y=parameters.y,
        radius_mm=parameters.corner_radius_mm,
    )

    return model.cut(cutter)


def add_display_bezel(
    model: cq.Workplane,
    *,
    parameters: DisplayBezelParameters,
) -> cq.Workplane:
    """Add a raised rounded bezel around a display window."""
    parameters.validate()

    outer_width_mm = parameters.inner_width_mm + (2 * parameters.bezel_wall_mm)
    outer_height_mm = parameters.inner_height_mm + (2 * parameters.bezel_wall_mm)
    outer_radius_mm = parameters.corner_radius_mm + parameters.bezel_wall_mm

    outer = _rounded_prism(
        width_mm=outer_width_mm,
        height_mm=outer_height_mm,
        depth_mm=parameters.bezel_height_mm,
        base_z_mm=parameters.panel_top_z_mm,
        x=parameters.x,
        y=parameters.y,
        radius_mm=outer_radius_mm,
    )

    inner = _rounded_prism(
        width_mm=parameters.inner_width_mm,
        height_mm=parameters.inner_height_mm,
        depth_mm=parameters.bezel_height_mm + 0.2,
        base_z_mm=parameters.panel_top_z_mm - 0.1,
        x=parameters.x,
        y=parameters.y,
        radius_mm=parameters.corner_radius_mm,
    )

    bezel = outer.cut(inner)

    return model.union(bezel)
