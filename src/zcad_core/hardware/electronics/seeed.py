"""Seeed Studio board specifications."""

from dataclasses import dataclass, field

from zcad_core.hardware.electronics.board_components import (
    BoardComponentSpec,
    load_board_components,
)
from zcad_core.hardware.electronics.connectors import (
    RectangularConnectorSpec,
    WallOpeningSpec,
)


def _xiao_esp32s3_usb_connector() -> RectangularConnectorSpec:
    """Return provisional XIAO ESP32-S3 USB-C connector metadata."""
    return RectangularConnectorSpec(
        identifier="USB_C",
        width_mm=9.0,
        height_mm=3.2,
        depth_mm=7.0,
        board_edge="positive_y",
        center_offset_mm=0.0,
        bottom_offset_from_board_top_mm=0.0,
    )


@dataclass(frozen=True)
class SeeedXiaoEsp32S3Spec:
    """Mechanical specification for Seeed Studio XIAO ESP32-S3."""

    identifier: str = "SEEED_XIAO_ESP32_S3"

    geometry_evidence_status: str = "provisional"
    geometry_source: str = (
        "Seeed Studio XIAO ESP32-S3 DXF v1.1 outline; board thickness "
        "measured from the vendor STEP; USB-C envelope unverified"
    )

    board_width_mm: float = 17.8
    board_length_mm: float = 21.0
    board_thickness_mm: float = 1.25

    usb_connector: RectangularConnectorSpec = field(
        default_factory=_xiao_esp32s3_usb_connector
    )

    # Every other part, extracted from the vendor model.
    components: tuple[BoardComponentSpec, ...] = field(
        default_factory=lambda: load_board_components("seeed-xiao-esp32s3")
    )
    # Every part it needs reached through a wall is among the components.
    wall_openings: tuple[WallOpeningSpec, ...] = ()

    recommended_standoff_height_mm: float = 3.0
    recommended_clearance_mm: float = 0.5


_XIAO_ESP32S3 = SeeedXiaoEsp32S3Spec()


def get_seeed_xiao_esp32s3() -> SeeedXiaoEsp32S3Spec:
    """Return the Seeed Studio XIAO ESP32-S3 specification."""
    return _XIAO_ESP32S3
