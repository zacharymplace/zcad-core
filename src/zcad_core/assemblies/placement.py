"""Reusable component placement transforms."""

from dataclasses import dataclass

import cadquery as cq


@dataclass(frozen=True)
class Placement:
    """Translation and Euler rotation for an assembly component."""

    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = 0.0

    rotation_x_deg: float = 0.0
    rotation_y_deg: float = 0.0
    rotation_z_deg: float = 0.0

    def apply(
        self,
        model: cq.Workplane,
    ) -> cq.Workplane:
        """Return geometry transformed into assembly coordinates."""
        transformed = model

        if self.rotation_x_deg:
            transformed = transformed.rotate(
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                self.rotation_x_deg,
            )

        if self.rotation_y_deg:
            transformed = transformed.rotate(
                (0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                self.rotation_y_deg,
            )

        if self.rotation_z_deg:
            transformed = transformed.rotate(
                (0.0, 0.0, 0.0),
                (0.0, 0.0, 1.0),
                self.rotation_z_deg,
            )

        return transformed.translate(
            (
                self.x_mm,
                self.y_mm,
                self.z_mm,
            )
        )
