"""Reusable electronic display specifications."""

from dataclasses import dataclass
from typing import Literal

DisplayMountStyle = Literal[
    "adhesive",
    "bezel",
    "screws",
    "snap",
]


@dataclass(frozen=True)
class DisplaySpec:
    """Mechanical specification for an electronic display module."""

    identifier: str

    module_width_mm: float
    module_height_mm: float
    module_depth_mm: float

    active_width_mm: float
    active_height_mm: float

    active_center_x_mm: float = 0.0
    active_center_y_mm: float = 0.0

    mounting_hole_diameter_mm: float | None = None
    mounting_hole_spacing_x_mm: float | None = None
    mounting_hole_spacing_y_mm: float | None = None

    mount_style: DisplayMountStyle = "bezel"

    recommended_window_clearance_mm: float = 0.4
    recommended_module_clearance_mm: float = 0.5

    def validate(self) -> None:
        """Validate display geometry and mounting metadata."""
        if not self.identifier.strip():
            raise ValueError("identifier must not be empty")

        positive_values = {
            "module_width_mm": self.module_width_mm,
            "module_height_mm": self.module_height_mm,
            "module_depth_mm": self.module_depth_mm,
            "active_width_mm": self.active_width_mm,
            "active_height_mm": self.active_height_mm,
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.active_width_mm > self.module_width_mm:
            raise ValueError("active_width_mm must not exceed module_width_mm")

        if self.active_height_mm > self.module_height_mm:
            raise ValueError("active_height_mm must not exceed module_height_mm")

        if self.recommended_window_clearance_mm < 0:
            raise ValueError("recommended_window_clearance_mm must not be negative")

        if self.recommended_module_clearance_mm < 0:
            raise ValueError("recommended_module_clearance_mm must not be negative")

        mounting_values = (
            self.mounting_hole_diameter_mm,
            self.mounting_hole_spacing_x_mm,
            self.mounting_hole_spacing_y_mm,
        )

        defined_mounting_values = tuple(value is not None for value in mounting_values)

        if any(defined_mounting_values) and not all(defined_mounting_values):
            raise ValueError(
                "mounting-hole diameter and both spacing "
                "values must be defined together"
            )

        for mounting_value in mounting_values:
            if mounting_value is not None and mounting_value <= 0:
                raise ValueError("mounting-hole values must be greater than zero")


# A deliberately vendor-neutral reference used to exercise the
# display subsystem. It is not presented as a drop-in match for
# any particular commercial module.
REFERENCE_OLED_128X64 = DisplaySpec(
    identifier="REFERENCE_OLED_128X64",
    module_width_mm=28.0,
    module_height_mm=28.0,
    module_depth_mm=4.0,
    active_width_mm=22.0,
    active_height_mm=11.0,
    mount_style="bezel",
)


def get_reference_oled_128x64() -> DisplaySpec:
    """Return the vendor-neutral 128 × 64 OLED reference."""
    return REFERENCE_OLED_128X64
