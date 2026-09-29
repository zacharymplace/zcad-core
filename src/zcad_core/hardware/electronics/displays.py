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

    # A real module in layers, face up: parts on the back, the PCB, then the
    # glass panel. Left unset, the module is one solid block. ``module_depth``
    # is the whole stack; the panel is centred on ``panel_center_*`` and the
    # active area and mounting holes on the PCB centre.
    pcb_thickness_mm: float | None = None
    panel_width_mm: float | None = None
    panel_height_mm: float | None = None
    panel_thickness_mm: float | None = None
    panel_center_x_mm: float = 0.0
    panel_center_y_mm: float = 0.0

    geometry_evidence_status: str = "reference"
    geometry_source: str = ""

    @property
    def is_layered(self) -> bool:
        return self.pcb_thickness_mm is not None

    @property
    def back_depth_mm(self) -> float:
        """Depth of the parts behind the PCB (zero for a solid block)."""
        if self.pcb_thickness_mm is None or self.panel_thickness_mm is None:
            return 0.0

        return self.module_depth_mm - self.pcb_thickness_mm - self.panel_thickness_mm

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

        self._validate_layers()

    def _validate_layers(self) -> None:
        layers = (
            self.pcb_thickness_mm,
            self.panel_width_mm,
            self.panel_height_mm,
            self.panel_thickness_mm,
        )

        if not any(value is not None for value in layers):
            return

        if any(value is None or value <= 0 for value in layers):
            raise ValueError(
                "a layered display needs a positive PCB thickness and panel "
                "width, height, and thickness"
            )

        if self.back_depth_mm < 0:
            raise ValueError("module_depth_mm must hold the panel and the PCB")

        assert self.panel_width_mm is not None and self.panel_height_mm is not None

        if (
            abs(self.panel_center_x_mm) + self.panel_width_mm / 2
            > self.module_width_mm / 2 + 1e-6
            or abs(self.panel_center_y_mm) + self.panel_height_mm / 2
            > self.module_height_mm / 2 + 1e-6
        ):
            raise ValueError("the panel must lie within the module outline")


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


# Adafruit breakouts, measured from Adafruit's CAD models
# (github.com/adafruit/Adafruit_CAD_Parts, kept in evidence/) with the
# panels' active areas from their datasheets. Each has four 2.5 mm holes.

ADAFRUIT_OLED_128X64_1_3IN = DisplaySpec(
    identifier="ADAFRUIT_OLED_128X64_1_3IN",
    module_width_mm=35.56,
    module_height_mm=33.02,
    # 2.0 panel, 1.57 PCB, 2.96 STEMMA QT connectors behind.
    module_depth_mm=6.53,
    active_width_mm=29.42,
    active_height_mm=14.70,
    active_center_x_mm=0.0,
    active_center_y_mm=1.67,
    mounting_hole_diameter_mm=2.5,
    mounting_hole_spacing_x_mm=30.48,
    mounting_hole_spacing_y_mm=27.94,
    mount_style="screws",
    pcb_thickness_mm=1.57,
    panel_width_mm=34.40,
    panel_height_mm=23.00,
    panel_thickness_mm=2.00,
    panel_center_x_mm=0.0,
    panel_center_y_mm=0.12,
    geometry_evidence_status="measured",
    geometry_source=(
        "Adafruit 938 CAD model (PCB, holes, panel, connectors); active area "
        "from the UG-2864KSWLG01 datasheet drawing, 1.55 mm off the panel "
        "centre away from its flex cable, whose wraparound pads Adafruit's "
        "board layout (Adafruit-1.3inch-128x64-Mono-OLED-PCB) puts at the end "
        "opposite the header"
    ),
)

ADAFRUIT_OLED_128X128_1_5IN = DisplaySpec(
    identifier="ADAFRUIT_OLED_128X128_1_5IN",
    module_width_mm=35.56,
    module_height_mm=46.99,
    # 1.41 panel (datasheet), 1.57 PCB, 2.96 STEMMA QT connectors behind.
    module_depth_mm=5.94,
    active_width_mm=26.86,
    active_height_mm=26.86,
    active_center_x_mm=0.13,
    active_center_y_mm=3.18,
    mounting_hole_diameter_mm=2.5,
    mounting_hole_spacing_x_mm=30.48,
    mounting_hole_spacing_y_mm=41.91,
    mount_style="screws",
    pcb_thickness_mm=1.57,
    panel_width_mm=33.80,
    panel_height_mm=36.50,
    panel_thickness_mm=1.41,
    panel_center_x_mm=0.13,
    panel_center_y_mm=0.26,
    geometry_evidence_status="measured",
    geometry_source=(
        "Adafruit 4741 CAD model (PCB, holes, panel, connectors); active area "
        "from the RiTdisplay RGS15128128WR000 drawing, 2.92 mm off the panel "
        "centre away from its flex cable, whose pads Adafruit's board layout "
        "(Adafruit-Grayscale-1.5-inch-128x128-OLED-PCB) puts at the end "
        "opposite the header"
    ),
)

ADAFRUIT_EINK_200X200_1_54IN = DisplaySpec(
    identifier="ADAFRUIT_EINK_200X200_1_54IN",
    module_width_mm=43.18,
    module_height_mm=43.18,
    # 1.05 panel (datasheet), 1.57 PCB, 1.88 parts behind.
    module_depth_mm=4.50,
    active_width_mm=27.60,
    active_height_mm=27.60,
    active_center_x_mm=0.0,
    active_center_y_mm=-0.83,
    mounting_hole_diameter_mm=2.5,
    mounting_hole_spacing_x_mm=38.10,
    mounting_hole_spacing_y_mm=38.10,
    mount_style="screws",
    pcb_thickness_mm=1.57,
    panel_width_mm=31.80,
    panel_height_mm=37.30,
    panel_thickness_mm=1.05,
    panel_center_x_mm=0.0,
    panel_center_y_mm=1.92,
    geometry_evidence_status="measured",
    geometry_source=(
        "Adafruit 4196 CAD model (PCB, holes, panel); active area from the "
        "1.54 inch e-Paper (SSD1681) drawing, 2.76 mm off the panel centre "
        "away from its flex cable, which the model's panel layers confirm"
    ),
)
