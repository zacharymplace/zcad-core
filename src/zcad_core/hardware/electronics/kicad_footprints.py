"""Where a KiCad footprint sits, and the frame a board file is written in.

Shared by the KiCad import's readers of the outline, the holes, the parts and
the test points, so they place a footprint's points one way.

KiCad's footprint angle is taken as counter-clockwise on screen and a
bottom-side footprint as mirrored in X before it is turned. Neither is checked
against a real board yet: ``Placement.unsure`` says when a point depends on one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from zcad_core.hardware.electronics import kicad_sexp
from zcad_core.hardware.electronics.board_outline import Point
from zcad_core.hardware.electronics.kicad_sexp import Node


@dataclass(frozen=True)
class Placement:
    """Where a footprint sits: position, angle (degrees) and side."""

    x_mm: float = 0.0
    y_mm: float = 0.0
    angle: float = 0.0
    bottom: bool = False

    @property
    def unsure(self) -> bool:
        """Whether a point's place depends on a convention not yet checked."""

        return self.angle % 360 != 0 or self.bottom

    def apply(self, point: Point) -> Point:
        x, y = point

        if self.bottom:
            x = -x

        turn = math.radians(self.angle)
        # Counter-clockwise on screen; the file's Y points down.
        return (
            self.x_mm + x * math.cos(turn) + y * math.sin(turn),
            self.y_mm - x * math.sin(turn) + y * math.cos(turn),
        )


@dataclass(frozen=True)
class Frame:
    """KiCad's frame to the board file's: Y flipped, the outline's centre at
    the origin."""

    centre: Point

    def __call__(self, point: Point) -> Point:
        return (point[0] - self.centre[0], -(point[1] - self.centre[1]))


def atom(root: Node, token: str) -> str | None:
    """The first argument of ``root``'s ``token`` form, as text."""

    found = kicad_sexp.child(root, token)

    return str(found[1]) if found is not None and len(found) > 1 else None


def footprint_reference(footprint: Node) -> str:
    for text in kicad_sexp.children(footprint, "fp_text"):
        if len(text) > 2 and text[1] == "reference":
            return str(text[2])

    for prop in kicad_sexp.children(footprint, "property"):
        if len(prop) > 2 and prop[1] == "Reference":
            return str(prop[2])

    return str(footprint[1]) if len(footprint) > 1 else "?"


def footprint_placement(footprint: Node) -> Placement:
    layer = atom(footprint, "layer") or "F.Cu"
    at = kicad_sexp.child(footprint, "at")

    if at is None:
        raise ValueError(f"footprint {footprint_reference(footprint)} has no position")

    x, y = kicad_sexp.numbers(at, 2)
    angle = kicad_sexp.number(at[3]) if len(at) > 3 else 0.0

    return Placement(x, y, angle, layer.startswith("B."))
