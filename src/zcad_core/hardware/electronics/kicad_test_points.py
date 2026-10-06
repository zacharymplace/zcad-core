"""A KiCad board's test points, which a STEP model cannot give.

A footprint is a test point if its library name starts with ``TestPoint``, its
reference is ``TP`` and digits, or the user names it with ``--test-points``.
Its one copper pad is the point: the pad's centre through the footprint is the
place, the footprint's layer the side, a round pad's size the diameter (the
smaller side of any other shape, with a warning, since a probe lands in the
pad's middle), and the pad's net its net. A footprint with more than one pad,
or none, is listed and not read. What a board file refuses of a test point
(a pad under 0.5 mm, two that overlap, one off the outline, a name used
twice) is left to the board file's own check.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from zcad_core.hardware.electronics import kicad_sexp
from zcad_core.hardware.electronics.kicad_footprints import (
    Frame,
    footprint_placement,
    footprint_reference,
)
from zcad_core.hardware.electronics.kicad_sexp import Node

TEST_POINT_LIBRARY = "TestPoint"
TEST_POINT_REFERENCE = re.compile(r"TP\d+")


@dataclass(frozen=True)
class TestPointsRead:
    """The test points as a board file writes them, and what was noted."""

    points: list[dict[str, Any]]
    not_read: list[dict[str, str]]
    notes: list[str]


def is_test_point(reference: str, library: str, named: Sequence[str] = ()) -> bool:
    return (
        library.rpartition(":")[2].startswith(TEST_POINT_LIBRARY)
        or TEST_POINT_REFERENCE.fullmatch(reference) is not None
        or reference in named
    )


def _net(pad: Node) -> str:
    """The pad's net name: ``(net N "NAME")`` up to KiCad 8, and a bare
    ``(net "NAME")`` after."""

    net = kicad_sexp.child(pad, "net")

    if net is None or len(net) < 2:
        return ""

    return str(net[2]) if len(net) > 2 else str(net[1])


def _diameter(pad: Node, reference: str, notes: list[str]) -> float | None:
    size = kicad_sexp.child(pad, "size")

    if size is None:
        return None

    width, height = kicad_sexp.numbers(size, 2)
    shape = str(pad[3]) if len(pad) > 3 else ""

    if shape != "circle" or abs(width - height) > 1e-9:
        notes.append(
            f"{reference} has a {shape or 'shaped'} {width:g} x {height:g} mm pad: "
            f"its diameter is taken as {min(width, height):g} mm, the smaller side"
        )

    return min(width, height)


def read_test_points(
    root: Node,
    frame: Frame,
    named: Sequence[str],
    unverified: list[str],
) -> TestPointsRead:
    """The test points of the file, in the board file's frame."""

    points: list[dict[str, Any]] = []
    not_read: list[dict[str, str]] = []
    notes: list[str] = []
    found: set[str] = set()

    for footprint in kicad_sexp.children(root, "footprint"):
        reference = footprint_reference(footprint)
        library = str(footprint[1]) if len(footprint) > 1 else ""

        if not is_test_point(reference, library, named):
            continue

        found.add(reference)
        pads = [
            pad
            for pad in kicad_sexp.children(footprint, "pad")
            if len(pad) > 2 and pad[2] != "np_thru_hole"
        ]

        if len(pads) != 1:
            not_read.append(
                {
                    "reference": reference,
                    "why": f"{len(pads)} copper pads, not one: give it by hand",
                }
            )
            continue

        (pad,) = pads
        diameter = _diameter(pad, reference, notes)
        at = kicad_sexp.child(pad, "at")

        if diameter is None or at is None:
            not_read.append(
                {"reference": reference, "why": "its pad has no size or place"}
            )
            continue

        place = footprint_placement(footprint)
        local_x, local_y = kicad_sexp.numbers(at, 2)
        x, y = frame(place.apply((local_x, local_y)))

        if place.unsure and max(abs(local_x), abs(local_y)) > 1e-9:
            unverified.append(
                f"{reference}: a test pad at ({local_x:g}, {local_y:g}) in a "
                f"footprint at angle {place.angle:g}"
                + (" on the bottom side" if place.bottom else "")
            )

        points.append(
            {
                "identifier": reference,
                "x_mm": round(x, 3),
                "y_mm": round(y, 3),
                "pad_diameter_mm": round(diameter, 3),
                "side": "bottom" if place.bottom else "top",
                "net": _net(pad),
            }
        )

    missing = [reference for reference in named if reference not in found]

    if missing:
        raise ValueError(
            f"--test-points names {', '.join(missing)}, which the file does not have"
        )

    return TestPointsRead(points=points, not_read=not_read, notes=notes)
