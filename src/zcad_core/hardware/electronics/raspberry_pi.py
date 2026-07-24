"""Raspberry Pi board specifications."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RaspberryPiPico2Spec:
    """Mechanical specification for Raspberry Pi Pico 2."""

    identifier: str = "RASPBERRY_PI_PICO_2"

    board_width_mm: float = 21.0
    board_length_mm: float = 51.0
    board_thickness_mm: float = 1.0

    usb_connector_width_mm: float = 8.9
    usb_connector_height_mm: float = 3.2

    mounting_hole_diameter_mm: float = 2.1
    mounting_hole_spacing_x_mm: float = 11.4
    mounting_hole_spacing_y_mm: float = 47.0

    recommended_standoff_height_mm: float = 3.0
    recommended_clearance_mm: float = 0.5


_PICO2 = RaspberryPiPico2Spec()


def get_raspberry_pi_pico2() -> RaspberryPiPico2Spec:
    """Return the Raspberry Pi Pico 2 specification."""
    return _PICO2
