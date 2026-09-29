"""Raspberry Pi board specifications."""

from dataclasses import dataclass, field

from zcad_core.hardware.electronics.board_components import (
    BoardComponentSpec,
    load_board_components,
)
from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
)


def _pico2_usb_connector() -> RectangularConnectorSpec:
    """Return Pico 2 USB connector placement metadata."""
    return RectangularConnectorSpec(
        identifier="USB_MICRO_B",
        width_mm=8.9,
        height_mm=3.2,
        depth_mm=6.075,
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

    # Every other part, extracted from the vendor model.
    components: tuple[BoardComponentSpec, ...] = field(
        default_factory=lambda: load_board_components("raspberry-pi-pico-2")
    )

    recommended_standoff_height_mm: float = 3.0
    recommended_clearance_mm: float = 0.5


_PICO2 = RaspberryPiPico2Spec()


def get_raspberry_pi_pico2() -> RaspberryPiPico2Spec:
    """Return the Raspberry Pi Pico 2 specification."""
    return _PICO2


@dataclass(frozen=True)
class BoardPortSpec:
    """A connector envelope on a board edge, in the board's own frame.

    ``center_mm`` runs along the edge from the board centre; the envelope
    reaches ``overhang_mm`` past the board edge and ``depth_mm`` in from it.
    """

    identifier: str
    edge: BoardEdge
    center_mm: float
    width_mm: float
    height_mm: float
    depth_mm: float
    overhang_mm: float


@dataclass(frozen=True)
class RaspberryPi5Spec:
    """Mechanical envelope of a Raspberry Pi 5, from the published drawing.

    Portrait frame, origin at the board centre: the Ethernet and USB edge is
    ``positive_y``, the USB-C power and micro-HDMI edge is ``negative_x``,
    the 40-pin header edge is ``positive_x``, and the microSD end is
    ``negative_y``. Envelopes are hand-built, not read from a vendor model,
    so measure a real board before trusting a 0.5 mm margin.
    """

    identifier: str = "RASPBERRY_PI_5"

    board_width_mm: float = 56.0
    board_length_mm: float = 85.0
    board_thickness_mm: float = 1.4

    mounting_hole_diameter_mm: float = 2.7
    mounting_hole_spacing_x_mm: float = 49.0
    mounting_hole_spacing_y_mm: float = 58.0
    recommended_standoff_height_mm: float = 4.0
    recommended_clearance_mm: float = 0.0

    ports: tuple[BoardPortSpec, ...] = (
        BoardPortSpec("ETHERNET", "positive_y", -17.75, 16.0, 13.5, 21.0, 1.5),
        BoardPortSpec("USB3_PAIR", "positive_y", 1.0, 13.1, 15.6, 17.5, 2.0),
        BoardPortSpec("USB2_PAIR", "positive_y", 19.0, 13.1, 15.6, 17.5, 2.0),
        BoardPortSpec("USB_C_POWER", "negative_x", -31.3, 9.0, 3.3, 8.0, 0.8),
        BoardPortSpec("MICRO_HDMI_0", "negative_x", -16.5, 7.0, 3.5, 7.0, 0.8),
        BoardPortSpec("MICRO_HDMI_1", "negative_x", -3.0, 7.0, 3.5, 7.0, 0.8),
    )

    # The 2x20 header on the positive_x edge, and the tallest thing a
    # standard Active Cooler adds over the SoC, centred on it.
    header_height_mm: float = 8.5
    header_length_mm: float = 51.0
    header_width_mm: float = 5.1
    header_center_y_mm: float = -10.0
    cooler_width_mm: float = 41.0
    cooler_length_mm: float = 41.0
    cooler_height_mm: float = 15.0
    cooler_center_y_mm: float = -9.5
    # The microSD card hangs under the board and past the negative_y edge.
    sd_card_width_mm: float = 12.0
    sd_card_overhang_mm: float = 2.5
    sd_card_depth_below_board_mm: float = 1.6


_PI5 = RaspberryPi5Spec()


def get_raspberry_pi5() -> RaspberryPi5Spec:
    """Return the Raspberry Pi 5 specification."""
    return _PI5
