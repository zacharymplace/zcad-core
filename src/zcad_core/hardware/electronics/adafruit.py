"""Adafruit board specifications."""

from dataclasses import dataclass, field

from zcad_core.hardware.electronics.board_components import (
    BoardComponentSpec,
    load_board_components,
)
from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
    WallOpeningSpec,
)


def _feather_rp2040_usb_connector() -> RectangularConnectorSpec:
    """Return Feather RP2040 USB-C connector placement metadata."""
    # A mid-mount receptacle: in the vendor model it runs from 0.9 mm below
    # the board top to 3.3 mm above, and overhangs the edge by 1.15 mm.
    return RectangularConnectorSpec(
        identifier="USB_C",
        width_mm=8.94,
        height_mm=3.3,
        depth_mm=6.75,
        board_edge="negative_y",
        center_offset_mm=0.0,
        bottom_offset_from_board_top_mm=0.0,
    )


@dataclass(frozen=True)
class AdafruitFeatherRp2040Spec:
    """Mechanical specification for Adafruit Feather RP2040 (product 4884)."""

    identifier: str = "ADAFRUIT_FEATHER_RP2040"

    geometry_source: str = (
        "Adafruit 4884 Feather RP2040 STEP: PCB outline, mounting holes, "
        "and USB-C position measured from the vendor model"
    )

    board_width_mm: float = 22.86
    board_length_mm: float = 50.8
    board_thickness_mm: float = 1.57

    usb_connector: RectangularConnectorSpec = field(
        default_factory=_feather_rp2040_usb_connector
    )

    mounting_hole_diameter_mm: float = 2.5
    mounting_hole_spacing_x_mm: float = 17.78
    mounting_hole_spacing_y_mm: float = 45.72

    # Every other part, extracted from the vendor model.
    components: tuple[BoardComponentSpec, ...] = field(
        default_factory=lambda: load_board_components("adafruit-feather-rp2040")
    )
    # Every part it needs reached through a wall is among the components.
    wall_openings: tuple[WallOpeningSpec, ...] = ()

    recommended_standoff_height_mm: float = 3.0
    recommended_clearance_mm: float = 0.5


_FEATHER_RP2040 = AdafruitFeatherRp2040Spec()


def get_adafruit_feather_rp2040() -> AdafruitFeatherRp2040Spec:
    """Return the Adafruit Feather RP2040 specification."""
    return _FEATHER_RP2040
