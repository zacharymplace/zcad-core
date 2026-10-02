"""What a bay holds: a module, as the group enclosure's builder reads it.

A bay used to be a Raspberry Pi 5 or an open shelf, and every step of the build
(the slot's width, the standoffs, the fit envelope, the checks) read a Pi's
figures directly. A :class:`BayModule` is those figures as data, so a bay can
hold a Pi 5 or any board a board file describes and the builder reads them all
the same way:

- its **footprint** across the row and from front to back, as built;
- its **supports**: where the standoffs go, and the screw they take;
- its **parts**: the envelope the enclosure must clear and each part's box;
- how low its standoffs must be and how tall its parts stand; and
- the wall **openings** a board bay needs, in the group's own frame.

The Pi 5's openings, its service gap, and the fan slots over it stay in their own
code (:mod:`zcad_core.features.enclosure_group_openings`), since they are a Pi's;
this module wraps the Pi's envelope and parts and its holes unchanged, so a Pi bay
builds what it built before.

A board bay turns the board in 90 degree steps so that its longer side runs front
to back, as a Pi's does, unless the bay says otherwise. Its connectors then fall on
the back wall, the front wall, or the sides facing the neighbouring bays. The first
two take an opening through the wall. One facing a side takes a **service space** on
that side, as a Pi's USB-C and micro-HDMI do: room for the plug, with the cable
leaving through an opening in the front wall at the end of the space.

A board with no mounting holes stands in a **cradle** instead of on standoffs: a
ledge under its edges, snap clips at its sides, and a stop opposite its cable
connector (:mod:`zcad_core.features.board_cradle`). The clips stand a millimetre or
two outside the board's side edges, so a cradle bay takes no divider.

The board's frame is :mod:`zcad_core.features.board_solids`'s: centred, +X right
and +Y up the page seen from above, top face at ``z == 0``. A turn is
counterclockwise seen from above, so a quarter turn takes the board's +X edge to
the back wall.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import cadquery as cq

from zcad_core.features.board_solids import board_assembly
from zcad_core.features.enclosure_group_envelope import (
    PART_TOLERANCE_MM,
    make_box,
    pi_envelope,
    pi_parts,
)
from zcad_core.hardware import RaspberryPi5Spec, get_fastener, list_fasteners
from zcad_core.hardware.electronics.board_components import BoardComponentSpec
from zcad_core.hardware.electronics.board_file import BoardFileSpec
from zcad_core.hardware.electronics.board_outline import Point

ROTATIONS = (0, 90, 180, 270)
ALIGNMENTS = ("front", "center", "back")
# The card or part under a board clears the floor by this much.
MINIMUM_FLOOR_GAP_MM = 0.4
# A bay's headroom stands this far above its tallest part.
HEADROOM_MARGIN_MM = 0.5
STANDOFF_DIAMETER_MM = 6.0
_PI_STANDOFF_FASTENER = "M2.5"
_EDGE_AFTER_TURN = {
    90: {
        "positive_x": "positive_y",
        "positive_y": "negative_x",
        "negative_x": "negative_y",
        "negative_y": "positive_x",
    },
    180: {
        "positive_x": "negative_x",
        "positive_y": "negative_y",
        "negative_x": "positive_x",
        "negative_y": "positive_y",
    },
    270: {
        "positive_x": "negative_y",
        "positive_y": "positive_x",
        "negative_x": "positive_y",
        "negative_y": "negative_x",
    },
}


@dataclass(frozen=True)
class PortOpening:
    """An opening a board bay needs through the front or back wall.

    ``along_mm`` is from the board's centre along the wall, ``bottom_mm`` is the
    opening's lower edge above the board's top face, and the size is the plug's
    or the part's, before the enclosure adds its margin."""

    wall: str
    along_mm: float
    bottom_mm: float
    width_mm: float
    height_mm: float
    label: str


@dataclass(frozen=True)
class BayModule:
    """A bay's board, as the builder reads it."""

    kind: str
    width_mm: float
    depth_mm: float
    thickness_mm: float
    holes: tuple[Point, ...]
    standoff_screw: str
    # The standoff's lowest height, so what is under the board clears the floor,
    # and the one a bay takes unless it says otherwise; ``None``: the design's.
    minimum_standoff_mm: float
    default_standoff_mm: float | None
    # How tall the board's parts stand above its top face.
    tallest_mm: float
    # The board's envelope and parts, placed: ``(centre x, centre y, board bottom,
    # board top)`` and ``(centre x, centre y, board top)``.
    envelope: Callable[[float, float, float, float], cq.Shape]
    parts: Callable[[float, float, float], dict[str, cq.Shape]]
    openings: tuple[PortOpening, ...] = ()
    is_pi: bool = False
    # Connectors on the side faces, which take a service space rather than a wall
    # opening, and the board's lid vents, each as a centre in the turned frame.
    side_ports: tuple[PortOpening, ...] = ()
    vents: tuple[Point, ...] = ()
    # ``standoffs``, or ``cradle`` for a board with no mounting holes: then the
    # outline (turned, or ``None`` for a rectangle) and the wall its cable
    # connector faces say how the cradle is built.
    support: str = "standoffs"
    outline: tuple[Point, ...] | None = None
    connector_wall: str = "negative_y"

    @property
    def faces_right(self) -> bool:
        """Whether a connector faces the next bay."""
        return any(port.wall == "positive_x" for port in self.side_ports)

    @property
    def faces_left(self) -> bool:
        """Whether a connector faces the previous bay."""
        return any(port.wall == "negative_x" for port in self.side_ports)

    @property
    def standoff_diameter_mm(self) -> float:
        if not self.standoff_screw:
            return STANDOFF_DIAMETER_MM

        return max(
            STANDOFF_DIAMETER_MM, get_fastener(self.standoff_screw).tap_hole_mm + 3.0
        )


def pi_module(pi: RaspberryPi5Spec) -> BayModule:
    """A Raspberry Pi 5 as a module: its holes, envelope and parts as the group
    has always read them."""

    def envelope(
        center_x: float, center_y: float, bottom: float, top: float
    ) -> cq.Shape:
        return pi_envelope(pi, center_x, center_y, bottom, top)

    def parts(center_x: float, center_y: float, top: float) -> dict[str, cq.Shape]:
        return pi_parts(pi, center_x, center_y, top)

    return BayModule(
        kind="pi5",
        width_mm=pi.board_width_mm,
        depth_mm=pi.board_length_mm,
        thickness_mm=pi.board_thickness_mm,
        holes=pi.mounting_hole_positions_mm,
        standoff_screw=_PI_STANDOFF_FASTENER,
        minimum_standoff_mm=pi.sd_card_depth_below_board_mm + MINIMUM_FLOOR_GAP_MM,
        default_standoff_mm=None,
        tallest_mm=0.0,
        envelope=envelope,
        parts=parts,
        is_pi=True,
    )


def turn_point(point: Point, rotate: int) -> Point:
    """A point turned counterclockwise about the board's centre."""

    x, y = point

    return {0: (x, y), 90: (-y, x), 180: (-x, -y), 270: (y, -x)}[rotate]


def default_rotation(board: BoardFileSpec) -> int:
    """Longer side front to back, as a Pi sits."""

    return 0 if board.board_length_mm >= board.board_width_mm else 90


def _standoff_screw(board: BoardFileSpec, screw: str | None) -> str:
    """The screw a board's standoffs take: the one named, or the largest in the
    catalog that its mounting holes pass."""

    diameter = board.mounting_hole_diameter_mm

    if diameter is None:
        raise ValueError("the board has no mounting holes to stand it on")

    if screw is not None:
        if screw not in list_fasteners():
            raise ValueError(f"screw must be one of {list_fasteners()}, not {screw!r}")

        if get_fastener(screw).nominal_diameter_mm > diameter:
            raise ValueError(
                f"{screw} is wider than the board's {diameter:g} mm mounting holes"
            )

        return screw

    fitting = [
        name
        for name in list_fasteners()
        if get_fastener(name).nominal_diameter_mm <= diameter - 0.1
    ]

    if not fitting:
        raise ValueError(
            f"no catalog screw fits the board's {diameter:g} mm mounting holes"
        )

    return max(fitting, key=lambda name: get_fastener(name).nominal_diameter_mm)


def _port_openings(
    board: BoardFileSpec,
) -> list[tuple[str, float, float, float, float, str]]:
    """Every opening the board asks for as ``(edge, along, bottom, width, height,
    label)`` in the board's frame: its cable connector, its wall openings, and
    each part marked as reached through an edge."""

    found: list[tuple[str, float, float, float, float, str]] = []
    usb = board.usb_connector
    found.append(
        (
            usb.board_edge,
            usb.center_offset_mm,
            usb.bottom_offset_from_board_top_mm,
            usb.width_mm,
            usb.height_mm,
            usb.identifier,
        )
    )

    for opening in board.wall_openings:
        found.append(
            (
                opening.edge,
                opening.center_offset_mm,
                opening.bottom_offset_from_board_top_mm,
                opening.width_mm,
                opening.height_mm,
                opening.identifier,
            )
        )

    for part in board.components:
        if part.access_edge is None:
            continue

        along_y = part.access_edge in ("positive_y", "negative_y")
        found.append(
            (
                part.access_edge,
                part.center_x_mm if along_y else part.center_y_mm,
                part.bottom_offset_from_board_top_mm,
                part.width_mm if along_y else part.depth_mm,
                part.height_mm,
                part.identifier,
            )
        )

    return found


def _turned_openings(
    board: BoardFileSpec, rotate: int
) -> tuple[tuple[PortOpening, ...], tuple[PortOpening, ...]]:
    """The openings after the board is turned: those on the back and front walls,
    and those on the sides, where ``along_mm`` is from the board's centre along
    the side."""

    half_x, half_y = board.board_width_mm / 2, board.board_length_mm / 2
    walls: list[PortOpening] = []
    sides: list[PortOpening] = []

    for edge, along, bottom, width, height, label in _port_openings(board):
        point = {
            "positive_x": (half_x, along),
            "negative_x": (-half_x, along),
            "positive_y": (along, half_y),
            "negative_y": (along, -half_y),
        }[edge]
        wall = edge if rotate == 0 else _EDGE_AFTER_TURN[rotate][edge]
        x, y = turn_point(point, rotate)

        if wall in ("positive_x", "negative_x"):
            sides.append(PortOpening(wall, y, bottom, width, height, label))
        else:
            walls.append(PortOpening(wall, x, bottom, width, height, label))

    return tuple(walls), tuple(sides)


def _turned_extent(part: BoardComponentSpec, rotate: int) -> tuple[Point, float, float]:
    """A part's centre and size once the board is turned."""

    centre = turn_point((part.center_x_mm, part.center_y_mm), rotate)
    swap = rotate in (90, 270)

    return (
        centre,
        part.depth_mm if swap else part.width_mm,
        part.width_mm if swap else part.depth_mm,
    )


def _holes(board: BoardFileSpec) -> tuple[Point, ...]:
    """The board's mounting holes about its centre, or none."""

    if board.mounting_hole_diameter_mm is None:
        return ()

    if board.mounting_hole_positions_mm is not None:
        return tuple(board.mounting_hole_positions_mm)

    sx, sy = board.mounting_hole_spacing_x_mm, board.mounting_hole_spacing_y_mm

    if sx is None or sy is None:
        return ()

    return ((-sx / 2, -sy / 2), (sx / 2, -sy / 2), (-sx / 2, sy / 2), (sx / 2, sy / 2))


def _placers(
    board: BoardFileSpec, turn: int
) -> tuple[
    Callable[[float, float, float, float], cq.Shape],
    Callable[[float, float, float], dict[str, cq.Shape]],
]:
    """The board's envelope and parts, turned and placed in the row."""

    def envelope(
        center_x: float, center_y: float, bottom: float, top: float
    ) -> cq.Shape:
        shape = board_assembly(board).rotate((0, 0, 0), (0, 0, 1), float(turn))

        return shape.moved(cq.Location(cq.Vector(center_x, center_y, top)))

    def parts(center_x: float, center_y: float, top: float) -> dict[str, cq.Shape]:
        def span(start: float, size: float) -> tuple[float, float]:
            inset = min(PART_TOLERANCE_MM, size / 4)

            return start + inset, start + size - inset

        placed: dict[str, cq.Shape] = {}

        for part in board.components:
            (x, y), width, depth = _turned_extent(part, turn)
            placed[part.identifier] = make_box(
                span(center_x + x - width / 2, width),
                span(center_y + y - depth / 2, depth),
                span(top + part.bottom_offset_from_board_top_mm, part.height_mm),
            )

        return placed

    return envelope, parts


def board_module(
    board: BoardFileSpec, *, rotate: int | None = None, screw: str | None = None
) -> BayModule:
    """A board from a board file as a module, turned to sit in the row. Refuses a
    board that cannot stand in one."""

    turn = default_rotation(board) if rotate is None else rotate

    if turn not in ROTATIONS:
        raise ValueError(f"rotate must be one of {ROTATIONS}, not {turn!r}")

    holes = _holes(board)
    cradle = not holes

    if cradle and screw is not None:
        raise ValueError(
            f"{board.identifier} has no mounting holes and stands in a cradle, "
            "which takes no screw"
        )

    swap = turn in (90, 270)
    above = [p for p in board.components if p.bottom_offset_from_board_top_mm >= -1e-9]
    below = [p for p in board.components if p.bottom_offset_from_board_top_mm < 0]
    depth_below = max(
        (-p.bottom_offset_from_board_top_mm - board.board_thickness_mm for p in below),
        default=0.0,
    )
    envelope, parts = _placers(board, turn)
    walls, sides = _turned_openings(board, turn)
    connector = board.usb_connector.board_edge

    return BayModule(
        kind="board",
        width_mm=board.board_length_mm if swap else board.board_width_mm,
        depth_mm=board.board_width_mm if swap else board.board_length_mm,
        thickness_mm=board.board_thickness_mm,
        holes=tuple(turn_point(hole, turn) for hole in holes),
        standoff_screw="" if cradle else _standoff_screw(board, screw),
        minimum_standoff_mm=(
            depth_below + MINIMUM_FLOOR_GAP_MM if below else MINIMUM_FLOOR_GAP_MM
        ),
        default_standoff_mm=board.recommended_standoff_height_mm,
        tallest_mm=max(
            (p.bottom_offset_from_board_top_mm + p.height_mm for p in above),
            default=0.0,
        ),
        envelope=envelope,
        parts=parts,
        openings=walls,
        side_ports=sides,
        vents=tuple(
            turn_point((p.center_x_mm, p.center_y_mm), turn)
            for p in board.components
            if p.lid_vent
        ),
        support="cradle" if cradle else "standoffs",
        outline=(
            None
            if board.outline_points_mm is None
            else tuple(turn_point(point, turn) for point in board.outline_points_mm)
        ),
        connector_wall=connector if turn == 0 else _EDGE_AFTER_TURN[turn][connector],
    )
