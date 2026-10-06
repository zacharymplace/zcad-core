"""Retaining tabs for an object holder, when the object's weight is not enough to keep it in.

A tab is a strip of a side wall, cut free of the wall by a slit each side and rooted
``TAB_ROOT_MM`` above the floor, that rises past the object's top and carries a hook reaching in
over it. The object pushes the tabs apart as it goes in and they spring back over its top. With
tabs, the sides climb the object's whole height.

A tab bends as a cantilever by the clearance, the object's corner radius (the hook must reach past
the rounded corner to its flat top) and the overhang. Its strain is held to the flexure limit: the
engine's provisional one, or a coupon's measured one under ``--compensation-profile``. It bends
across the printed layers, as the holding nest's tabs and the coupon's tongues do.

The hook's underside is flat and prints with nothing under it, so a hook reaching more than
``MAXIMUM_HOOK_MM`` in from the wall is refused: an object with rounded corners needs a hook that
long to reach its flat top, and leaves tabs off. A side that carries a notch for an edge feature
carries no tab, since the notch runs to the wall's top through where the tab would be.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.holder_shapes import Placed, box, xz_prism
from zcad_core.features.mounts import (
    flexure_for,
    flexure_strain_limit,
    strain_limit_source,
)
from zcad_core.features.nest_features import (
    HOOK_FACE_MM,
    HOOK_GAP_MM,
    HOOK_HEIGHT_MM,
    SLIT_MM,
    TAB_ROOT_MM,
    TAB_WIDTH_MM,
)

# The longest a hook may reach in from the wall, its flat underside printed over nothing.
MAXIMUM_HOOK_MM = 2.5


@dataclass(frozen=True)
class HolderTab:
    """A tab on one side: which side (-1 left, +1 right seen from the room), its middle along
    Y, and how it bends."""

    side: float
    y_mm: float
    hook_mm: float
    reach_mm: float
    deflection_mm: float
    strain: float
    # The limit the tab was held to when it was planned, and where it came from.
    strain_limit: float
    strain_limit_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": "right" if self.side > 0 else "left",
            "width_mm": TAB_WIDTH_MM,
            "hook_mm": round(self.hook_mm, 3),
            "reach_mm": round(self.reach_mm, 3),
            "deflection_mm": round(self.deflection_mm, 3),
            "strain_percent": round(100 * self.strain, 3),
            "strain_limit_percent": round(100 * self.strain_limit, 2),
            "strain_limit_source": self.strain_limit_source,
        }


def plan_tabs(
    p: Placed,
    clearance: float,
    wall_mm: float,
    overhang_mm: float,
    notched_sides: Sequence[float],
) -> tuple[HolderTab, ...]:
    """A tab on each side without a notch, refused if none is free, the pocket is too shallow
    for one, a hook would reach too far, or a tab would strain past the limit."""

    sides = [side for side in (-1.0, 1.0) if side not in notched_sides]

    if not sides:
        raise ValueError(
            "Both sides carry a notch for an edge feature, which runs through where a tab "
            "would be: leave tabs off, or hang the object another way up"
        )

    pocket_y = 2 * clearance + p.depth_mm
    needed = TAB_WIDTH_MM + 2 * SLIT_MM

    if pocket_y < needed:
        raise ValueError(
            f"A tab is {TAB_WIDTH_MM:g} mm wide with a {SLIT_MM:g} mm slit each side, and the "
            f"pocket is only {pocket_y:.1f} mm deep: an object at least "
            f"{needed - 2 * clearance:.1f} mm thick takes tabs"
        )

    corner = p.radius_mm or 0.0
    hook = clearance + corner + overhang_mm

    if hook > MAXIMUM_HOOK_MM:
        raise ValueError(
            f"A hook must reach {hook:.1f} mm in from the wall to hold the object's flat top "
            f"past its {corner:g} mm corners, more than the {MAXIMUM_HOOK_MM:g} mm a hook printed "
            "upright may overhang: leave tabs off, or use a smaller overhang"
        )

    reach = p.height_mm - TAB_ROOT_MM + HOOK_GAP_MM
    flexure = flexure_for(hook, reach, wall_mm)
    limit = flexure_strain_limit()

    if flexure.strain > limit:
        needed_reach = math.sqrt(3 * wall_mm * hook / (2 * limit))
        raise ValueError(
            f"A tab on an object {p.height_mm:.1f} mm tall would strain "
            f"{100 * flexure.strain:.2f}%, over the {100 * limit:.2f}% limit "
            f"({strain_limit_source()}): its reach is {reach:.1f} mm and needs "
            f"{needed_reach:.1f} mm, or a thinner wall or a smaller overhang"
        )

    source = strain_limit_source()

    return tuple(
        HolderTab(side, pocket_y / 2, hook, reach, hook, flexure.strain, limit, source)
        for side in sides
    )


def tab_solids(
    tab: HolderTab, p: Placed, clearance: float, wall_mm: float
) -> tuple[cq.Workplane, cq.Workplane, list[cq.Workplane]]:
    """The tab's rise above the wall, its hook, and the two slits that free it."""

    inner = p.width_mm / 2 + clearance
    top = p.height_mm
    y0, y1 = tab.y_mm - TAB_WIDTH_MM / 2, tab.y_mm + TAB_WIDTH_MM / 2
    x0, x1 = sorted((tab.side * inner, tab.side * (inner + wall_mm)))
    rise = box(x0, x1, y0, y1, top, top + HOOK_GAP_MM + HOOK_HEIGHT_MM)
    # The hook's profile seen from the room: its underside level, its top sloping down to its
    # tip so the object pushes the tab aside on the way in.
    hook_profile = [
        (0.0, HOOK_GAP_MM),
        (tab.hook_mm, HOOK_GAP_MM),
        (tab.hook_mm, HOOK_GAP_MM + HOOK_FACE_MM),
        (0.0, HOOK_GAP_MM + HOOK_HEIGHT_MM),
    ]
    hook = xz_prism(
        [(tab.side * (inner - d), top + z) for d, z in hook_profile], y0, y1
    )
    slits = [
        box(x0 - 0.5, x1 + 0.5, y, y + SLIT_MM, TAB_ROOT_MM, top + 2.0)
        for y in (y0 - SLIT_MM, y1)
    ]

    return rise, hook, slits


def hooks_over_object(
    tabs: Sequence[HolderTab], p: Placed, solid: cq.Shape, overhang_mm: float
) -> bool:
    """Each hook has the object's flat top under it: the point under the middle of the hook's
    last ``overhang_mm``, just below the object's top, is inside the object."""

    corner = p.radius_mm or 0.0
    solids = solid.Solids()

    for tab in tabs:
        x = tab.side * (p.width_mm / 2 - corner - overhang_mm / 2)
        under = cq.Vector(x, tab.y_mm, p.height_mm - 0.1)

        if not any(part.isInside(under) for part in solids):
            return False

    return True
