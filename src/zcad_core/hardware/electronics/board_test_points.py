"""A board's test points: the pads a probe lands on.

A test point is a pad on one side of the board, given by its centre and its
diameter, in the board's frame (centre at the origin, +X right and +Y up the
page seen from above). The list is optional: it is a property of the board, so
it lives in the board file, and a test fixture reads it from there.

``board import`` cannot find test points: a STEP model carries no copper. They
come from the board's design, and from the person who wrote the file.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_outline import Point

SIDES = ("top", "bottom")
PAD_DIAMETER_RANGE_MM = (0.5, 10.0)
MAXIMUM_TEST_POINTS = 200
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


@dataclass(frozen=True)
class BoardTestPoint:
    """One test pad."""

    identifier: str
    x_mm: float
    y_mm: float
    pad_diameter_mm: float
    side: str
    net: str = ""

    @property
    def position(self) -> Point:
        return (self.x_mm, self.y_mm)


def _number(
    entry: Mapping[str, Any],
    name: str,
    where: str,
    error: Callable[[str], None],
    *,
    low: float,
    high: float,
) -> float | None:
    value = entry.get(name)

    if value is None:
        error(f"{where}.{name} is missing")

        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        error(f"{where}.{name} must be a number, not {value!r}")

        return None

    if not low <= value <= high:
        error(f"{where}.{name} is {value:g}, outside {low:g} to {high:g}")

        return None

    return float(value)


def _check_one(
    entry: Any, index: int, error: Callable[[str], None]
) -> tuple[str, float, float, float, str] | None:
    where = f"test_points[{index}]"

    if not isinstance(entry, Mapping):
        error(f"{where} must be an object")

        return None

    name = entry.get("identifier")

    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        error(f"{where}.identifier must be a name of letters, digits, _ . -")

    x = _number(entry, "x_mm", where, error, low=-500.0, high=500.0)
    y = _number(entry, "y_mm", where, error, low=-500.0, high=500.0)
    pad = _number(
        entry,
        "pad_diameter_mm",
        where,
        error,
        low=PAD_DIAMETER_RANGE_MM[0],
        high=PAD_DIAMETER_RANGE_MM[1],
    )
    side = entry.get("side", "top")

    if side not in SIDES:
        error(f"{where}.side must be one of {SIDES}, not {side!r}")
        side = None

    net = entry.get("net", "")

    if not isinstance(net, str):
        error(f"{where}.net must be text")

    if (
        not isinstance(name, str)
        or x is None
        or y is None
        or pad is None
        or side is None
    ):
        return None

    return name, x, y, pad, side


def check_test_points(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    outline: Sequence[Point] | None,
    error: Callable[[str], None],
) -> None:
    """Check a file's ``test_points``: each pad whole on the board, none
    overlapping another on its side, and no name used twice."""

    listed = data.get("test_points")

    if listed is None:
        return

    if not isinstance(listed, Sequence) or isinstance(listed, str):
        error("test_points must be a list")

        return

    if len(listed) > MAXIMUM_TEST_POINTS:
        error(f"A board has at most {MAXIMUM_TEST_POINTS} test points")

        return

    found = [point for i, e in enumerate(listed) if (point := _check_one(e, i, error))]
    names = [point[0] for point in found]

    if len(set(names)) != len(names):
        error("Test point identifiers must be unique")

    if size is not None:
        for name, x, y, pad, _ in found:
            _check_on_board(name, x, y, pad, size, outline, error)

    for index, first in enumerate(found):
        for second in found[index + 1 :]:
            if first[4] != second[4]:
                continue

            apart = math.hypot(first[1] - second[1], first[2] - second[2])

            if apart < (first[3] + second[3]) / 2 - 1e-9:
                error(
                    f"Test points {first[0]} and {second[0]} overlap: their pads are "
                    f"{apart:.2f} mm apart and {(first[3] + second[3]) / 2:.2f} mm "
                    "is the least"
                )


def _check_on_board(
    name: str,
    x: float,
    y: float,
    pad: float,
    size: tuple[float, float, float],
    outline: Sequence[Point] | None,
    error: Callable[[str], None],
) -> None:
    radius = pad / 2

    if outline is not None:
        inside = board_outline.depth_inside(outline, (x, y)) >= radius
    else:
        inside = abs(x) <= size[0] / 2 - radius and abs(y) <= size[1] / 2 - radius

    if not inside:
        error(
            f"Test point {name} at ({x:g}, {y:g}) is not wholly on the board: its "
            f"{pad:g} mm pad would hang over the edge"
        )


def parse_test_points(data: Mapping[str, Any]) -> tuple[BoardTestPoint, ...]:
    """The test points of a checked file."""

    return tuple(
        BoardTestPoint(
            identifier=str(entry["identifier"]),
            x_mm=float(entry["x_mm"]),
            y_mm=float(entry["y_mm"]),
            pad_diameter_mm=float(entry["pad_diameter_mm"]),
            side=str(entry.get("side", "top")),
            net=str(entry.get("net", "")),
        )
        for entry in data.get("test_points") or ()
    )
