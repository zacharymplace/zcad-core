"""The types of a Pi 5 group enclosure: its design, its bays, and its result.

Everything here is data. The layout that places the bays is in
:mod:`zcad_core.features.enclosure_group_layout`, and the builder that
returns a :class:`GroupEnclosure` is in :mod:`zcad_core.features.enclosure_group`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cadquery as cq

from zcad_core.features.connector_cutouts import MINIMUM_OPENING_WEB_MM
from zcad_core.features.enclosure_group_dividers import Divider
from zcad_core.features.mounts import MOUNTS, MountPads, MountPlate
from zcad_core.hardware import FastenerSpec

BayKind = Literal["pi5", "reserved", "open"]
BAY_KINDS: tuple[BayKind, ...] = ("pi5", "reserved", "open")
OpeningWall = Literal["front", "back"]
OPENING_WALLS: tuple[OpeningWall, ...] = ("front", "back")
# Wall left between an opening and the shelf's ends, and under the lid.
OPENING_RIM_MM = 1.0
# Bosses and standoffs start this far down inside the floor, so they fuse to
# it.
FLOOR_EMBED_MM = 0.5


@dataclass(frozen=True)
class GroupDesign:
    """Sizes for the row of bays, in millimetres.

    ``standoff_height_mm`` and ``headroom_mm`` are the defaults for every
    bay; a :class:`Bay` overrides either for itself. ``headroom_mm`` is the
    room a bay's parts need above a Pi's PCB top: the default clears the
    tallest standard part (the 15.6 mm USB stack) and an Active Cooler with
    2 mm to spare; raise it for a HAT. For an ``open`` bay it is the height
    of the shelf's usable space. ``service_gap_mm`` is the space right of each
    Pi for its USB-C and micro-HDMI plugs, and ``end_margin_mm`` the space
    left of the first bay, beside its header. ``open_bay_width_mm`` is the
    width of an ``open`` bay's shelf.
    """

    wall_mm: float = 2.0
    floor_mm: float = 2.0
    lid_mm: float = 3.0
    fastener: str = "M3"
    boss_radial_wall_mm: float = 1.8
    standoff_height_mm: float = 4.0
    headroom_mm: float = 18.0
    service_gap_mm: float = 25.0
    end_margin_mm: float = 9.0
    front_clearance_mm: float = 4.0
    back_clearance_mm: float = 3.0
    slot_pad_mm: float = 0.25
    open_bay_width_mm: float = 40.0
    plug_margin_mm: float = 1.5
    vents: bool = True
    join_bolts: bool = True
    divider_mm: float = 2.0
    divider_clearance_mm: float = 0.75
    divider_notch_width_mm: float = 20.0
    divider_notch_height_mm: float = 10.0
    # A Pi's back-wall openings closer than this merge into one, so no thin
    # web of wall is left between its Ethernet and USB plugs; zero keeps
    # them apart.
    minimum_opening_web_mm: float = MINIMUM_OPENING_WEB_MM
    # A mount plate that bolts to four pads under the floor; none by default.
    mount: str | None = None
    mount_plate_mm: float = 4.0

    def validate(self) -> None:
        if self.mount is not None and self.mount not in MOUNTS:
            raise ValueError(f"mount must be one of {MOUNTS}")

        for name in (
            "wall_mm",
            "floor_mm",
            "lid_mm",
            "boss_radial_wall_mm",
            "standoff_height_mm",
            "headroom_mm",
            "service_gap_mm",
            "end_margin_mm",
            "open_bay_width_mm",
            "divider_mm",
            "divider_notch_width_mm",
            "divider_notch_height_mm",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.floor_mm <= FLOOR_EMBED_MM:
            raise ValueError(f"floor_mm must exceed {FLOOR_EMBED_MM} mm")

        for name in (
            "front_clearance_mm",
            "back_clearance_mm",
            "slot_pad_mm",
            "plug_margin_mm",
            "divider_clearance_mm",
            "minimum_opening_web_mm",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class BayOpening:
    """A rectangular opening through an ``open`` bay's front or back wall.

    ``offset_mm`` runs along X from the middle of the bay's shelf, and
    ``bottom_mm`` is the opening's lower edge above the floor's top face. It
    must sit inside the shelf, leave a millimetre of wall to each side, and
    stop a millimetre short of the lid.
    """

    wall: OpeningWall
    width_mm: float
    height_mm: float
    offset_mm: float = 0.0
    bottom_mm: float = 0.0


@dataclass(frozen=True)
class Bay:
    """One bay, with heights that differ from the design's defaults.

    ``standoff_height_mm`` lifts a Pi off the floor, for a board mounted
    under it; ``headroom_mm`` is the room its parts need above the PCB, for a
    HAT. The lid is flat, so the box is as tall as its tallest bay needs and
    the other bays get spare room above their boards. ``openings`` cut
    through an ``open`` bay's walls, for the cables of whatever sits on its
    shelf; a Pi bay's openings are fixed by its ports. ``divider`` puts a
    wall on the boundary to this bay's left, at the end of the previous
    bay's service gap and just clear of this bay's header edge, so the first
    bay takes none.
    """

    kind: BayKind = "pi5"
    standoff_height_mm: float | None = None
    headroom_mm: float | None = None
    openings: tuple[BayOpening, ...] = ()
    divider: Divider | None = None


BayLike = BayKind | Bay


@dataclass(frozen=True)
class BayLayout:
    """Where one bay sits along X, its heights, and its centre when it holds
    a Pi. Heights are ``z`` in the enclosure frame; an ``open`` bay has no
    board, so its board faces sit at the floor."""

    index: int
    kind: BayKind
    slot_start_mm: float
    slot_end_mm: float
    # The service gap to the slot's right, or an open shelf's strip.
    gap_start_mm: float
    gap_end_mm: float
    standoff_height_mm: float
    headroom_mm: float
    board_bottom_z_mm: float
    board_top_z_mm: float
    openings: tuple[BayOpening, ...] = ()
    divider: Divider | None = None
    # Where the divider's left face is, when there is one.
    divider_start_mm: float = 0.0

    @property
    def needed_top_z_mm(self) -> float:
        """The lowest lid underside this bay's parts fit under."""
        return self.board_top_z_mm + self.headroom_mm

    @property
    def center_x_mm(self) -> float:
        return (self.slot_start_mm + self.slot_end_mm) / 2

    @property
    def holds_pi(self) -> bool:
        return self.kind != "open"


@dataclass(frozen=True)
class GroupEnclosure:
    """The printable base and lid, and the space they were built around."""

    base: cq.Workplane
    lid: cq.Workplane
    design: GroupDesign
    fastener: FastenerSpec
    bays: tuple[BayLayout, ...]
    inner_size_mm: tuple[float, float, float]
    outer_size_mm: tuple[float, float, float]
    pi_center_y_mm: float
    lid_boss_positions: tuple[tuple[float, float], ...]
    join_positions: tuple[tuple[float, float], ...]
    # One envelope per Pi bay, keyed "bay-<n>", used for the fit checks and
    # for showing the parts in a review model.
    hardware: dict[str, cq.Shape]
    checks: dict[str, bool]
    recommended_lid_screw_mm: int
    recommended_join_screw_mm: int | None
    # Each of a Pi's extracted parts that runs into the base or lid, as
    # "bay-<n> <part> meets the <base|lid>"; empty when the parts all clear.
    part_collisions: tuple[str, ...] = ()
    # The pads under the floor and the plate that bolts to them, when the
    # design asks for a mount.
    mount_pads: MountPads | None = None
    mount: MountPlate | None = None

    @property
    def cavity_top_z_mm(self) -> float:
        return self.design.floor_mm + self.inner_size_mm[2]

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    def room_above_board_mm(self, bay: BayLayout) -> float:
        """The space between a bay's board faces and the lid: at least the
        bay's headroom, and more where a taller bay set the box's height."""
        return self.cavity_top_z_mm - bay.board_top_z_mm
