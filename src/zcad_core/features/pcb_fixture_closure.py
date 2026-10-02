"""The closure of a PCB test fixture: two screws that hold the plate down.

The pins push the plate up with their combined force, so something must hold it
against the nest's rim. Two screws do: each goes down through a clearance hole in
the plate into a heat-set insert in an **ear** on the nest, on the sides the
finger notches are on, one at each end so the pair sit diagonally across the
plate.

The **preload** is the pins' force with the plate closed: the force each pin
gives at the working travel, times the number of pins. A pin's force at a travel
other than the one its maker gives is taken as proportional to the travel, a
straight spring; the record says so. It is a figure the maker's own datasheet
should confirm: a pin's force is rarely linear to its end.

What the engine checks, and what it does not:

- It checks the ears fit: clear of the dowel ears and the notches, wide enough
  round the insert for the printer's minimum wall, and tall enough for the pocket.
- It checks the preload against a screw's tensile limit **only if the fixture
  file gives one with its source**. The catalog has dimensions, not strengths, so
  there is no figure here to read it from, and the engine does not make one up.
- It does not check the plate bending between the screws, a printed ear pulling
  off, or an insert pulling out of printed plastic. A trial shows whether the
  plate stays down.

A **hinged** closure holds the plate on a pin along one long wall and closes it
with a snap catch on the opposite one, both from :mod:`zcad_core.features.lid_hinge`.
It needs a plain rectangular board, since the hinge and catch are built round a
rectangular wall, and the finger notch moves off the middle of the catch's wall to
leave room for it. The catch carries the share of the preload that a moment balance
about the pin gives it, from where each pin stands between the pin and the catch; the
hinge carries the rest. The catch's strain is checked as the enclosure's catch is,
and its load only against a limit the fixture file gives with its source.

Frame: the board's own, as in :mod:`zcad_core.features.pcb_fixture_plan`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.lid_hinge import axis_offset_mm
from zcad_core.features.pcb_fixture_plan import (
    EAR_OFFSET_MM,
    EAR_RADIUS_MM,
    FLOOR_MM,
    RELIEF_MARGIN_MM,
    FixturePlan,
    outline_points,
)
from zcad_core.hardware import PogoSpec
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_file import (
    ENVELOPE_IDENTIFIER,
    BoardFileSpec,
)
from zcad_core.hardware.electronics.board_outline import Point
from zcad_core.hardware.fasteners import FastenerSpec, get_fastener, list_fasteners

DEFAULT_SCREW = "M3"
# The finger notches are cut this big (see ``pcb_fixture``); an ear stands clear
# of one by at least this much.
NOTCH_RADIUS_MM = 4.5
EAR_GAP_MM = 1.5
# Ears stand this far clear of a dowel ear.
EAR_SPACING_MM = 1.0


@dataclass(frozen=True)
class HingePlan:
    """The hinge and catch: which walls, and how the preload divides."""

    hinge_edge: str
    closure_edge: str
    pin: str
    lever_mm: float
    catch_load_n: float
    hinge_load_n: float
    catch_limit_n: float | None
    catch_limit_source: str
    notch_offset_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "hinge_wall": self.hinge_edge,
            "catch_wall": self.closure_edge,
            "pin": self.pin,
            "lever_mm": round(self.lever_mm, 3),
            "catch_load_n": round(self.catch_load_n, 3),
            "hinge_load_n": round(self.hinge_load_n, 3),
            "load_note": (
                "The preload shared between the catch and the hinge by a moment "
                "balance about the pin, taking the pins' force as equal and the "
                "catch at the closure wall's outer face. The catch's strain "
                "limit is checked at build; its load only against a limit you "
                "give."
            ),
            "catch_load_limit_n": self.catch_limit_n,
            "catch_load_limit_source": self.catch_limit_source or None,
            "catch_load_limit_checked": self.catch_limit_n is not None,
            "finger_notch_offset_mm": round(self.notch_offset_mm, 3),
        }


@dataclass(frozen=True)
class ClosurePlan:
    """The screws, their ears, and the load they hold; or the hinge and catch."""

    kind: str
    preload_n: float
    pins: int
    screw: str
    screws: tuple[Point, ...]
    ear_radius_mm: float
    clearance_hole_mm: float
    pocket_diameter_mm: float
    pocket_depth_mm: float
    screw_length_min_mm: float
    limit_n: float | None
    limit_source: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    hinge: HingePlan | None = None

    @property
    def load_per_screw_n(self) -> float:
        """The load one screw may have to carry: all of it, should the plate lift
        at the other end."""

        return self.preload_n

    @property
    def limit_checked(self) -> bool:
        if self.hinge is not None:
            return self.hinge.catch_limit_n is not None

        return self.limit_n is not None

    @property
    def within_limit(self) -> bool:
        if self.hinge is not None:
            limit = self.hinge.catch_limit_n

            return limit is None or self.hinge.catch_load_n <= limit

        return self.limit_n is None or self.load_per_screw_n <= self.limit_n

    def to_dict(self) -> dict[str, Any]:
        if self.hinge is not None:
            return {
                "kind": self.kind,
                "pins": self.pins,
                "preload_n": round(self.preload_n, 3),
                "preload_note": _PRELOAD_NOTE,
                "hinge": self.hinge.to_dict(),
                "not_checked": [
                    "the plate bending between the hinge and the catch",
                    "the hinge's knuckles or pin wearing",
                    "the catch's hook wearing or creeping under load",
                ],
            }

        return {
            "kind": self.kind,
            "screw": self.screw,
            "screws": [[round(x, 3), round(y, 3)] for x, y in self.screws],
            "ear_radius_mm": round(self.ear_radius_mm, 3),
            "clearance_hole_mm": round(self.clearance_hole_mm, 3),
            "insert_pocket_diameter_mm": round(self.pocket_diameter_mm, 3),
            "insert_pocket_depth_mm": round(self.pocket_depth_mm, 3),
            "screw_length_min_mm": round(self.screw_length_min_mm, 3),
            "pins": self.pins,
            "preload_n": round(self.preload_n, 3),
            "preload_note": _PRELOAD_NOTE,
            "load_per_screw_n": round(self.load_per_screw_n, 3),
            "load_per_screw_note": (
                "The whole preload: should the plate lift at one end, the other "
                "screw carries it all."
            ),
            "tensile_limit_n": self.limit_n,
            "tensile_limit_source": self.limit_source or None,
            "tensile_limit_checked": self.limit_checked,
            "not_checked": [
                "the plate bending between the screws",
                "a printed ear pulling off the nest",
                "an insert pulling out of printed plastic",
            ],
        }


_PRELOAD_NOTE = (
    "The pins' force at the working travel, taken as proportional to the travel "
    "from the figure the pin was given at its own. A straight-spring assumption: "
    "confirm it from the datasheet."
)


def preload_n(pin: PogoSpec, count: int, working_travel_mm: float) -> float:
    """The pins' combined force with the plate closed, taking a pin's force as
    proportional to its travel (the figure the maker gives is at one travel)."""

    return count * pin.force_n * working_travel_mm / pin.force_at_travel_mm


def _edge(points: Sequence[Point], along_x: bool, lateral: float, sign: float) -> float:
    """Where the outline's edge is, on one of the two long sides, at a distance
    ``lateral`` along it from the middle."""

    if along_x:
        found = board_outline.chord([(y, x) for x, y in points], lateral)
    else:
        found = board_outline.chord(points, lateral)

    if found is None:
        raise ValueError("outside the outline")

    return found[1] if sign > 0 else found[0]


def _screw_positions(
    board: BoardFileSpec, reach: float, ear_radius: float, errors: list[str]
) -> tuple[Point, ...]:
    """Two ears on the long sides, a notch and an ear apart from the middle, on
    opposite sides and opposite ends."""

    points = outline_points(board)
    along_x = board.board_width_mm >= board.board_length_mm
    along = board.board_width_mm if along_x else board.board_length_mm
    lateral = NOTCH_RADIUS_MM + ear_radius + EAR_GAP_MM
    placed: list[Point] = []

    if along / 2 < lateral + ear_radius:
        errors.append(
            f"The board is {along:g} mm along its longer side; the screws' ears "
            f"need {2 * (lateral + ear_radius):g} mm: the closure cannot be built"
        )

        return ()

    for end, sign in ((-1.0, 1.0), (1.0, -1.0)):
        try:
            edge = _edge(points, along_x, end * lateral, sign)
        except ValueError:
            errors.append(
                "The outline does not reach the screws' ears: the closure cannot "
                "be built"
            )

            return ()

        outward = edge + sign * (reach + EAR_OFFSET_MM)
        placed.append((end * lateral, outward) if along_x else (outward, end * lateral))

    return (placed[0], placed[1])


def _fastener(size: str, errors: list[str]) -> FastenerSpec | None:
    try:
        spec = get_fastener(size)
    except ValueError:
        errors.append(f"screw size {size!r} is not in the catalog: {list_fasteners()}")

        return None

    if (
        spec.heat_set_insert_diameter_mm is None
        or spec.heat_set_insert_depth_mm is None
    ):
        errors.append(f"{size} has no heat-set insert in the catalog")

        return None

    return spec


def _check_ears(
    screws: Sequence[Point], plan: FixturePlan, ear_radius: float, errors: list[str]
) -> None:
    for x, y in screws:
        for anchor in plan.anchors:
            if anchor.kind != "dowel":
                continue

            gap = math.dist((x, y), (anchor.x_mm, anchor.y_mm)) - ear_radius
            gap -= EAR_RADIUS_MM

            if gap < EAR_SPACING_MM:
                errors.append(
                    f"The screw ear at ({x:.1f}, {y:.1f}) is {gap:.1f} mm from a "
                    "dowel ear: the board is too small to carry both"
                )


def window_spans(
    board: BoardFileSpec, clearance_mm: float, edge: str
) -> list[tuple[float, float]]:
    """Where along a wall the nest has a window for a part that overhangs it: the
    stretches, from the board's centre, that the catch and the hinge must avoid."""

    on_y = edge.endswith("_y")
    half = (board.board_length_mm if on_y else board.board_width_mm) / 2
    sign = 1.0 if edge.startswith("positive") else -1.0
    spans = []

    for part in board.components:
        if part.identifier == ENVELOPE_IDENTIFIER:
            continue

        across, size_across = (
            (part.center_y_mm, part.depth_mm)
            if on_y
            else (part.center_x_mm, part.width_mm)
        )
        along, size_along = (
            (part.center_x_mm, part.width_mm)
            if on_y
            else (part.center_y_mm, part.depth_mm)
        )
        reach = sign * (across + sign * (size_across / 2 + RELIEF_MARGIN_MM))

        if reach > half + clearance_mm:
            spans.append(
                (
                    along - size_along / 2 - RELIEF_MARGIN_MM,
                    along + size_along / 2 + RELIEF_MARGIN_MM,
                )
            )

    return spans


def hinge_walls(board: BoardFileSpec, clearance_mm: float) -> tuple[str, str, bool]:
    """The wall that takes the hinge, the wall opposite it that takes the catch,
    and whether the long walls face Y. The hinge goes on the positive long wall
    unless a window is cut in it, then on the negative one; refused if both have a
    window, since the knuckles would close it over a part that must lift out."""

    on_y = board.board_width_mm >= board.board_length_mm
    positive, negative = (
        ("positive_y", "negative_y") if on_y else ("positive_x", "negative_x")
    )

    for hinge, catch in ((positive, negative), (negative, positive)):
        if not window_spans(board, clearance_mm, hinge):
            return hinge, catch, on_y

    raise ValueError(
        "Both long walls have a window for a part that overhangs the board, and "
        "the hinge's knuckles would close one over it"
    )


def hinge_notch_offset(board: BoardFileSpec) -> float:
    """Where along the catch's wall the finger notch goes: toward one end, so the
    catch has the rest of the wall."""

    half = max(board.board_width_mm, board.board_length_mm) / 2

    return -(half - NOTCH_RADIUS_MM - 1.0)


def _hinge_plan(
    *,
    board: BoardFileSpec,
    plan: FixturePlan,
    preload: float,
    pin: str,
    limit_n: float | None,
    limit_source: str,
    errors: list[str],
) -> HingePlan | None:
    """Divide the preload between the catch and the hinge, and refuse a board the
    hinge cannot be built on."""

    if board.outline_points_mm is not None:
        errors.append(
            "A hinged closure needs a plain rectangular board outline: the hinge "
            "and the catch are built round a straight wall. Close this one with "
            "screws"
        )

        return None

    try:
        fastener = get_fastener(pin)
    except ValueError:
        errors.append(f"hinge.pin {pin!r} is not in the catalog: {list_fasteners()}")

        return None

    try:
        hinge_edge, closure_edge, on_y = hinge_walls(board, plan.clearance_mm)
    except ValueError as error:
        errors.append(str(error))

        return None

    side = 1.0 if hinge_edge.startswith("positive") else -1.0
    half = (board.board_length_mm if on_y else board.board_width_mm) / 2
    half += plan.clearance_mm + plan.nest_wall_mm
    axis = half + axis_offset_mm(fastener)
    lever = axis + half
    share = preload / max(len(plan.points), 1)
    moment = sum(
        share * (axis - side * (point.y_mm if on_y else point.x_mm))
        for point in plan.points
    )
    catch = moment / lever

    return HingePlan(
        hinge_edge=hinge_edge,
        closure_edge=closure_edge,
        pin=pin,
        lever_mm=lever,
        catch_load_n=catch,
        hinge_load_n=preload - catch,
        catch_limit_n=limit_n,
        catch_limit_source=limit_source,
        notch_offset_mm=hinge_notch_offset(board),
    )


def plan_closure(
    *,
    board: BoardFileSpec,
    plan: FixturePlan,
    kind: str,
    screw: str,
    limit_n: float | None,
    limit_source: str,
    profile: Mapping[str, Any],
    hinge_pin: str = DEFAULT_SCREW,
    catch_limit_n: float | None = None,
    catch_limit_source: str = "",
) -> ClosurePlan:
    """Place the screws and add up the load they hold, or lay out the hinge and
    divide the preload. Every problem is collected, so the user sees them all."""

    errors: list[str] = []
    warnings: list[str] = []
    _, least_wall, least_floor = printer_numbers(profile)
    pins = len(plan.points)
    preload = preload_n(plan.pin, pins, plan.working_travel_mm)

    if kind == "hinge":
        return _plan_hinged(
            board=board,
            plan=plan,
            preload=preload,
            pin=hinge_pin,
            limit_n=catch_limit_n,
            limit_source=catch_limit_source,
        )

    fastener = _fastener(screw, errors) if kind == "screws" else None

    if kind != "screws":
        errors.append(f"closure {kind!r} is not one of 'screws' and 'hinge'")

    pocket = fastener.heat_set_insert_diameter_mm if fastener else None
    depth = fastener.heat_set_insert_depth_mm if fastener else None
    hole = fastener.clearance_hole_mm if fastener else 0.0
    ear_radius = max(EAR_RADIUS_MM, (pocket or 0.0) / 2 + least_wall)
    screws: tuple[Point, ...] = ()

    if fastener is not None and pocket is not None and depth is not None:
        reach = plan.clearance_mm + plan.nest_wall_mm
        screws = _screw_positions(board, reach, ear_radius, errors)
        ear_height = plan.plate_underside_mm - (
            -board.board_thickness_mm - plan.under_depth_mm - FLOOR_MM
        )

        if depth + least_floor > ear_height:
            errors.append(
                f"The ear is {ear_height:.1f} mm tall; the insert's {depth:g} mm "
                f"pocket and a {least_floor:g} mm floor need more"
            )

        _check_ears(screws, plan, ear_radius, errors)

    if limit_n is None:
        warnings.append(
            f"The closure's preload is {preload:.1f} N, and it is not checked "
            "against a screw's strength: give the screw's tensile limit and its "
            "source in the fixture file's 'screw' section"
        )

    if limit_n is not None and preload > limit_n:
        errors.append(
            f"The pins' preload is {preload:.1f} N, more than the {limit_n:g} N "
            f"a {screw} screw is given to hold ({limit_source})"
        )

    return ClosurePlan(
        kind=kind,
        preload_n=preload,
        pins=pins,
        screw=screw,
        screws=screws,
        ear_radius_mm=ear_radius,
        clearance_hole_mm=hole,
        pocket_diameter_mm=pocket or 0.0,
        pocket_depth_mm=depth or 0.0,
        screw_length_min_mm=plan.plate_thickness_mm + (depth or 0.0),
        limit_n=limit_n,
        limit_source=limit_source,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _plan_hinged(
    *,
    board: BoardFileSpec,
    plan: FixturePlan,
    preload: float,
    pin: str,
    limit_n: float | None,
    limit_source: str,
) -> ClosurePlan:
    errors: list[str] = []
    warnings: list[str] = []
    hinge = _hinge_plan(
        board=board,
        plan=plan,
        preload=preload,
        pin=pin,
        limit_n=limit_n,
        limit_source=limit_source,
        errors=errors,
    )

    if hinge is not None and limit_n is None:
        warnings.append(
            f"The catch carries {hinge.catch_load_n:.1f} N of the "
            f"{preload:.1f} N preload, and that is not checked against what the "
            "catch can hold: give its load limit and the source in the fixture "
            "file's 'hinge' section"
        )

    if hinge is not None and limit_n is not None and hinge.catch_load_n > limit_n:
        errors.append(
            f"The catch carries {hinge.catch_load_n:.1f} N of the pins' preload, "
            f"more than the {limit_n:g} N it is given to hold ({limit_source})"
        )

    return ClosurePlan(
        kind="hinge",
        preload_n=preload,
        pins=len(plan.points),
        screw="",
        screws=(),
        ear_radius_mm=0.0,
        clearance_hole_mm=0.0,
        pocket_diameter_mm=0.0,
        pocket_depth_mm=0.0,
        screw_length_min_mm=0.0,
        limit_n=None,
        limit_source="",
        errors=tuple(errors),
        warnings=tuple(warnings),
        hinge=hinge,
    )
