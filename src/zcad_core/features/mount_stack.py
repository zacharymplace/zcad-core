"""The stack mount and the stack top: plates that put an enclosure on the grid and the grid on it.

A stack plate is a flat plate on a stack profile's foot, in whole cells: a cap that
screws to the enclosure's four mount pads instead of sitting loose. The enclosure then
stands on a baseplate, on a bin or a frame of the same cells, or on another stack
plate's lip, like any item built on the profile.

The screws come from below, so each goes up through a foot. A recess in the foot's bottom
sinks the screw's head, and the build refuses a plate where a recess would cut across a
foot's edge: it tries one more cell across or deep, up to two, so the pads fall inside the
feet, and refuses if none does. The plate is centred on the pads.

The recess depth and its margin are the engine's own design choices.

A **stack top** is the other way up: a baseplate, in whole cells that cover the lid, that sits on
a screwed lid's top face and is held by the lid's own screws, made longer. Each screw goes down
through a recess sunk in a pocket's floor, through the plate and the lid, into its insert. Bins,
frames and other enclosures then stand on the enclosure as on any baseplate. The plate's floor
is the screw head's recess and a millimetre of floor under it.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cadquery as cq

from zcad_core.features.mounts import (
    HEAD_DIAMETER_FACTOR,
    MountPads,
    MountPlate,
    _pad_bounds,
    cut_all,
    standard_screw_length,
)
from zcad_core.features.stack_drawers import cap_solid
from zcad_core.features.stack_holding import (
    HOLDING_TOP,
    Holding,
    holding_for,
)
from zcad_core.features.stack_latch import (
    DEFAULT_LEAST_WALL_MM,
    ENGAGEMENT_RANGE_MM,
    SIDES,
    cut_plate_keepers,
    engagement_for,
    plan_latch,
)
from zcad_core.features.stack_profile import StackProfile
from zcad_core.features.stack_solids import (
    baseplate_solid,
    cell_centres,
)
from zcad_core.hardware import FastenerSpec
from zcad_core.hardware.magnets import list_magnets

# A screw's head is about its nominal diameter tall; the recess is a little deeper.
RECESS_EXTRA_MM = 0.5
# The recess leaves at least this much foot above it, and this much round it.
FOOT_ABOVE_RECESS_MM = 1.0
RECESS_WALL_MM = 1.0
# The recess is the head's diameter and this much over.
RECESS_OVER_MM = 0.6
# How many cells past the least the search may add, each way.
MAXIMUM_EXTRA_CELLS = 2


# A stack top's rim round its outermost pockets, the engine's own choice and a baseplate's default.
TOP_RIM_MM = 1.2
# A window over a lid's openings is the opening grown by this much each way, so the plate does not
# narrow the way the air goes; openings closer than OPENING_MERGE_MM are one window, and a lid
# whose openings make more than MAXIMUM_WINDOWS is refused.
WINDOW_MARGIN_MM = 2.0
OPENING_MERGE_MM = 4.0
MAXIMUM_WINDOWS = 4
Rect = tuple[float, float, float, float]
# With windows, the plate may be shifted off the lid's centre, by whole millimetres, as far as it
# still covers the lid, so a window falls on a cell the screws are not in.
OFFSET_STEP_MM = 1.0


def plain_lid(
    centre: tuple[float, float],
    size_mm: tuple[float, float],
    z_mm: float,
    lid_mm: float,
    positions: Sequence[tuple[float, float]],
    hole_mm: float,
) -> cq.Workplane:
    """A lid with nothing in it but its screw holes: the plate of ``size_mm`` centred on
    ``centre``, ``lid_mm`` thick from ``z_mm``."""

    lid = (
        cq.Workplane("XY")
        .box(size_mm[0], size_mm[1], lid_mm, centered=(True, True, False))
        .translate((centre[0], centre[1], z_mm))
    )

    if not positions:
        return lid

    holes = (
        cq.Workplane("XY")
        .pushPoints(list(positions))
        .circle(hole_mm / 2)
        .extrude(lid_mm + 2.0)
        .translate((0.0, 0.0, z_mm - 1.0))
    )

    return lid.cut(holes)


def _merge(rects: list[Rect], gap: float) -> list[Rect]:
    """Rectangles that come within ``gap`` of each other joined into their bounding rectangle,
    until none do."""

    merged = list(rects)
    changed = True

    while changed:
        changed = False

        for i, first in enumerate(merged):
            for j in range(i + 1, len(merged)):
                second = merged[j]

                if (
                    first[0] - gap < second[2]
                    and second[0] - gap < first[2]
                    and first[1] - gap < second[3]
                    and second[1] - gap < first[3]
                ):
                    merged[i] = (
                        min(first[0], second[0]),
                        min(first[1], second[1]),
                        max(first[2], second[2]),
                        max(first[3], second[3]),
                    )
                    del merged[j]
                    changed = True
                    break

            if changed:
                break

    return merged


def lid_openings(
    lid: cq.Workplane, reference: cq.Workplane, z0_mm: float, z1_mm: float
) -> list[Rect]:
    """Where a built lid is open: the footprints of what it has cut away from ``reference``, the
    plain lid, right through its thickness from ``z0_mm`` to ``z1_mm``, joined where they are
    close. A countersink or a pocket is not through, so is not an opening."""

    removed = reference.cut(lid).val()
    rects: list[Rect] = []

    for solid in removed.Solids():  # type: ignore[union-attr]
        box = solid.BoundingBox()

        if box.zmin <= z0_mm + 0.05 and box.zmax >= z1_mm - 0.05:
            rects.append((box.xmin, box.ymin, box.xmax, box.ymax))

    return _merge(rects, OPENING_MERGE_MM)


def vent_cells(
    windows: Sequence[Rect], cells: tuple[int, int], profile: StackProfile
) -> frozenset[int]:
    """The cells a window touches: their pockets' footprints, from the plate's centre."""

    half = profile.cell_top_mm / 2
    touched = set()

    for index, (cx, cy) in enumerate(cell_centres(cells, profile.pitch_mm)):
        for x0, y0, x1, y1 in windows:
            if x0 < cx + half and cx - half < x1 and y0 < cy + half and cy - half < y1:
                touched.add(index)

    return frozenset(touched)


def _offsets(
    cells: tuple[int, int],
    lid_size_mm: tuple[float, float],
    profile: StackProfile,
    shifted: bool,
) -> list[tuple[float, float]]:
    """The shifts of a plate of ``cells`` off the lid's centre to try, the least first: none, and,
    if ``shifted``, every whole millimetre each way that leaves the lid covered."""

    shifts = [(0.0, 0.0)]

    if not shifted:
        return shifts

    slack_x = (cells[0] * profile.pitch_mm + 2 * TOP_RIM_MM - lid_size_mm[0]) / 2
    slack_y = (cells[1] * profile.pitch_mm + 2 * TOP_RIM_MM - lid_size_mm[1]) / 2
    reach_x = int(max(slack_x, 0.0) // OFFSET_STEP_MM)
    reach_y = int(max(slack_y, 0.0) // OFFSET_STEP_MM)
    more = [
        (i * OFFSET_STEP_MM, j * OFFSET_STEP_MM)
        for i in range(-reach_x, reach_x + 1)
        for j in range(-reach_y, reach_y + 1)
        if (i, j) != (0, 0)
    ]

    return shifts + sorted(more, key=lambda s: (math.hypot(*s), s))


def _foot_cell(
    point: tuple[float, float],
    cells: tuple[int, int],
    profile: StackProfile,
    radius: float,
) -> int | None:
    """The cell whose foot's bottom a recess at ``point`` lies inside, if any."""

    room = profile.cell_top_mm / 2 - profile.foot[0][0] - RECESS_WALL_MM - radius

    for index, (cx, cy) in enumerate(cell_centres(cells, profile.pitch_mm)):
        if max(abs(point[0] - cx), abs(point[1] - cy)) <= room:
            return index

    return None


@dataclass(frozen=True)
class TopHolding:
    """How a stack top holds what stands on it: the lip alone, or magnets under each cell's
    pocket floor, and hooks of the item above caught in keepers cut in the pocket walls. A bolt
    needs a hole through what is under the plate, and the lid is closed, so there is none."""

    kind: str = "lip"
    magnet: str = ""
    latch_sides: tuple[str, ...] = ()
    engagement_mm: float | None = None
    clearance_mm: float = 0.2

    @property
    def holds(self) -> bool:
        return self.kind != "lip" or bool(self.latch_sides)


def latch_sides(text: str) -> tuple[str, ...]:
    """The sides in a comma-separated ``stack_top_latch`` such as ``front,back``."""

    return tuple(side.strip() for side in text.split(",") if side.strip())


def check_top_holding(
    kind: str,
    magnet: str | None,
    latch_sides: Sequence[str],
    engagement_mm: float | None,
    stack_top: bool,
) -> None:
    """Refuse holding options that do not go with a stack top or each other."""

    if kind not in HOLDING_TOP:
        raise ValueError(
            f"stack_top_holding must be one of {HOLDING_TOP}: "
            + (
                "a bolt would go through the lid, which is closed"
                if kind == "bolt"
                else f"{kind!r} is not a holding"
            )
        )

    given = (
        kind != "lip"
        or magnet is not None
        or bool(latch_sides)
        or (engagement_mm is not None)
    )

    if given and not stack_top:
        raise ValueError(
            "stack_top_holding, stack_top_magnet, stack_top_latch and "
            "stack_top_engagement_mm are options of a stack top: set stack_top"
        )

    if kind == "magnet" and magnet not in list_magnets():
        raise ValueError(
            f"stack_top_magnet must name a catalogued magnet: {list(list_magnets())}"
        )

    if kind != "magnet" and magnet is not None:
        raise ValueError("stack_top_magnet is for holding by magnets only")

    if not all(side in SIDES for side in latch_sides) or len(set(latch_sides)) != len(
        latch_sides
    ):
        raise ValueError(f"stack_top_latch must be different sides from {SIDES}")

    if engagement_mm is not None:
        low, high = ENGAGEMENT_RANGE_MM

        if not low <= engagement_mm <= high:
            raise ValueError(
                f"stack_top_engagement_mm is {engagement_mm:g}, outside {low:g} to {high:g}"
            )

        if not latch_sides:
            raise ValueError(
                "stack_top_engagement_mm is for a latch: set stack_top_latch"
            )


@dataclass(frozen=True)
class StackTop:
    """A stack top and what the build says of it."""

    plate: cq.Workplane
    cells: tuple[int, int]
    size_mm: tuple[float, float]
    thickness_mm: float
    floor_mm: float
    screw_recess_mm: float
    screw_reach_mm: float
    recommended_screw_mm: int
    stack: dict[str, Any]
    # The cells with a window and no pocket, and the windows, in the enclosure's frame.
    vent_cells: tuple[int, ...] = ()
    windows: tuple[Rect, ...] = ()


def _recess_radius(fastener: FastenerSpec) -> float:
    return (fastener.nominal_diameter_mm * HEAD_DIAMETER_FACTOR + RECESS_OVER_MM) / 2


def recess_depth_mm(fastener: FastenerSpec) -> float:
    """How far up from the foot's bottom a screw's head is sunk."""

    return fastener.nominal_diameter_mm + RECESS_EXTRA_MM


def _inside_a_foot(
    position: tuple[float, float],
    cells: tuple[int, int],
    profile: StackProfile,
    radius: float,
) -> bool:
    """The recess circle lies inside one cell's foot bottom, with the wall round it."""

    room = profile.cell_top_mm / 2 - profile.foot[0][0] - RECESS_WALL_MM - radius

    return any(
        max(abs(position[0] - cx), abs(position[1] - cy)) <= room
        for cx, cy in cell_centres(cells, profile.pitch_mm)
    )


def _cell_options(
    least: tuple[int, int],
) -> list[tuple[int, int]]:
    options = [
        (least[0] + extra_x, least[1] + extra_y)
        for extra_x in range(MAXIMUM_EXTRA_CELLS + 1)
        for extra_y in range(MAXIMUM_EXTRA_CELLS + 1)
    ]

    return sorted(options, key=lambda cells: (cells[0] * cells[1], sum(cells)))


def build_stack_plate(
    pads: MountPads,
    *,
    fastener: FastenerSpec,
    profile: StackProfile,
    plate_mm: float,
    compensation: float,
) -> MountPlate:
    """The plate in the enclosure's frame, its top face on the pads' bottoms."""

    x0, x1, y0, y1 = _pad_bounds(pads)
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    least = (
        math.ceil(((x1 - x0) + profile.gap_mm) / profile.pitch_mm),
        math.ceil(((y1 - y0) + profile.gap_mm) / profile.pitch_mm),
    )
    radius = _recess_radius(fastener)
    recess = recess_depth_mm(fastener)

    if profile.foot_height_mm - recess < FOOT_ABOVE_RECESS_MM:
        raise ValueError(
            f"A {fastener.identifier} head needs a recess {recess:g} mm deep, and the "
            f"profile's foot is {profile.foot_height_mm:g} mm: it would leave "
            f"{profile.foot_height_mm - recess:g} mm, under {FOOT_ABOVE_RECESS_MM:g}"
        )

    for cells in _cell_options(least):
        relative = [(px - centre[0], py - centre[1]) for px, py in pads.positions]

        if all(_inside_a_foot(p, cells, profile, radius) for p in relative):
            return _plate(
                pads, fastener, profile, plate_mm, compensation, cells, centre, recess
            )

    raise ValueError(
        f"No stack plate of {least[0]} to {least[0] + MAXIMUM_EXTRA_CELLS} by "
        f"{least[1]} to {least[1] + MAXIMUM_EXTRA_CELLS} cells puts all four mount "
        f"pads inside a foot with a {fastener.identifier} head's recess: a screw would "
        "land on a foot's edge. Change the wall, the fastener or the profile"
    )


def _plate(
    pads: MountPads,
    fastener: FastenerSpec,
    profile: StackProfile,
    plate_mm: float,
    compensation: float,
    cells: tuple[int, int],
    centre: tuple[float, float],
    recess: float,
) -> MountPlate:
    model, height = cap_solid(profile, cells, plate_mm)
    # The cap's top is the pads' bottoms; its feet hang below.
    model = model.translate((centre[0], centre[1], pads.mating_z_mm - height))
    foot_bottom = pads.mating_z_mm - height
    screw_hole = fastener.clearance_hole_mm + compensation
    radius = _recess_radius(fastener)

    for x, y in pads.positions:
        model = cut_all(
            model,
            cq.Solid.makeCylinder(
                screw_hole / 2,
                height + 2.0,
                pnt=cq.Vector(x, y, foot_bottom - 1.0),
            ),
            cq.Solid.makeCylinder(
                radius, recess + 1.0, pnt=cq.Vector(x, y, foot_bottom - 1.0)
            ),
        )

    reach = (profile.foot_height_mm - recess) + plate_mm + pads.pocket_depth_mm
    width = cells[0] * profile.pitch_mm - profile.gap_mm
    depth = cells[1] * profile.pitch_mm - profile.gap_mm
    stack: dict[str, Any] = {
        "profile": {
            "identifier": profile.identifier,
            "path": str(profile.path),
            "sha256": profile.sha256,
        },
        "cells": list(cells),
        "plate_mm": plate_mm,
        "foot_height_mm": profile.foot_height_mm,
        "holding": "lip",
        "screw_recess_mm": recess,
        "screw_reach_mm": round(reach, 3),
    }

    return MountPlate(
        plate=model,
        thickness_mm=plate_mm,
        recommended_screw_mm=standard_screw_length(reach),
        size_mm=(width, depth),
        attachment=(
            f"stacks on a baseplate, or a bin or frame of {cells[0]} x {cells[1]} cells, "
            f"built to the profile {profile.identifier}"
        ),
        stack=stack,
    )


def require_plate_fits_bed(
    mount: MountPlate | None, volume: Mapping[str, Any] | None
) -> None:
    """Refuse a stack plate larger than the printer's bed, with its cells and the bed's."""

    if mount is None or mount.stack is None or not volume:
        return

    width, depth = mount.size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or turned):
        cells = mount.stack["cells"]

        raise ValueError(
            f"The stack plate is {cells[0]} x {cells[1]} cells, {width:.0f} x "
            f"{depth:.0f} mm; the printer's bed is {volume['x']:.0f} x "
            f"{volume['y']:.0f} mm. A stack plate is whole cells under the "
            "enclosure's footprint: build a narrower enclosure, or shorter units "
            "bolted together"
        )


def _top_magnet(
    holding: TopHolding, profile: StackProfile, floor: float
) -> Holding | None:
    """The magnet a top holds by, or ``None``; refused if the profile has no holding points or the
    plate's floor cannot keep a minimum floor under a pocket."""

    if holding.kind != "magnet":
        return None

    if not profile.holding_points:
        raise ValueError(
            "Holding a stack top by magnets needs holding_points in the profile, and it has none"
        )

    magnet = holding_for("magnet", holding.magnet, "")
    need = magnet.pocket_depth_mm + DEFAULT_LEAST_WALL_MM

    if floor < need:
        raise ValueError(
            f"A {magnet.identifier} pocket is {magnet.pocket_depth_mm:g} mm deep, so the "
            f"plate's floor must be at least {need:g} mm to keep a minimum floor under it; "
            f"it is {floor:g}"
        )

    return magnet


def magnet_points(
    relative: Sequence[tuple[float, float]],
    cells: tuple[int, int],
    profile: StackProfile,
    radius: float,
    magnet: Holding,
    vents: Collection[int] = frozenset(),
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """The holding points that get a magnet pocket, and those that do not: a pocket is left out
    where a screw's recess comes within a wall of it in the same floor. The lid's screws sit in
    the corners, as the grid's holding points do, so on a small lid some of them meet."""

    room = radius + magnet.pocket_diameter_mm / 2 + RECESS_WALL_MM
    kept: list[tuple[float, float]] = []
    skipped: list[tuple[float, float]] = []

    for index, (cx, cy) in enumerate(cell_centres(cells, profile.pitch_mm)):
        if index in vents:
            continue

        for px, py in profile.holding_points:
            mx, my = cx + px, cy + py
            near = any(math.hypot(x - mx, y - my) < room for x, y in relative)
            (skipped if near else kept).append((mx, my))

    return kept, skipped


def _place(
    positions: Sequence[tuple[float, float]],
    centre: tuple[float, float],
    lid_size_mm: tuple[float, float],
    windows: Sequence[Rect],
    least: tuple[int, int],
    profile: StackProfile,
    radius: float,
    fastener: FastenerSpec,
) -> tuple[
    tuple[int, int],
    tuple[float, float],
    list[tuple[float, float]],
    frozenset[int],
]:
    """The least plate that works: its cells, where its middle is, the lid's screws from there,
    and its vent cells. Every screw must be in a cell with no window; with windows the plate may be
    shifted off the lid's centre to get there."""

    for cells in _cell_options(least):
        for shift in _offsets(cells, lid_size_mm, profile, bool(windows)):
            origin = (centre[0] + shift[0], centre[1] + shift[1])
            relative = [(x - origin[0], y - origin[1]) for x, y in positions]
            vents = vent_cells(
                [
                    (x0 - origin[0], y0 - origin[1], x1 - origin[0], y1 - origin[1])
                    for x0, y0, x1, y1 in windows
                ],
                cells,
                profile,
            )
            homes = [_foot_cell(point, cells, profile, radius) for point in relative]

            if len(vents) < cells[0] * cells[1] and all(
                home is not None and home not in vents for home in homes
            ):
                return cells, origin, relative, vents

    raise ValueError(
        f"No stack top of {least[0]} to {least[0] + MAXIMUM_EXTRA_CELLS} by "
        f"{least[1]} to {least[1] + MAXIMUM_EXTRA_CELLS} cells puts every lid screw "
        f"inside a pocket's floor with a {fastener.identifier} head's recess"
        + (", in a cell with no window, " if windows else "")
        + ("even with the plate shifted off the lid's centre: " if windows else ": ")
        + "a screw would land on a ridge"
        + (" or a window" if windows else "")
        + ". Change the wall, the fastener or the profile"
    )


def build_stack_top(
    positions: Sequence[tuple[float, float]],
    *,
    centre: tuple[float, float],
    lid_size_mm: tuple[float, float],
    lid_top_z_mm: float,
    lid_mm: float,
    fastener: FastenerSpec,
    profile: StackProfile,
    compensation: float,
    holding: TopHolding | None = None,
    openings: Sequence[Rect] = (),
) -> StackTop:
    """A baseplate on a lid, in the enclosure's frame: its underside flat on the lid's top face
    at ``lid_top_z_mm``, centred on ``centre``, with a hole and a head recess at each of the lid's
    screws at ``positions``. The cells are the least that cover the lid with every recess inside
    a pocket's floor, searched like the stack plate's."""

    if not positions:
        raise ValueError(
            "A stack top is held by the lid's screws, and this lid has none: the board's "
            "enclosure has no corner bosses to screw it to"
        )

    insert_depth = fastener.heat_set_insert_depth_mm

    if insert_depth is None:
        raise ValueError(
            f"The catalogue has no heat-set insert depth for {fastener.identifier}"
        )

    holding = holding or TopHolding()
    recess = recess_depth_mm(fastener)
    floor = recess + FOOT_ABOVE_RECESS_MM
    radius = _recess_radius(fastener)
    magnet = _top_magnet(holding, profile, floor)
    least = (
        math.ceil(lid_size_mm[0] / profile.pitch_mm),
        math.ceil(lid_size_mm[1] / profile.pitch_mm),
    )
    if len(openings) > MAXIMUM_WINDOWS:
        raise ValueError(
            f"The lid's openings make {len(openings)} separate windows, and a stack top takes "
            f"at most {MAXIMUM_WINDOWS}: its outlets are too scattered for a plate to leave open"
        )

    windows = [
        (
            x0 - WINDOW_MARGIN_MM,
            y0 - WINDOW_MARGIN_MM,
            x1 + WINDOW_MARGIN_MM,
            y1 + WINDOW_MARGIN_MM,
        )
        for x0, y0, x1, y1 in openings
    ]
    cells, origin, relative, vents = _place(
        positions, centre, lid_size_mm, windows, least, profile, radius, fastener
    )

    plate, _ = baseplate_solid(profile, cells, floor, TOP_RIM_MM, vents)
    kept: list[tuple[float, float]] = []
    skipped: list[tuple[float, float]] = []

    if magnet is not None:
        kept, skipped = magnet_points(relative, cells, profile, radius, magnet, vents)

        if not kept:
            raise ValueError(
                f"Every magnet point of a {cells[0]} x {cells[1]} stack top is within a wall "
                f"of a lid screw's recess, so a {magnet.identifier} pocket fits nowhere: use "
                "a smaller magnet or a profile whose holding points are farther in"
            )

        plate = cut_all(
            plate,
            *(
                cq.Solid.makeCylinder(
                    magnet.pocket_diameter_mm / 2,
                    magnet.pocket_depth_mm + 0.5,
                    pnt=cq.Vector(x, y, floor - magnet.pocket_depth_mm),
                )
                for x, y in kept
            ),
        )

    latch_engagement: float | None = None

    if holding.latch_sides:
        engagement = engagement_for(holding.engagement_mm, profile)
        plan, problems = plan_latch(
            profile, engagement, DEFAULT_LEAST_WALL_MM, holding.clearance_mm
        )

        if plan is None:
            raise ValueError(
                "The stack top cannot be built with a latch:\n- "
                + "\n- ".join(problems)
            )

        latch_engagement = engagement
        plate = cut_plate_keepers(
            plate,
            plan,
            [
                cell
                for index, cell in enumerate(cell_centres(cells, profile.pitch_mm))
                if index not in vents
            ],
            holding.latch_sides,
            floor,
        )

    plate = plate.translate((origin[0], origin[1], lid_top_z_mm))
    height = plate.val().BoundingBox().zlen  # type: ignore[union-attr]

    for x0, y0, x1, y1 in windows:
        plate = plate.cut(
            cq.Workplane("XY")
            .box(x1 - x0, y1 - y0, height + 2.0, centered=(False, False, False))
            .translate((x0, y0, lid_top_z_mm - 1.0))
        )

    hole = fastener.clearance_hole_mm + compensation

    for x, y in positions:
        plate = cut_all(
            plate,
            cq.Solid.makeCylinder(
                hole / 2, floor + 2.0, pnt=cq.Vector(x, y, lid_top_z_mm - 1.0)
            ),
            cq.Solid.makeCylinder(
                radius,
                recess + 1.0,
                pnt=cq.Vector(x, y, lid_top_z_mm + floor - recess),
            ),
        )

    box = plate.val().BoundingBox()  # type: ignore[union-attr]
    reach = (floor - recess) + lid_mm + insert_depth
    screw = standard_screw_length(reach)
    stack: dict[str, Any] = {
        "profile": {
            "identifier": profile.identifier,
            "path": str(profile.path),
            "sha256": profile.sha256,
        },
        "cells": list(cells),
        "floor_mm": round(floor, 3),
        "rim_mm": TOP_RIM_MM,
        "thickness_mm": round(box.zlen, 3),
        "holding": holding.kind,
        "magnet": magnet.identifier if magnet else "",
        "pocket_diameter_mm": round(magnet.pocket_diameter_mm, 3) if magnet else None,
        "pocket_depth_mm": round(magnet.pocket_depth_mm, 3) if magnet else None,
        "magnet_points": [[round(x, 3), round(y, 3)] for x, y in kept],
        "magnet_points_left_out": [[round(x, 3), round(y, 3)] for x, y in skipped],
        "latch_sides": list(holding.latch_sides),
        "latch_engagement_mm": latch_engagement,
        "screw_recess_mm": recess,
        "recess_diameter_mm": round(2 * radius, 3),
        "screw_reach_mm": round(reach, 3),
        "recommended_screw_mm": screw,
        "lid_top_z_mm": round(lid_top_z_mm, 3),
        "offset_mm": [
            round(origin[0] - centre[0], 3),
            round(origin[1] - centre[1], 3),
        ],
        "vent_cells": sorted(vents),
        "vent_windows_mm": [[round(v, 3) for v in window] for window in windows],
        "cells_usable": cells[0] * cells[1] - len(vents),
    }

    return StackTop(
        plate=plate,
        cells=cells,
        size_mm=(box.xlen, box.ylen),
        thickness_mm=box.zlen,
        floor_mm=floor,
        screw_recess_mm=recess,
        screw_reach_mm=reach,
        recommended_screw_mm=screw,
        stack=stack,
        vent_cells=tuple(sorted(vents)),
        windows=tuple(windows),
    )


def require_top_fits_bed(
    top: StackTop | None, volume: Mapping[str, Any] | None
) -> None:
    """Refuse a stack top larger than the printer's bed, with its cells and the bed's."""

    if top is None or not volume:
        return

    width, depth = top.size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or turned) or top.thickness_mm > volume["z"]:
        raise ValueError(
            f"The stack top is {top.cells[0]} x {top.cells[1]} cells, {width:.0f} x "
            f"{depth:.0f} x {top.thickness_mm:.0f} mm; the printer's bed is "
            f"{volume['x']:.0f} x {volume['y']:.0f} x {volume['z']:.0f} mm. A stack top is "
            "whole cells over the lid: build a smaller enclosure"
        )
