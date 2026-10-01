"""Where a PCB test fixture's parts go, and whether its pins can land.

This is the arithmetic of a fixture, with no CAD in it: the heights of the plate
and the nest from the pin and the board, where the plate is located, which pins
fall on a part, where the board can be propped, and the **misalignment budget**,
the sum of every clearance that can move a pin's tip off its pad.

Frame: the board's own, centred on its bounding box, +X right and +Y up the page
seen from above, with the board's **top face at z == 0**: the board occupies
``-thickness`` to ``0``, parts above it are at positive heights, and parts under
it at negative ones.

The pin sits in a bore through the plate with its tail flush with the plate's
top. Compressed by the working travel ``w`` its tip is at the pad, so the plate's
top stands at ``free_length - w`` above the board and its underside ``thickness``
below that. The plate rests on a rim the nest carries up to that underside, so it
never rests on the board.

The budget is a worst case: every clearance taken at its largest, in the worst
direction, from the printer profile's provisional tolerances. It says a fixture
cannot be trusted to land if the sum exceeds a pad's slack. It does not say the
fixture will land if the sum fits: trials decide that.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.hardware import PogoSpec
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_file import (
    ENVELOPE_IDENTIFIER,
    BoardFileSpec,
)
from zcad_core.hardware.electronics.board_outline import Point
from zcad_core.hardware.electronics.board_test_points import BoardTestPoint

# The plate's underside stands this far above the tallest part.
PART_CLEARANCE_MM = 0.5
# A pin's bore is this many barrel diameters long, if the plate has the room.
PLATE_FACTOR = 2.0
MINIMUM_PLATE_MM = 1.5
DEFAULT_WALL_MM = 2.4
# The nest's floor, and the ledge the board rests on round its edge.
FLOOR_MM = 2.0
LEDGE_MM = 1.2
# Room under the board's lowest part.
UNDER_CLEARANCE_MM = 1.0
# A dowel on an ear outside the nest, and the ear that carries it.
DOWEL_DIAMETER_MM = 3.0
EAR_RADIUS_MM = 4.0
EAR_OFFSET_MM = 2.0
# The thinnest post worth putting through a mounting hole.
MINIMUM_POST_MM = 1.6
# Props under the board's test points.
SUPPORT_POST_MM = 3.0
SUPPORT_MARGIN_MM = 0.5
# A pin's barrel stands this far clear of any part beside it.
PIN_PART_MARGIN_MM = 0.2


@dataclass(frozen=True)
class Anchor:
    """A post that locates the plate: a dowel on an ear, or a post through a
    mounting hole, and the socket the plate has for it."""

    x_mm: float
    y_mm: float
    post_diameter_mm: float
    socket_diameter_mm: float
    kind: str


@dataclass(frozen=True)
class Budget:
    """What can move a pin's tip off its pad, in millimetres, each at its worst."""

    board_play_mm: float
    plate_play_mm: float
    bore_play_mm: float
    tilt_mm: float

    @property
    def total_mm(self) -> float:
        return (
            self.board_play_mm + self.plate_play_mm + self.bore_play_mm + self.tilt_mm
        )

    def largest(self) -> tuple[str, float]:
        links = {
            "the board in its nest": self.board_play_mm,
            "the plate on its dowels": self.plate_play_mm,
            "the pin in its bore": self.bore_play_mm,
            "the pin tilting in its bore": self.tilt_mm,
        }
        name = max(links, key=lambda key: links[key])

        return name, links[name]

    def to_dict(self) -> dict[str, float]:
        return {
            "board_in_nest_mm": round(self.board_play_mm, 3),
            "plate_on_dowels_mm": round(self.plate_play_mm, 3),
            "pin_in_bore_mm": round(self.bore_play_mm, 3),
            "pin_tilt_in_bore_mm": round(self.tilt_mm, 3),
            "total_mm": round(self.total_mm, 3),
        }


@dataclass(frozen=True)
class FixturePlan:
    """The heights, the anchors, the props, and the budget of a fixture."""

    points: tuple[BoardTestPoint, ...]
    pin: PogoSpec
    working_travel_mm: float
    plate_top_mm: float
    plate_thickness_mm: float
    plate_underside_mm: float
    tallest_part_mm: float
    under_depth_mm: float
    bore_diameter_mm: float
    nest_wall_mm: float
    clearance_mm: float
    locating: str
    anchors: tuple[Anchor, ...]
    anchor_spacing_mm: float
    supports: tuple[Point, ...]
    unsupported: tuple[str, ...]
    budgets: dict[str, Budget]
    worst_point: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def worst(self) -> Budget | None:
        return self.budgets.get(self.worst_point) if self.worst_point else None

    def to_dict(self) -> dict[str, Any]:
        worst = self.worst

        return {
            "plate": {
                "top_mm": round(self.plate_top_mm, 3),
                "underside_mm": round(self.plate_underside_mm, 3),
                "thickness_mm": round(self.plate_thickness_mm, 3),
                "bore_diameter_mm": round(self.bore_diameter_mm, 3),
            },
            "tallest_part_mm": round(self.tallest_part_mm, 3),
            "under_board_depth_mm": round(self.under_depth_mm, 3),
            "locating": self.locating,
            "anchors": [
                {
                    "kind": a.kind,
                    "position_mm": [round(a.x_mm, 3), round(a.y_mm, 3)],
                    "post_diameter_mm": round(a.post_diameter_mm, 3),
                    "socket_diameter_mm": round(a.socket_diameter_mm, 3),
                }
                for a in self.anchors
            ],
            "anchor_spacing_mm": round(self.anchor_spacing_mm, 3),
            "supports": [[round(x, 3), round(y, 3)] for x, y in self.supports],
            "unsupported": list(self.unsupported),
            "misalignment": (
                None
                if worst is None
                else {
                    "worst_point": self.worst_point,
                    **worst.to_dict(),
                    "note": (
                        "A worst case from the printer profile's provisional "
                        "tolerances alone. If it fits, nothing is proved; if it "
                        "does not, the fixture cannot be trusted to land."
                    ),
                }
            ),
            "per_point_total_mm": {
                name: round(budget.total_mm, 3) for name, budget in self.budgets.items()
            },
        }


def bore_diameter(pin: PogoSpec, fits: Mapping[str, float]) -> float:
    """The bore a pin's barrel is pressed into: the barrel, the press-fit
    clearance each side, and what a printer takes off a hole."""

    return (
        pin.barrel_diameter_mm
        + 2 * fits["press_fit_clearance_per_side"]
        + fits["hole_oversize"]
    )


def _rectangle_distance(
    point: Point, centre: Point, width: float, depth: float
) -> float:
    """How far a point is from an axis-aligned rectangle, zero inside it."""

    dx = max(abs(point[0] - centre[0]) - width / 2, 0.0)
    dy = max(abs(point[1] - centre[1]) - depth / 2, 0.0)

    return math.hypot(dx, dy)


def _parts(board: BoardFileSpec) -> tuple[list[Any], list[Any]]:
    """The board's parts above its top face, and those under its underside."""

    above = [p for p in board.components if p.bottom_offset_from_board_top_mm >= -1e-9]
    below = [p for p in board.components if p.bottom_offset_from_board_top_mm < 0]

    return above, below


def mounting_holes(board: BoardFileSpec) -> list[Point]:
    if board.mounting_hole_diameter_mm is None:
        return []

    if board.mounting_hole_positions_mm is not None:
        return list(board.mounting_hole_positions_mm)

    sx, sy = board.mounting_hole_spacing_x_mm, board.mounting_hole_spacing_y_mm

    if sx is None or sy is None:
        return []

    return [(-sx / 2, -sy / 2), (sx / 2, -sy / 2), (-sx / 2, sy / 2), (sx / 2, sy / 2)]


def outline_points(board: BoardFileSpec) -> Sequence[Point]:
    if board.outline_points_mm is not None:
        return board.outline_points_mm

    half_w, half_l = board.board_width_mm / 2, board.board_length_mm / 2

    return ((-half_w, -half_l), (half_w, -half_l), (half_w, half_l), (-half_w, half_l))


def _ear_anchors(
    board: BoardFileSpec, fits: Mapping[str, float], wall: float
) -> tuple[Anchor, Anchor]:
    """Two dowels on ears outside the nest, at the ends of the board's longer
    side, so the plate's turning is held over the longest lever."""

    points = outline_points(board)
    clearance = fits["sliding_clearance_per_side"]
    reach = clearance + wall + EAR_OFFSET_MM
    along_x = board.board_width_mm >= board.board_length_mm
    ends = []

    for sign in (-1.0, 1.0):
        if along_x:
            chord = board_outline.chord(points, 0.0)
            extent = (
                (chord[1] if sign > 0 else -chord[0])
                if chord
                else board.board_width_mm / 2
            )
            ends.append((sign * (extent + reach), 0.0))
        else:
            # The outline's extent along Y at x == 0: a chord of the turned shape.
            turned = [(y, x) for x, y in points]
            chord = board_outline.chord(turned, 0.0)
            extent = (
                (chord[1] if sign > 0 else -chord[0])
                if chord
                else board.board_length_mm / 2
            )
            ends.append((0.0, sign * (extent + reach)))

    socket = DOWEL_DIAMETER_MM + 2 * clearance + fits["hole_oversize"]

    return (
        Anchor(ends[0][0], ends[0][1], DOWEL_DIAMETER_MM, socket, "dowel"),
        Anchor(ends[1][0], ends[1][1], DOWEL_DIAMETER_MM, socket, "dowel"),
    )


def _hole_anchors(
    board: BoardFileSpec,
    fits: Mapping[str, float],
    below: list[Any],
    errors: list[str],
) -> tuple[Anchor, ...]:
    """Two posts up through the board's mounting holes, the farthest apart."""

    holes = mounting_holes(board)

    if len(holes) < 2 or board.mounting_hole_diameter_mm is None:
        errors.append(
            "Locating by the mounting holes needs at least two of them, and the "
            f"board has {len(holes)}"
        )

        return ()

    clearance = fits["sliding_clearance_per_side"]
    post = board.mounting_hole_diameter_mm - 2 * clearance

    if post < MINIMUM_POST_MM:
        errors.append(
            f"The mounting holes are {board.mounting_hole_diameter_mm:g} mm, so a "
            f"post through one would be {post:.2f} mm and the least is "
            f"{MINIMUM_POST_MM:g} mm: locate by the outline"
        )

        return ()

    first, second = max(
        ((a, b) for i, a in enumerate(holes) for b in holes[i + 1 :]),
        key=lambda pair: math.dist(pair[0], pair[1]),
    )
    socket = post + 2 * clearance + fits["hole_oversize"]
    chosen = []

    for x, y in (first, second):
        for part in below:
            if (
                _rectangle_distance(
                    (x, y),
                    (part.center_x_mm, part.center_y_mm),
                    part.width_mm,
                    part.depth_mm,
                )
                < post / 2 + SUPPORT_MARGIN_MM
            ):
                errors.append(
                    f"The post through the hole at ({x:g}, {y:g}) would meet "
                    f"{part.identifier} under the board"
                )

        chosen.append(Anchor(x, y, post, socket, "post"))

    return (chosen[0], chosen[1])


def _plate_play(
    point: Point, anchors: Sequence[Anchor], clearance: float
) -> tuple[float, float]:
    """The most the plate can sit off at a point, given two anchors, each free
    to shift by the clearance, and the spacing between them.

    A point at ``t`` along the line from the first anchor to the second moves by
    ``(1 - t) a + t b`` for anchor shifts ``a`` and ``b``, at most ``(|1 - t| +
    |t|)`` clearances; and a point off the line, at ``d`` from it, also swings by
    the turn the two shifts can make, ``2 c d / S``."""

    first, second = anchors
    dx, dy = second.x_mm - first.x_mm, second.y_mm - first.y_mm
    spacing = math.hypot(dx, dy)
    ux, uy = dx / spacing, dy / spacing
    rx, ry = point[0] - first.x_mm, point[1] - first.y_mm
    t = (rx * ux + ry * uy) / spacing
    d = abs(-rx * uy + ry * ux)

    return ((abs(1 - t) + abs(t)) * clearance + 2 * clearance * d / spacing, spacing)


def _plate_thickness(
    pin: PogoSpec,
    working_travel_mm: float,
    top: float,
    tallest: float,
    least_floor: float,
    given: float | None,
    errors: list[str],
) -> float:
    """The plate's thickness: the user's, or the bore length the pin wants, as
    much as the room between the tallest part and the plate's top allows."""

    room = top - (tallest + PART_CLEARANCE_MM)
    floor = max(MINIMUM_PLATE_MM, least_floor)
    wanted = max(floor, PLATE_FACTOR * pin.barrel_diameter_mm)
    thickness = given if given is not None else min(wanted, room)

    if room < floor:
        errors.append(
            f"The pin is too short: with {working_travel_mm:g} mm of travel its "
            f"plate stands {top:.1f} mm above the board, and the tallest part is "
            f"{tallest:.1f} mm, leaving {max(room, 0.0):.1f} mm for a plate that "
            f"needs {floor:g} mm. Use a longer pin"
        )
    elif thickness > room + 1e-9:
        errors.append(
            f"plate.thickness_mm is {thickness:g}, but only {room:.1f} mm is free "
            f"between the {tallest:.1f} mm part and the plate's top at {top:.1f} mm"
        )
    elif thickness < floor:
        errors.append(
            f"plate.thickness_mm is {thickness:g}, under the printer's "
            f"{floor:g} mm minimum"
        )

    return thickness


def _check_pins_on_parts(
    points: Sequence[BoardTestPoint],
    above: list[Any],
    pin: PogoSpec,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Refuse a pin whose barrel would land on a part beside its pad."""

    if any(part.identifier == ENVELOPE_IDENTIFIER for part in above):
        warnings.append(
            "The board's parts are one envelope over the whole board, so which "
            "pins would land on a part cannot be checked: list the parts as "
            "components for that"
        )

    for point in points:
        for part in above:
            height = part.bottom_offset_from_board_top_mm + part.height_mm

            if part.identifier == ENVELOPE_IDENTIFIER or height <= 0.05:
                continue

            reach = _rectangle_distance(
                point.position,
                (part.center_x_mm, part.center_y_mm),
                part.width_mm,
                part.depth_mm,
            )

            if reach < pin.barrel_diameter_mm / 2 + PIN_PART_MARGIN_MM:
                errors.append(
                    f"The pin on {point.identifier} would land on {part.identifier}, "
                    f"a part {height:.1f} mm tall beside the pad"
                )


def plan_fixture(
    *,
    board: BoardFileSpec,
    points: Sequence[BoardTestPoint],
    pin: PogoSpec,
    working_travel_mm: float,
    locating: str,
    profile: Mapping[str, Any],
    nest_wall_mm: float = DEFAULT_WALL_MM,
    plate_thickness_mm: float | None = None,
) -> FixturePlan:
    """Lay a fixture out and add up what can move its pins. Every problem is
    collected, so the user sees them all."""

    fits, least_wall, least_floor = printer_numbers(profile)
    errors: list[str] = []
    warnings: list[str] = []
    clearance = fits["sliding_clearance_per_side"]
    above, below = _parts(board)
    tallest = max(
        (p.bottom_offset_from_board_top_mm + p.height_mm for p in above), default=0.0
    )
    under = max((-p.bottom_offset_from_board_top_mm for p in below), default=0.0)
    under_depth = max(under - board.board_thickness_mm, 0.0) + UNDER_CLEARANCE_MM

    if nest_wall_mm < least_wall:
        errors.append(
            f"nest.wall_mm is {nest_wall_mm:g}, under the printer's {least_wall:g} mm "
            "minimum wall"
        )

    top = pin.free_length_mm - working_travel_mm
    thickness = _plate_thickness(
        pin, working_travel_mm, top, tallest, least_floor, plate_thickness_mm, errors
    )
    bore = bore_diameter(pin, fits)
    _check_pins_on_parts(points, above, pin, errors, warnings)

    if locating == "holes":
        anchors = _hole_anchors(board, fits, below, errors)
    else:
        anchors = _ear_anchors(board, fits, nest_wall_mm)

    supports, unsupported = _supports(points, below)

    if unsupported:
        warnings.append(
            "The board is not propped under "
            + ", ".join(unsupported)
            + ": a part sits under each, and the pins' force may flex the board there"
        )

    budgets, worst, spacing = _budgets(
        points, anchors, pin, working_travel_mm, thickness, top, fits
    )
    _check_budgets(points, budgets, pin, errors)

    return FixturePlan(
        points=tuple(points),
        pin=pin,
        working_travel_mm=working_travel_mm,
        plate_top_mm=top,
        plate_thickness_mm=thickness,
        plate_underside_mm=top - thickness,
        tallest_part_mm=tallest,
        under_depth_mm=under_depth,
        bore_diameter_mm=bore,
        nest_wall_mm=nest_wall_mm,
        clearance_mm=clearance,
        locating=locating,
        anchors=anchors,
        anchor_spacing_mm=spacing,
        supports=tuple(supports),
        unsupported=tuple(unsupported),
        budgets=budgets,
        worst_point=worst,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _supports(
    points: Sequence[BoardTestPoint], below: list[Any]
) -> tuple[list[Point], list[str]]:
    """A post under each test point, unless a part sits there."""

    posts: list[Point] = []
    bare: list[str] = []

    for point in points:
        blocked = any(
            _rectangle_distance(
                point.position,
                (p.center_x_mm, p.center_y_mm),
                p.width_mm,
                p.depth_mm,
            )
            < SUPPORT_POST_MM / 2 + SUPPORT_MARGIN_MM
            for p in below
        )

        if blocked:
            bare.append(point.identifier)
        else:
            posts.append(point.position)

    return posts, bare


def _budgets(
    points: Sequence[BoardTestPoint],
    anchors: Sequence[Anchor],
    pin: PogoSpec,
    working_travel_mm: float,
    thickness: float,
    plate_top: float,
    fits: Mapping[str, float],
) -> tuple[dict[str, Budget], str | None, float]:
    if len(anchors) < 2 or not points:
        return {}, None, 0.0

    slide = fits["sliding_clearance_per_side"]
    press = fits["press_fit_clearance_per_side"]
    budgets: dict[str, Budget] = {}
    spacing = 0.0

    for point in points:
        plate, spacing = _plate_play(point.position, anchors, slide)
        # The pin turns in its bore by up to two clearances over the bore's
        # length, and the tip is the whole depth from the bore's middle below it.
        tilt = (
            (2 * press / thickness) * (plate_top - thickness / 2)
            if thickness > 0
            else 0.0
        )
        budgets[point.identifier] = Budget(
            board_play_mm=slide,
            plate_play_mm=plate,
            bore_play_mm=press,
            tilt_mm=tilt,
        )

    worst = max(budgets, key=lambda name: budgets[name].total_mm)

    return budgets, worst, spacing


def _check_budgets(
    points: Sequence[BoardTestPoint],
    budgets: Mapping[str, Budget],
    pin: PogoSpec,
    errors: list[str],
) -> None:
    """Refuse a pin whose tip could miss its pad by the chain of clearances."""

    tip = pin.tip_diameter_mm / 2

    for point in points:
        budget = budgets.get(point.identifier)

        if budget is None:
            continue

        slack = point.pad_diameter_mm / 2 - tip

        if budget.total_mm > slack + 1e-9:
            link, value = budget.largest()
            errors.append(
                f"{point.identifier}: the clearances can move the tip "
                f"{budget.total_mm:.2f} mm off its pad, and the pad leaves "
                f"{max(slack, 0.0):.2f} mm. The largest link is {link}, at "
                f"{value:.2f} mm: tighten it, use a larger pad or a finer tip, or "
                "locate by the mounting holes"
            )
