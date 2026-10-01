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

The hinged closure is not built.

Frame: the board's own, as in :mod:`zcad_core.features.pcb_fixture_plan`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.pcb_fixture_plan import (
    EAR_OFFSET_MM,
    EAR_RADIUS_MM,
    FLOOR_MM,
    FixturePlan,
    outline_points,
)
from zcad_core.hardware import PogoSpec
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_file import BoardFileSpec
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
class ClosurePlan:
    """The screws, their ears, and the load they hold."""

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

    @property
    def load_per_screw_n(self) -> float:
        """The load one screw may have to carry: all of it, should the plate lift
        at the other end."""

        return self.preload_n

    @property
    def limit_checked(self) -> bool:
        return self.limit_n is not None

    @property
    def within_limit(self) -> bool:
        return self.limit_n is None or self.load_per_screw_n <= self.limit_n

    def to_dict(self) -> dict[str, Any]:
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
            "preload_note": (
                "The pins' force at the working travel, taken as proportional to "
                "the travel from the figure the pin was given at its own. A "
                "straight-spring assumption: confirm it from the datasheet."
            ),
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


def plan_closure(
    *,
    board: BoardFileSpec,
    plan: FixturePlan,
    kind: str,
    screw: str,
    limit_n: float | None,
    limit_source: str,
    profile: Mapping[str, Any],
) -> ClosurePlan:
    """Place the screws and add up the load they hold. Every problem is
    collected, so the user sees them all."""

    errors: list[str] = []
    warnings: list[str] = []
    _, least_wall, least_floor = printer_numbers(profile)
    pins = len(plan.points)
    preload = preload_n(plan.pin, pins, plan.working_travel_mm)
    fastener = _fastener(screw, errors) if kind == "screws" else None

    if kind != "screws":
        errors.append(
            f"closure {kind!r} is not built yet; use 'screws', which holds the "
            "plate with two screws"
        )

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
