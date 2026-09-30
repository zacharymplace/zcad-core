"""Raspberry Pi board specifications."""

from dataclasses import dataclass, field, replace

from zcad_core.hardware.electronics.board_components import (
    BoardComponentSpec,
    load_board_components,
)
from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
    WallOpeningSpec,
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
    # Every part it needs reached through a wall is among the components.
    wall_openings: tuple[WallOpeningSpec, ...] = ()

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
    """Mechanical envelope of a Raspberry Pi 5 and its Active Cooler.

    Portrait frame, origin at the board centre, seen from above: the
    Ethernet and USB edge is ``positive_y``, with Ethernet on the right; the
    USB-C power and micro-HDMI edge is ``positive_x``; the 40-pin header
    runs along ``negative_x``; and the microSD end is ``negative_y``. (An
    earlier version mirrored this left to right; Raspberry Pi's STEP model
    settles it.)

    The numbers come from Raspberry Pi's mechanical drawings, RP-008347 for the
    board and RP-008187 for the Active Cooler, which call themselves
    approximate. The board outline, the 58 x 49 mm hole pattern, and the port
    positions along each edge are dimensioned there. The rest is read off the
    drawings' scale: the on-board length and 3.1 mm overhang of the Ethernet
    and USB blocks, the cooler's footprint and fan position from where its
    push pins meet the board's two cooler holes, and the cooler's height above
    the PCB, which assumes its pin tips are flush with the PCB underside
    (13.7 mm overall less the 1.4 mm board). Measure a real board before
    trusting a 0.5 mm margin. ``components`` are the board's parts as boxes,
    extracted from Raspberry Pi's STEP model, for the single-board enclosure
    builder.
    """

    identifier: str = "RASPBERRY_PI_5"

    board_width_mm: float = 56.0
    board_length_mm: float = 85.0
    board_thickness_mm: float = 1.4

    mounting_hole_diameter_mm: float = 2.7
    mounting_hole_spacing_x_mm: float = 49.0
    mounting_hole_spacing_y_mm: float = 58.0
    # The pattern is not centred on the board: like the HAT footprint, it sits
    # 3.5 mm from the microSD end, 10 mm toward it (the header's centre too).
    # Raspberry Pi's STEP model has the holes here.
    mounting_hole_positions_mm: tuple[tuple[float, float], ...] = (
        (-24.5, -39.0),
        (24.5, -39.0),
        (-24.5, 19.0),
        (24.5, 19.0),
    )
    recommended_standoff_height_mm: float = 4.0
    recommended_clearance_mm: float = 0.0

    ports: tuple[BoardPortSpec, ...] = (
        BoardPortSpec("ETHERNET", "positive_y", 17.8, 16.1, 13.4, 18.2, 3.1),
        BoardPortSpec("USB3_PAIR", "positive_y", -1.1, 13.7, 15.6, 14.0, 3.1),
        BoardPortSpec("USB2_PAIR", "positive_y", -19.0, 13.7, 15.6, 14.0, 3.1),
        BoardPortSpec("USB_C_POWER", "positive_x", -31.3, 9.0, 3.2, 8.0, 0.8),
        BoardPortSpec("MICRO_HDMI_0", "positive_x", -16.7, 7.0, 3.4, 7.0, 0.8),
        BoardPortSpec("MICRO_HDMI_1", "positive_x", -3.3, 7.0, 3.4, 7.0, 0.8),
    )
    # The edge the power cable plugs into, for the single-board enclosure.
    usb_connector: RectangularConnectorSpec = field(
        default_factory=lambda: RectangularConnectorSpec(
            identifier="USB_C_POWER",
            width_mm=9.0,
            height_mm=3.2,
            depth_mm=8.0,
            board_edge="positive_x",
            center_offset_mm=-31.3,
            bottom_offset_from_board_top_mm=0.0,
        )
    )
    components: tuple[BoardComponentSpec, ...] = field(
        default_factory=lambda: load_board_components("raspberry-pi-5")
    )

    # The 2x20 header on the negative_x edge: pins reach 8.3 mm above the PCB.
    header_height_mm: float = 8.5
    header_length_mm: float = 51.0
    header_width_mm: float = 5.1
    header_center_y_mm: float = -10.0
    # The Active Cooler, as one box. Its heatsink base sits on the SoC and
    # its fins clear the connectors, so the box starts above them; the fan is
    # a 30 x 30 mm square over the SoC.
    cooler_width_mm: float = 42.5
    cooler_length_mm: float = 63.5
    cooler_center_x_mm: float = 1.25
    cooler_center_y_mm: float = -10.0
    cooler_bottom_above_board_mm: float = 3.5
    cooler_height_mm: float = 12.5
    fan_center_x_mm: float = -4.6
    fan_center_y_mm: float = 0.1
    fan_size_mm: float = 30.0
    # The microSD card hangs under the board and past the negative_y edge.
    sd_card_width_mm: float = 12.0
    sd_card_overhang_mm: float = 2.5
    sd_card_depth_below_board_mm: float = 1.6

    @property
    def wall_openings(self) -> tuple[WallOpeningSpec, ...]:
        """Openings for the single-board enclosure: every port but the power
        input, which the enclosure's cable opening serves, and the microSD
        card. The vendor model leaves out the micro-HDMI bodies and the card,
        so the extracted parts cannot mark them."""

        ports = tuple(
            WallOpeningSpec(
                identifier=port.identifier,
                edge=port.edge,
                center_offset_mm=port.center_mm,
                bottom_offset_from_board_top_mm=0.0,
                width_mm=port.width_mm,
                height_mm=port.height_mm,
            )
            for port in self.ports
            if port.identifier != self.usb_connector.identifier
        )
        sd_card = WallOpeningSpec(
            identifier="MICRO_SD",
            edge="negative_y",
            center_offset_mm=0.0,
            bottom_offset_from_board_top_mm=-(
                self.board_thickness_mm + self.sd_card_depth_below_board_mm
            ),
            width_mm=self.sd_card_width_mm,
            height_mm=self.sd_card_depth_below_board_mm,
        )

        return (*ports, sd_card)

    def with_active_cooler(self) -> "RaspberryPi5Spec":
        """This board with its Active Cooler fitted, for the single-board
        enclosure: the cooler as one more part, and its fan as a part that
        wants a vent in the lid above it."""

        bottom = self.cooler_bottom_above_board_mm
        height = self.cooler_height_mm - bottom
        cooler = (
            BoardComponentSpec(
                identifier="active-cooler",
                center_x_mm=self.cooler_center_x_mm,
                center_y_mm=self.cooler_center_y_mm,
                width_mm=self.cooler_width_mm,
                depth_mm=self.cooler_length_mm,
                bottom_offset_from_board_top_mm=bottom,
                height_mm=height,
            ),
            BoardComponentSpec(
                identifier="active-cooler-fan",
                center_x_mm=self.fan_center_x_mm,
                center_y_mm=self.fan_center_y_mm,
                width_mm=self.fan_size_mm,
                depth_mm=self.fan_size_mm,
                bottom_offset_from_board_top_mm=bottom,
                height_mm=height,
                lid_vent=True,
            ),
        )

        return replace(self, components=(*self.components, *cooler))


_PI5 = RaspberryPi5Spec()


def get_raspberry_pi5() -> RaspberryPi5Spec:
    """Return the Raspberry Pi 5 specification."""
    return _PI5
