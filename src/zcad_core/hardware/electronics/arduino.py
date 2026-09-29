"""Arduino board specifications."""

from dataclasses import dataclass, field

from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
)


def _uno_r4_wifi_usb_connector() -> RectangularConnectorSpec:
    """Return UNO R4 WiFi USB-C connector placement metadata."""
    return RectangularConnectorSpec(
        identifier="USB_C",
        width_mm=9.54,
        height_mm=3.2,
        depth_mm=5.94,
        board_edge="negative_x",
        center_offset_mm=11.2,
        bottom_offset_from_board_top_mm=0.0,
    )


@dataclass(frozen=True)
class ArduinoUnoR4WifiSpec:
    """Mechanical specification for Arduino UNO R4 WiFi."""

    identifier: str = "ARDUINO_UNO_R4_WIFI"

    geometry_evidence_status: str = "provisional"
    geometry_source: str = (
        "Arduino UNO R4 WiFi STEP for the PCB outline and USB-C position; "
        "the model has no mounting holes, so they follow the UNO form-factor "
        "drawing. The barrel jack beside the USB-C is not modelled."
    )

    board_width_mm: float = 68.58
    board_length_mm: float = 53.34
    board_thickness_mm: float = 1.61

    usb_connector: RectangularConnectorSpec = field(
        default_factory=_uno_r4_wifi_usb_connector
    )

    mounting_hole_diameter_mm: float = 3.2
    # About the board centre; the UNO pattern is not a rectangle.
    mounting_hole_positions_mm: tuple[tuple[float, float], ...] = (
        (-20.32, -24.13),
        (-19.05, 24.13),
        (31.75, -19.05),
        (31.75, 8.89),
    )

    recommended_standoff_height_mm: float = 3.0
    recommended_clearance_mm: float = 0.5


_UNO_R4_WIFI = ArduinoUnoR4WifiSpec()


def get_arduino_uno_r4_wifi() -> ArduinoUnoR4WifiSpec:
    """Return the Arduino UNO R4 WiFi specification."""
    return _UNO_R4_WIFI
