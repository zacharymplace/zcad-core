"""How a stack holds together: magnets and bolts at the profile's holding points.

A profile lists points in a cell, from its centre. An item says what it holds with there:

- ``lip``: nothing at the points; the foot sits in the lip and gravity does the rest;
- ``magnet``: a pocket for a catalogued round magnet, in the bottom of each cell's foot
  and in the floor of each of a baseplate's pockets, so the two meet; or
- ``bolt``: a heat-set insert pocket in the bottom of each foot, and a clearance hole
  through a baseplate's floor under it, so a screw from below draws the bin down.

The engine records the size of a magnet or an insert and builds the pocket; it states
no pull force and no holding force. Which way a magnet faces is the user's: the engine
builds both pockets the same size at the same place.

A pocket is refused when it would break through, leave too little foot or floor above it,
or come within the printer's minimum wall of the edge of the foot's bottom.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from zcad_core.features.guide_common import Findings
from zcad_core.features.stack_profile import StackProfile
from zcad_core.hardware.fasteners import get_fastener, list_fasteners
from zcad_core.hardware.magnets import get_magnet, list_magnets

HOLDING = ("lip", "magnet", "bolt")
# What a stack top can hold by: a bolt would go through the closed lid.
HOLDING_TOP = ("lip", "magnet")


@dataclass(frozen=True)
class Holding:
    """What an item holds with, as sizes: the pocket in a foot's bottom, the hole through a
    baseplate's floor, and how deep a pocket goes."""

    kind: str
    identifier: str = ""
    pocket_diameter_mm: float = 0.0
    pocket_depth_mm: float = 0.0
    hole_diameter_mm: float = 0.0

    @property
    def holds(self) -> bool:
        return self.kind != "lip"


LIP = Holding("lip")


def holding_for(kind: str, magnet: str, fastener: str) -> Holding:
    """The sizes of a holding, from the catalogues; ``kind`` must already be checked."""

    if kind == "magnet":
        spec = get_magnet(magnet)

        return Holding(
            "magnet", spec.identifier, spec.pocket_diameter_mm, spec.pocket_depth_mm
        )

    if kind == "bolt":
        screw = get_fastener(fastener)

        return Holding(
            "bolt",
            screw.identifier,
            float(screw.heat_set_insert_diameter_mm or 0.0),
            float(screw.heat_set_insert_depth_mm or 0.0),
            screw.clearance_hole_mm,
        )

    return LIP


def check_holding_fields(
    entry: Mapping[str, Any], where: str, findings: Findings
) -> None:
    """The item's ``holding`` and the catalogue entry it needs."""

    kind = entry.get("holding", "lip")

    if kind not in HOLDING:
        findings.errors.append(f"{where}.holding must be one of {HOLDING}")

        return

    magnet, fastener = entry.get("magnet"), entry.get("fastener")

    if kind == "magnet":
        if magnet not in list_magnets():
            findings.errors.append(
                f"{where}.magnet must name a catalogued magnet: {list(list_magnets())}"
            )
    elif magnet is not None:
        findings.errors.append(f"{where}.magnet is for holding by magnets only")

    if kind == "bolt":
        if fastener not in list_fasteners():
            findings.errors.append(
                f"{where}.fastener must name a catalogued fastener: "
                f"{list(list_fasteners())}"
            )
    elif fastener is not None:
        findings.errors.append(f"{where}.fastener is for holding by bolts only")


def foot_bottom_half_mm(profile: StackProfile) -> float:
    """Half the width of a foot's bottom, where a pocket opens."""

    return profile.cell_top_mm / 2 - profile.foot[0][0]


def check_holding_fits(
    name: str,
    kind: str,
    holding: Holding,
    floor_mm: float,
    profile: StackProfile,
    least_wall: float,
    least_floor: float,
    errors: list[str],
) -> None:
    """Refuse a holding the profile or the item cannot carry."""

    if not holding.holds:
        return

    if not profile.holding_points:
        errors.append(
            f"{name}: holding by {holding.kind} needs holding_points in the profile, "
            "and it has none"
        )

        return

    if kind == "baseplate" and holding.kind == "magnet":
        need = holding.pocket_depth_mm + least_floor

        if floor_mm < need:
            errors.append(
                f"{name}: a {holding.identifier} pocket is {holding.pocket_depth_mm:g} mm "
                f"deep, so floor_mm must be at least {need:g} mm to keep the printer's "
                f"{least_floor:g} mm under it; it is {floor_mm:g}"
            )

    if kind == "bin":
        _check_foot(name, holding, profile, least_wall, least_floor, errors)


def _check_foot(
    name: str,
    holding: Holding,
    profile: StackProfile,
    least_wall: float,
    least_floor: float,
    errors: list[str],
) -> None:
    left = profile.foot_height_mm - holding.pocket_depth_mm

    if left < least_floor:
        errors.append(
            f"{name}: a {holding.identifier} pocket is {holding.pocket_depth_mm:g} mm "
            f"deep in a foot {profile.foot_height_mm:g} mm high, leaving {left:g} mm, "
            f"under the printer's {least_floor:g} mm; use a smaller one or a taller foot"
        )

    reach = holding.pocket_diameter_mm / 2 + least_wall
    room = foot_bottom_half_mm(profile)

    for x, y in profile.holding_points:
        if max(abs(x), abs(y)) + reach > room:
            errors.append(
                f"{name}: a {holding.identifier} pocket at ({x:g}, {y:g}) comes within "
                f"{least_wall:g} mm of the edge of the foot's bottom, which is "
                f"{room:g} mm from the centre"
            )

            return


def screw_length_mm(holding: Holding, floor_mm: float) -> float:
    """The least a screw must be to pass a baseplate's floor and reach the insert's
    depth, or ``0`` for a holding that takes no screw."""

    return (
        round(floor_mm + holding.pocket_depth_mm, 3) if holding.kind == "bolt" else 0.0
    )
