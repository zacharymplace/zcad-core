"""Reusable PCB mounting features."""

from dataclasses import dataclass
from typing import Protocol

import cadquery as cq


class MountableBoardSpec(Protocol):
    """Mechanical board properties required by PCB mounting features."""

    @property
    def mounting_hole_diameter_mm(self) -> float: ...
    @property
    def mounting_hole_spacing_x_mm(self) -> float: ...
    @property
    def mounting_hole_spacing_y_mm(self) -> float: ...
    @property
    def recommended_standoff_height_mm(self) -> float: ...
    @property
    def recommended_clearance_mm(self) -> float: ...


@dataclass(frozen=True)
class PcbStandoffParameters:
    """Geometry parameters for one PCB standoff."""

    x: float
    y: float
    base_height_mm: float
    standoff_height_mm: float
    outer_diameter_mm: float
    hole_diameter_mm: float
    base_z_mm: float = 0.0

    @classmethod
    def from_board(
        cls,
        *,
        board: MountableBoardSpec,
        x: float = 0.0,
        y: float = 0.0,
        base_height_mm: float,
        base_z_mm: float = 0.0,
        standoff_height_mm: float | None = None,
        radial_wall_mm: float = 1.5,
        hole_clearance_mm: float | None = None,
    ) -> "PcbStandoffParameters":
        """Derive standoff geometry from a board specification."""
        if base_height_mm <= 0:
            raise ValueError("base_height_mm must be greater than zero")

        if radial_wall_mm <= 0:
            raise ValueError("radial_wall_mm must be greater than zero")

        resolved_height = (
            standoff_height_mm
            if standoff_height_mm is not None
            else board.recommended_standoff_height_mm
        )

        if resolved_height <= 0:
            raise ValueError("standoff_height_mm must be greater than zero")

        resolved_clearance = (
            hole_clearance_mm
            if hole_clearance_mm is not None
            else board.recommended_clearance_mm
        )

        if resolved_clearance < 0:
            raise ValueError("hole_clearance_mm must not be negative")

        hole_diameter = board.mounting_hole_diameter_mm + resolved_clearance

        return cls(
            x=x,
            y=y,
            base_height_mm=base_height_mm,
            standoff_height_mm=resolved_height,
            outer_diameter_mm=(hole_diameter + (2 * radial_wall_mm)),
            hole_diameter_mm=hole_diameter,
            base_z_mm=base_z_mm,
        )

    def validate(self) -> None:
        """Validate PCB standoff geometry."""
        positive_values = {
            "base_height_mm": self.base_height_mm,
            "standoff_height_mm": self.standoff_height_mm,
            "outer_diameter_mm": self.outer_diameter_mm,
            "hole_diameter_mm": self.hole_diameter_mm,
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.outer_diameter_mm <= self.hole_diameter_mm:
            raise ValueError("outer diameter must exceed hole diameter")


def centered_mounting_hole_positions(
    board: MountableBoardSpec,
) -> tuple[tuple[float, float], ...]:
    """Return the board mounting-hole pattern about the origin."""
    half_x = board.mounting_hole_spacing_x_mm / 2
    half_y = board.mounting_hole_spacing_y_mm / 2

    return (
        (-half_x, -half_y),
        (half_x, -half_y),
        (-half_x, half_y),
        (half_x, half_y),
    )


def add_pcb_standoff(
    model: cq.Workplane,
    *,
    parameters: PcbStandoffParameters,
) -> cq.Workplane:
    """Add one PCB standoff and cut its mounting hole."""
    parameters.validate()

    standoff = (
        cq.Workplane("XY")
        .workplane(
            offset=(parameters.base_z_mm + parameters.base_height_mm),
        )
        .center(
            parameters.x,
            parameters.y,
        )
        .circle(
            parameters.outer_diameter_mm / 2,
        )
        .extrude(
            parameters.standoff_height_mm,
        )
    )

    mounting_hole = (
        cq.Workplane("XY")
        .workplane(
            offset=parameters.base_z_mm,
        )
        .center(
            parameters.x,
            parameters.y,
        )
        .circle(
            parameters.hole_diameter_mm / 2,
        )
        .extrude(
            parameters.base_height_mm + parameters.standoff_height_mm,
        )
    )

    return model.union(standoff).cut(mounting_hole)


def add_board_standoffs(
    model: cq.Workplane,
    *,
    board: MountableBoardSpec,
    base_height_mm: float,
    base_z_mm: float = 0.0,
    standoff_height_mm: float | None = None,
    radial_wall_mm: float = 1.5,
    hole_clearance_mm: float | None = None,
) -> cq.Workplane:
    """Add a centered four-standoff pattern for a board."""
    result = model

    for x, y in centered_mounting_hole_positions(
        board,
    ):
        parameters = PcbStandoffParameters.from_board(
            board=board,
            x=x,
            y=y,
            base_height_mm=base_height_mm,
            base_z_mm=base_z_mm,
            standoff_height_mm=standoff_height_mm,
            radial_wall_mm=radial_wall_mm,
            hole_clearance_mm=hole_clearance_mm,
        )

        result = add_pcb_standoff(
            result,
            parameters=parameters,
        )

    return result
