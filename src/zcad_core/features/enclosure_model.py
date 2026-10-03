"""The types of the enclosure builder: its design, and what it returns.

Everything here is data; the builder is in :mod:`zcad_core.features.enclosure`.
"""

from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq

from zcad_core.assemblies import EnclosureSpecification
from zcad_core.features.connector_cutouts import (
    MINIMUM_OPENING_WEB_MM,
    ConnectorCutoutParameters,
)
from zcad_core.features.enclosure_lid import LIP_DEPTH_MM, SNAP_SKIRT_DEPTH_MM
from zcad_core.features.enclosure_thermal import (
    CONVECTION_W_M2K,
    DEFAULT_AMBIENT_C,
    DEFAULT_SERVICE_LIMIT_C,
    ThermalEstimate,
)
from zcad_core.features.fan_bay import FAN_DIRECTIONS, FAN_POSITIONS, FanReport
from zcad_core.features.lid_hinge import HingeReport
from zcad_core.features.lid_slide import SlideReport, slide_clearance_error
from zcad_core.features.mount_stack import StackTop, check_top_holding, latch_sides
from zcad_core.features.mounts import MOUNTS, MountPads, MountPlate
from zcad_core.features.vent_patterns import PATTERNS, VentReport
from zcad_core.hardware import FastenerSpec, list_fans

# Bosses and standoffs start this far down inside the floor, so they fuse to
# it and their pilot holes do not break through the underside.
_FLOOR_EMBED_MM = 0.5


# Printers print holes small far more often than large, and the cradle's
# 0.3 mm fit leaves little room to shrink.
HOLE_COMPENSATION_RANGE_MM = (-0.2, 1.0)


LID_ATTACHMENTS = ("screws", "snap", "hinge", "slide")


@dataclass(frozen=True)
class EnclosureDesign:
    """Wall, floor, and lid thicknesses, the lid fastener, the gaps between
    the hardware and the cavity, and the cable plug the opening must pass.

    ``side_clearance_mm`` sets how far the walls, and so the corner bosses,
    stand off the hardware; left unset, it starts at 2 mm and widens X and Y
    separately, in 0.5 mm steps, to the smallest footprint at which the
    bosses clear the hardware and the cable opening; ``bottom_clearance_mm`` is the standoff height
    under the lowest part; ``top_clearance_mm`` is the gap under the lid.
    The cable opening is at least ``cable_plug_width_mm`` by
    ``cable_plug_height_mm``, so a cable's moulded plug body reaches the
    connector through the wall and the gap inside it; the defaults fit
    common USB-C and micro-USB cables. Set both to zero for an opening sized
    to the connector alone. ``display_retainer`` holds the display under
    its window: screw posts over a display's mounting holes, for
    ``display_fastener`` self-tapping screws, or, for a display without
    holes, corner posts and snap clips.
    """

    wall_mm: float = 2.0
    floor_mm: float = 2.0
    lid_mm: float = 2.0
    fastener: str = "M3"
    boss_radial_wall_mm: float = 1.8
    side_clearance_mm: float | None = None
    bottom_clearance_mm: float = 2.0
    top_clearance_mm: float = 2.0
    cable_plug_width_mm: float = 12.5
    cable_plug_height_mm: float = 7.5
    display_retainer: bool = True
    display_fastener: str = "M2"
    # How much wider than intended every hole and opening is modelled, to
    # make up for a printer that prints them undersized. A trial measures
    # the intended sizes; ``enclosure revise`` sets this from the shortfall.
    hole_compensation_mm: float = 0.0
    # "screws" into heat-set inserts, a "snap" lid with no fasteners, a
    # "hinge" lid on a pin that closes with a catch, or a "slide" lid that
    # runs in grooves and is held by a detent.
    lid_attachment: str = "screws"
    # The gap, per side, around a sliding lid; the printer profile recommends
    # one, and the export checks this against it.
    slide_clearance_mm: float = 0.2
    # The fastener used as the hinge pin (with a nut), for a "hinge" lid.
    hinge_pin: str = "M3"
    # For the temperature estimate: power the catalog lacks, in watts (a hat,
    # an SSD), the room's temperature, and the material's limit for the air
    # inside. ``allow_hot`` builds a box the estimate says is too hot.
    declared_power_w: float = 0.0
    # The coefficient the estimate uses, W/m2K, and where it came from: the
    # default, or a profile pooled from measured trials.
    convection_w_m2k: float = CONVECTION_W_M2K
    convection_source: str = "the default, an assumption"
    ambient_c: float = DEFAULT_AMBIENT_C
    service_limit_c: float = DEFAULT_SERVICE_LIMIT_C
    allow_hot: bool = False
    # Sink flat-head lid screws flush (screwed lids only).
    countersunk_screws: bool = False
    # A skirt under a screwed lid that keys it onto the base.
    locating_lip: bool = False
    # Vertical vent slots in each long wall that carries no opening.
    vent_slots: int = 0
    # A vent pattern sized to a free area, in mm2, for each of the inlets low
    # in the long walls and the outlets in the lid; the outlets are never
    # smaller. ``vent_slots`` is a separate, fixed set of slots.
    vent_pattern: str = "slots"
    vent_area_mm2: float = 0.0
    # A catalogued fan, inside the lid or against a long wall, screwed from
    # outside through a guarded round opening. Which way it blows is recorded;
    # its offset from the middle of the lid (X, Y) or the wall (along, up).
    fan: str | None = None
    fan_position: str = "lid"
    fan_direction: str = "out"
    fan_offset_x_mm: float = 0.0
    fan_offset_y_mm: float = 0.0
    # Openings in one wall closer than this merge into one, so no thin web
    # of wall is left between them; zero keeps every opening apart.
    minimum_opening_web_mm: float = MINIMUM_OPENING_WEB_MM
    # A mount plate that bolts to four pads under the floor; none by default.
    mount: str | None = None
    mount_plate_mm: float = 4.0
    # The stack profile file a ``stack`` mount or a stack top is built to.
    stack_profile: str | None = None
    # A baseplate over a screwed lid, held by the lid's own screws, so things stack on the box.
    stack_top: bool = False
    # What a stack top holds by: the lip alone, or magnets in the pockets' floors; and the sides
    # whose pocket walls take a keeper for the hooks of a latched item above, as a
    # comma-separated string such as "front,back" so a record round-trips.
    stack_top_holding: str = "lip"
    stack_top_magnet: str | None = None
    stack_top_latch: str = ""
    stack_top_engagement_mm: float | None = None

    def validate(self) -> None:
        if self.mount is not None and self.mount not in MOUNTS:
            raise ValueError(f"mount must be one of {MOUNTS}")

        if (self.mount == "stack" or self.stack_top) != (
            self.stack_profile is not None
        ):
            raise ValueError(
                "mount 'stack', a stack top and stack_profile go together: a stack mount "
                "or a stack top needs the profile it is built to, and a profile needs one"
            )

        check_top_holding(
            self.stack_top_holding,
            self.stack_top_magnet,
            latch_sides(self.stack_top_latch),
            self.stack_top_engagement_mm,
            self.stack_top,
        )

        for name in ("wall_mm", "floor_mm", "lid_mm", "boss_radial_wall_mm"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.floor_mm <= _FLOOR_EMBED_MM:
            raise ValueError(f"floor_mm must exceed {_FLOOR_EMBED_MM} mm")

        low, high = HOLE_COMPENSATION_RANGE_MM

        if not low <= self.hole_compensation_mm <= high:
            raise ValueError(f"hole_compensation_mm must be from {low} to {high} mm")

        if self.side_clearance_mm is not None and self.side_clearance_mm < 0:
            raise ValueError("side_clearance_mm must not be negative")

        self._validate_lid()
        self._validate_fan()
        self._validate_thermal()

        for name in (
            "bottom_clearance_mm",
            "top_clearance_mm",
            "cable_plug_width_mm",
            "cable_plug_height_mm",
            "minimum_opening_web_mm",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")

    def _validate_fan(self) -> None:
        if self.fan is None:
            return

        if self.fan not in list_fans():
            raise ValueError(f"fan must be one of {list_fans()}")

        if self.fan_position not in FAN_POSITIONS:
            raise ValueError(f"fan_position must be one of {FAN_POSITIONS}")

        if self.fan_direction not in FAN_DIRECTIONS:
            raise ValueError(f"fan_direction must be one of {FAN_DIRECTIONS}")

    def _validate_thermal(self) -> None:
        if self.declared_power_w < 0:
            raise ValueError("declared_power_w must not be negative")

        if self.service_limit_c <= self.ambient_c:
            raise ValueError("service_limit_c must be above ambient_c")

        if self.convection_w_m2k <= 0:
            raise ValueError("convection_w_m2k must be greater than zero")

    def _validate_lid(self) -> None:
        if self.lid_attachment not in LID_ATTACHMENTS:
            raise ValueError(f"lid_attachment must be one of {LID_ATTACHMENTS}")

        snap = self.lid_attachment == "snap"
        hinge = self.lid_attachment == "hinge"
        slide = self.lid_attachment == "slide"

        if (snap or hinge or slide) and self.countersunk_screws:
            raise ValueError(
                "A snap-fit, hinged, or sliding lid has no screws to countersink"
            )

        if slide and self.locating_lip:
            raise ValueError("A sliding lid has no lip: it would catch in its grooves")

        error = slide_clearance_error(self.slide_clearance_mm) if slide else None

        if error is not None:
            raise ValueError(error)

        if snap and self.locating_lip:
            raise ValueError("A snap-fit lid already locates on its skirt")

        if hinge and self.locating_lip:
            raise ValueError(
                "A hinged lid has no lip: it would catch as the lid swings"
            )

        if self.vent_slots < 0:
            raise ValueError("vent_slots must not be negative")

        if self.vent_pattern not in PATTERNS:
            raise ValueError(f"vent_pattern must be one of {PATTERNS}")

        if self.vent_area_mm2 < 0:
            raise ValueError("vent_area_mm2 must not be negative")

        if self.vent_area_mm2 and self.vent_slots:
            raise ValueError("Set vent_slots or vent_area_mm2, not both")

        if self.vent_pattern != "slots" and not self.vent_area_mm2:
            raise ValueError("A vent pattern needs a vent_area_mm2 to size it to")

    @property
    def skirt_depth_mm(self) -> float | None:
        """How far the lid's skirt reaches into the base, if it has one."""
        if self.lid_attachment == "snap":
            return SNAP_SKIRT_DEPTH_MM

        return LIP_DEPTH_MM if self.locating_lip else None


@dataclass(frozen=True)
class Enclosure:
    """The two printable parts and the geometry they were built from."""

    base: cq.Workplane
    lid: cq.Workplane
    specification: EnclosureSpecification
    design: EnclosureDesign
    side_clearance_mm: tuple[float, float]
    fastener: FastenerSpec
    fastener_positions: tuple[tuple[float, float], ...]
    board_support: str
    display_support: str | None = None
    # Screws up through the display's PCB into its posts: how many, and the
    # longest that fits (PCB thickness plus post length).
    display_screw_count: int = 0
    display_screw_reach_mm: float | None = None
    # The cable opening first, then one per board part reached through a wall.
    openings: tuple[ConnectorCutoutParameters, ...] = ()
    # The pads under the floor and the plate that bolts to them, when the
    # design asks for a mount.
    mount_pads: MountPads | None = None
    mount: MountPlate | None = None
    # The baseplate over the lid, when the design asks for a stack top.
    stack_top: StackTop | None = None
    # The hinge and its catch, for a hinged lid.
    hinge: HingeReport | None = None
    # The grooves and detent, for a sliding lid.
    slide: SlideReport | None = None
    # The temperature estimate for the closed box.
    thermal: ThermalEstimate | None = None
    # The vent pattern, when the design asks for one.
    vents: VentReport | None = None
    # The fan bay, when the design asks for one, and the fan's frame, which is
    # not printed but is shown in the review model.
    fan: FanReport | None = None
    fan_body: cq.Shape | None = None
