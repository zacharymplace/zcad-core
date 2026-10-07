"""A fitted Gridfinity bin: a solid bin with a pocket cut for one measured object.

The object is a caliper capture or a STEP model, as an object holder's is, lying in the bin with
its face up: a capture's length along X and its width along Y; a model turned so its ``up`` axis is
the bin's +Z and its ``out`` axis +Y. The bin is the fewest units that hold the object's footprint
with the clearance and a wall round it, and the fewest height units that sink it ``depth`` mm with
a floor left above the base. The pocket is the object's shadow seen from above, grown by the
clearance and open at the top, so the object lifts straight out whatever it does beneath. A finger
notch is cut at the middle of each long side of the pocket where the bin's wall leaves room.

The bin is solid below its top, so a bin stacked on it rests on that top inside the lip, not on
the lip's slopes as it would in a hollow bin. The base, the lip and every interface figure are the
plain bin's; inside, the fit is the engine's (the printer's sliding clearance, the coupon's measured
one, or the user's), unlike the interface, which is never changed.

Frame: the bin's: X and Y centred on the footprint, Z up from its bottom. Millimetres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.gridfinity import (
    BinSpec,
    base_to_standard,
    bin_block,
    lip_socket,
    seat_height_mm,
    underside_holes,
)
from zcad_core.features.gridfinity_baseplate import BaseplateSpec, build_baseplate
from zcad_core.features.gridfinity_shapes import (
    GridfinityPart,
    base_unit,
    box,
    empty_at,
    held,
)
from zcad_core.features.gridfinity_standard import (
    BASE_PROFILE_HEIGHT_MM,
    BASE_TOP_MM,
    GRID_MM,
    HEIGHT_UNIT_MM,
)
from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.holder_model import HolderModel
from zcad_core.features.nest_core import clear, lifts_out
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.wearables.capture import WearableCapture

# A finger notch at the middle of each long side of the pocket: this wide, reaching this far past
# the pocket's edge, where the bin's wall leaves room for it.
FINGER_NOTCH_WIDTH_MM = 20.0
FINGER_NOTCH_REACH_MM = 8.0
# The narrowest clearance a measured shortfall may bring the pocket down to.
MINIMUM_CLEARANCE_MM = 0.05
Point = tuple[float, float]


@dataclass(frozen=True)
class FittedSpec:
    """A fitted bin: how deep the object sinks, and the bin's own options."""

    depth_mm: float | None = None
    lip: bool = True
    magnets: bool = False
    screws: bool = False
    # The user's units, or None for the fewest that hold the object.
    units: tuple[int, int] | None = None
    # The user's clearance per side, with its source; None takes the printer's.
    clearance_mm: float | None = None
    clearance_source: str = ""


@dataclass(frozen=True)
class Footprint:
    """The object lying in the bin: its shadow from above (about its centre), its size, and the
    solid that stands for it, its bottom at ``z == 0``."""

    shadow: tuple[Point, ...]
    size_mm: tuple[float, float, float]
    solid: cq.Shape
    name: str
    sha256: str
    kind: str


def capture_footprint(capture: WearableCapture) -> Footprint:
    """A captured object lying face up: its outline, rounded if the capture says so."""

    length, width, height = capture.length_mm, capture.width_mm, capture.thickness_mm
    radius = capture.outline_radius_mm
    points = (
        tuple(board_outline.rounded_rectangle_points(length, width, radius))
        if radius
        else (
            (-length / 2, -width / 2),
            (length / 2, -width / 2),
            (length / 2, width / 2),
            (-length / 2, width / 2),
        )
    )
    solid = outline_prism(points, 0.0, height).val()

    if not isinstance(solid, cq.Shape):
        raise TypeError("Expected a shape")

    return Footprint(
        points, (length, width, height), solid, capture.name, capture.sha256, "capture"
    )


def model_footprint(model: HolderModel) -> Footprint:
    """A modelled object lying as its ``up`` and ``out`` axes put it: its shadow from above."""

    width, depth, height = model.size_mm
    solid = model.shape.moved(cq.Location(cq.Vector(0, -depth / 2, 0)))

    return Footprint(
        tuple(model.shadow.points),
        (width, depth, height),
        solid,
        model.name,
        model.sha256,
        "model",
    )


def fitted_clearance(
    spec: FittedSpec, profile: dict[str, Any], side_shortfall_mm: float | None
) -> tuple[float, str]:
    if spec.clearance_mm is not None:
        return spec.clearance_mm, f"given: {spec.clearance_source}"

    fits, _, _ = printer_numbers(profile)
    sliding = fits["sliding_clearance_per_side"]

    if side_shortfall_mm is None:
        return sliding, "printer profile sliding clearance"

    return (
        max(MINIMUM_CLEARANCE_MM, sliding + side_shortfall_mm),
        (
            "printer profile sliding clearance with a measured side-gap shortfall of "
            f"{side_shortfall_mm:+.3f} mm"
        ),
    )


def fewest_units(object_mm: float, clearance: float, wall: float) -> int:
    """The fewest units across that hold an object with the clearance and a wall each side."""

    gap = GRID_MM - BASE_TOP_MM

    return max(1, math.ceil((object_mm + 2 * (clearance + wall) + gap) / GRID_MM))


def _reach(shadow: tuple[Point, ...]) -> tuple[float, float]:
    xs = [x for x, _ in shadow]
    ys = [y for _, y in shadow]

    return max(abs(min(xs)), abs(max(xs))), max(abs(min(ys)), abs(max(ys)))


def _notches(
    shadow: tuple[Point, ...],
    clearance: float,
    footprint: tuple[float, float],
    wall: float,
) -> list[tuple[float, float, float, float]]:
    """A notch at the middle of each long side of the pocket, cut short where the bin's wall
    leaves less room than the notch's reach; none where it leaves none."""

    reach_x, reach_y = _reach(shadow)
    long_x = reach_x >= reach_y
    edge = (reach_y if long_x else reach_x) + clearance
    limit = (footprint[1] if long_x else footprint[0]) / 2 - wall
    outer = min(edge + FINGER_NOTCH_REACH_MM, limit)

    if outer <= edge + 1.0:
        return []

    half = FINGER_NOTCH_WIDTH_MM / 2
    found = []

    for sign in (-1.0, 1.0):
        lo, hi = sorted((sign * (edge - 1.0), sign * outer))

        if long_x:
            found.append((-half, half, lo, hi))
        else:
            found.append((lo, hi, -half, half))

    return found


def build_fitted_bin(
    item: Footprint,
    spec: FittedSpec,
    profile: dict[str, Any],
    *,
    side_shortfall_mm: float | None = None,
) -> GridfinityPart:
    """A bin with a pocket for the object; refused if the object does not fit the units asked
    for, or the depth is more than the object is tall."""

    minimums = profile.get("minimums_mm", {})
    wall = float(minimums.get("wall", 1.2))
    least_floor = float(minimums.get("floor", 1.2))
    clearance, clearance_from = fitted_clearance(spec, profile, side_shortfall_mm)
    height = item.size_mm[2]
    sink = height if spec.depth_mm is None else spec.depth_mm

    if not 0 < sink <= height:
        raise ValueError(
            f"The object sinks 0 to its {height:.1f} mm height into the pocket, not {sink:g}"
        )

    reach_x, reach_y = _reach(item.shadow)
    fewest = (
        fewest_units(2 * reach_x, clearance, wall),
        fewest_units(2 * reach_y, clearance, wall),
    )
    units = spec.units or fewest

    if units[0] < fewest[0] or units[1] < fewest[1]:
        raise ValueError(
            f"The object needs at least {fewest[0]}x{fewest[1]} units with its clearance and a "
            f"wall round it, not {units[0]}x{units[1]}"
        )

    floor_top = BASE_PROFILE_HEIGHT_MM + least_floor
    height_units = max(2, math.ceil((floor_top + sink) / HEIGHT_UNIT_MM))
    bin_spec = BinSpec(
        units_x=units[0],
        units_y=units[1],
        height_units=height_units,
        lip=spec.lip,
        magnets=spec.magnets,
        screws=spec.screws,
        wall_mm=wall,
    )
    top = bin_spec.height_mm
    pocket_floor = top - sink
    body = bin_block(bin_spec)

    if spec.lip:
        body = body.cut(lip_socket(bin_spec))

    body = body.cut(outline_prism(item.shadow, pocket_floor, top + 10.0, clearance))
    notches = _notches(item.shadow, clearance, bin_spec.footprint_mm, wall)

    for x0, x1, y0, y1 in notches:
        body = body.cut(box(x0, x1, y0, y1, pocket_floor, top + 10.0))

    for cutter in underside_holes(bin_spec, least_floor):
        body = body.cut(cutter)

    placed = item.solid.moved(cq.Location(cq.Vector(0, 0, pocket_floor)))
    proud = height - sink
    note = (
        f"The object stands {proud:.1f} mm above the bin's top: a bin stacked on this one "
        "would rest on the object"
    )
    warnings = (note,) if spec.lip and proud > 0 else ()

    return GridfinityPart(
        warnings=warnings,
        kind="bin",
        body=body,
        checks=_fitted_checks(bin_spec, body, placed, height, notches, pocket_floor),
        settings={
            "units": list(units),
            "seat_height_mm": seat_height_mm(*units),
            "height_units": height_units,
            "height_mm": top,
            "lip": spec.lip,
            "magnets": spec.magnets,
            "screws": spec.screws,
            "wall_mm": wall,
            "fitted": {
                "object": item.name,
                "object_kind": item.kind,
                "object_sha256": item.sha256,
                "object_size_mm": [round(v, 3) for v in item.size_mm],
                "sinks_mm": round(sink, 3),
                "pocket_floor_mm": round(pocket_floor, 3),
                "clearance_per_side_mm": round(clearance, 3),
                "clearance_from": clearance_from,
                "finger_notches": len(notches),
            },
        },
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
    )


def _fitted_checks(
    spec: BinSpec,
    body: cq.Workplane,
    item: cq.Shape,
    height: float,
    notches: list[tuple[float, float, float, float]],
    pocket_floor: float,
) -> dict[str, bool]:
    solid = body.val()
    plate = build_baseplate(BaseplateSpec(spec.units_x, spec.units_y), {}, check=False)
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "base_to_standard": base_to_standard(body, spec),
        "seats_in_baseplate": held(
            body, plate.body, seat_height_mm(spec.units_x, spec.units_y)
        ),
        "object_fits_pocket": clear(solid, item),
        "object_lifts_out": lifts_out(item, solid, height + 10.0),
    }

    if spec.lip:
        corner = (
            -(spec.units_x - 1) * GRID_MM / 2,
            -(spec.units_y - 1) * GRID_MM / 2,
            0.0,
        )
        # Solid below its top, the bin carries a stacked base on that top.
        checks["stacks"] = held(base_unit(corner), body, spec.height_mm)

    if notches:
        checks["finger_notches_open"] = empty_at(
            body,
            [
                ((x0 + x1) / 2, (y0 + y1) / 2, pocket_floor + 0.5)
                for x0, x1, y0, y1 in notches
            ],
        )

    return checks
