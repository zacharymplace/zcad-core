"""Raspberry Pi board specifications."""

from dataclasses import dataclass, field

from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
)


def _pico2_usb_connector() -> RectangularConnectorSpec:
    """Return Pico 2 USB connector placement metadata."""
    return RectangularConnectorSpec(
        identifier="USB_MICRO_B",
        width_mm=8.9,
        height_mm=3.2,
        board_edge="negative_y",
        center_offset_mm=0.0,
        bottom_offset_from_board_top_mm=0.0,
    )


@dataclass(frozen=True)
class RaspberryPiPico2Spec:
    """Mechanical specification for Raspberry Pi Pico 2."""

    identifier: str = "RASPBERRY_PI_PICO_2"

    board_width_mm: float = 21.0
    board_length_mm: float = 51.0
    board_thickness_mm: float = 1.0

    usb_connector_width_mm: float = 8.9
    usb_connector_height_mm: float = 3.2
    usb_connector: RectangularConnectorSpec = field(
        default_factory=_pico2_usb_connector
    )

    mounting_hole_diameter_mm: float = 2.1
    mounting_hole_spacing_x_mm: float = 11.4
    mounting_hole_spacing_y_mm: float = 47.0

    recommended_standoff_height_mm: float = 3.0
    recommended_clearance_mm: float = 0.5


_PICO2 = RaspberryPiPico2Spec()


def get_raspberry_pi_pico2() -> RaspberryPiPico2Spec:
    """Return the Raspberry Pi Pico 2 specification."""
    return _PICO2
