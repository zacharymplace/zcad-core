"""Mount pads under an enclosure's floor, and the plates that bolt to them.

An enclosure built with a mount gets four pads under its floor, one at each
corner of its footprint, each with a heat-set insert pocket opening on the
pad's bottom face. A mount plate screws to them with the enclosure's
fastener, so the plate never touches the inside of the enclosure. The pads
stand off the floor far enough for an insert, and so for a wall screw's head
to sit between the plate and the floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cadquery as cq

from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import FastenerSpec, get_fastener

MOUNTS = ("keyhole", "vesa75", "vesa100", "din")

# Floor left above an insert pocket, so the pocket never breaks into the cavity.
POCKET_ROOF_MM = 1.0
# The least room between the floor and the plate, for a wall screw's head.
MINIMUM_PAD_HEIGHT_MM = 3.5
# A pad sinks this far into the floor so it fuses to it.
PAD_EMBED_MM = 0.5
# Plate edge beyond the pads' outer faces, and the wall between a keyhole and
# a screw hole.
_PLATE_MARGIN_MM = 2.0
FEATURE_WALL_MM = 2.0
# Keyhole: a #6 wall screw's head passes the large hole; its shank slides up
# the slot. The plate hangs with the slot's open end toward -Y.
KEYHOLE_HEAD_DIAMETER_MM = 9.0
KEYHOLE_SLOT_WIDTH_MM = 4.5
KEYHOLE_TRAVEL_MM = 10.0
KEYHOLE_HEAD_HEIGHT_MM = 3.0
# VESA MIS-D: a square pattern of M4 threaded holes in the device. The plate
# carries the screws' clearance holes, and their heads sit on the plate's
# enclosure side, in the gap under the floor.
VESA_PATTERNS_MM = {"vesa75": 75.0, "vesa100": 100.0}
VESA_SCREW = "M4"
VESA_HEAD_DIAMETER_MM = 8.0
VESA_HEAD_HEIGHT_MM = 3.1
# How far a VESA screw should reach into the device, past the plate.
VESA_ENGAGEMENT_MM = 10.0
# DIN rail TS35: 35 mm wide, flanges 1.0 to 1.5 mm thick and 4 mm wide (a
# 27 mm web between them), 7.5 or 15 mm deep. The plate's outer face sits on
# the flanges; a hook on each side reaches under a flange. The fixed hook is
# toward +Y and the latch toward -Y, so the enclosure hangs with +Y up on a
# horizontal rail, which runs along X.
DIN_RAIL_WIDTH_MM = 35.0
DIN_FLANGE_WIDTH_MM = 4.0
DIN_FLANGE_THICKNESS_MM = 1.5
# Room between a flange's edge and a hook's wall, and between the flange and
# the lip that grips it.
_DIN_EDGE_CLEARANCE_MM = 0.3
_DIN_GRIP_CLEARANCE_MM = 0.2
_DIN_LIP_WIDTH_MM = 2.5
_DIN_LIP_THICKNESS_MM = 2.0
_DIN_WALL_MM = 2.0
_DIN_FIXED_HOOK_WIDTH_MM = 20.0
_DIN_LATCH_HOOK_WIDTH_MM = 8.0
# The latch is a tongue cut from the plate, bending in the plate's plane so
# its stress runs along the printed layers. Its free end swings clear of the
# flange by the lip's width, plus this margin.
FLEXURE_THICKNESS_MM = 1.6
_DIN_SWING_MARGIN_MM = 0.3
# A design strain limit for a printed PETG tongue, well under the material's
# yield; provisional until a print trial measures it.
FLEXURE_STRAIN_LIMIT = 0.015
_DIN_INNER_SLIT_MM = 0.8
_DIN_END_SLIT_MM = 1.0
_DIN_ROOT_MM = 3.0
_COUNTERSINK_FLOOR_MM = 1.2
_SCREW_LENGTHS_MM = (4, 5, 6, 8, 10, 12, 16, 20)
HEAD_DIAMETER_FACTOR = 2.0
_INTERFERENCE_TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class MountPads:
    """Where the pads are and how they are built."""

    positions: tuple[tuple[float, float], ...]
    diameter_mm: float
    height_mm: float
    floor_underside_z_mm: float
    pocket_diameter_mm: float
    pocket_depth_mm: float

    @property
    def mating_z_mm(self) -> float:
        """The pads' bottom faces, where a plate sits."""
        return self.floor_underside_z_mm - self.height_mm


@dataclass(frozen=True)
class Flexure:
    """A cantilever tongue: its size, how far its tip swings, and the strain
    at its root, as a fraction (0.015 is 1.5 %)."""

    thickness_mm: float
    length_mm: float
    deflection_mm: float
    strain: float
    strain_limit: float


@dataclass(frozen=True)
class MountPlate:
    """A built plate and the screws that hold it on."""

    plate: cq.Workplane
    thickness_mm: float
    recommended_screw_mm: int
    size_mm: tuple[float, float]
    # The screws that hold the plate to what it mounts on, when the plate
    # has them (a VESA plate's M4 screws); a keyhole plate's are the wall's.
    device_screws: str | None = None
    # How the plate attaches to a rail, and the printed spring that latches it.
    attachment: str | None = None
    flexure: Flexure | None = None
    # A mount that is several printable pieces, such as a pair of rack ears,
    # names each; ``plate`` is then the first. Otherwise the plate is the
    # one part, "mount".
    pieces: dict[str, cq.Workplane] | None = None

    @property
    def parts(self) -> dict[str, cq.Workplane]:
        """Every printable piece of the mount, by part name."""

        return self.pieces if self.pieces is not None else {"mount": self.plate}


def pad_height_mm(fastener: FastenerSpec, floor_mm: float) -> float:
    """The pad height that leaves ``POCKET_ROOF_MM`` of floor over the pocket."""
    depth = insert_dimensions(fastener)[1]

    return max(depth + POCKET_ROOF_MM - floor_mm, MINIMUM_PAD_HEIGHT_MM)


def mount_pads(
    *,
    x_span_mm: tuple[float, float],
    y_span_mm: tuple[float, float],
    floor_underside_z_mm: float,
    floor_mm: float,
    wall_mm: float,
    fastener: FastenerSpec,
    hole_compensation_mm: float = 0.0,
) -> MountPads:
    """Pads at the corners of the outer footprint, each inset by the wall
    thickness plus its radius, so the pad sits under the wall's inner face."""

    insert_diameter, depth = insert_dimensions(fastener)
    pocket = insert_diameter + hole_compensation_mm
    diameter = insert_diameter + 2 * 1.8
    inset = wall_mm + diameter / 2
    x0, x1 = sorted(x_span_mm)
    y0, y1 = sorted(y_span_mm)

    if x1 - x0 - 2 * inset < diameter or y1 - y0 - 2 * inset < diameter:
        raise ValueError(
            f"The {x1 - x0:.1f} x {y1 - y0:.1f} mm footprint is too small for "
            "four mount pads"
        )

    return MountPads(
        positions=(
            (x0 + inset, y0 + inset),
            (x1 - inset, y0 + inset),
            (x1 - inset, y1 - inset),
            (x0 + inset, y1 - inset),
        ),
        diameter_mm=diameter,
        height_mm=pad_height_mm(fastener, floor_mm),
        floor_underside_z_mm=floor_underside_z_mm,
        pocket_diameter_mm=pocket,
        pocket_depth_mm=depth,
    )


def add_mount_pads(base: cq.Workplane, pads: MountPads) -> cq.Workplane:
    """Fuse the pads to the floor's underside and cut their insert pockets."""

    for x, y in pads.positions:
        pad = cq.Workplane("XY").add(
            cq.Solid.makeCylinder(
                pads.diameter_mm / 2,
                pads.height_mm + PAD_EMBED_MM,
                pnt=cq.Vector(x, y, pads.mating_z_mm),
            )
        )
        base = base.union(pad)

    for x, y in pads.positions:
        # The pocket starts below the pad so its mouth is cut clean.
        pocket = cq.Workplane("XY").add(
            cq.Solid.makeCylinder(
                pads.pocket_diameter_mm / 2,
                pads.pocket_depth_mm + 1.0,
                pnt=cq.Vector(x, y, pads.mating_z_mm - 1.0),
            )
        )
        base = base.cut(pocket)

    return base


def build_mount(
    kind: str,
    pads: MountPads,
    *,
    fastener: FastenerSpec,
    plate_mm: float = 4.0,
    hole_compensation_mm: float = 0.0,
) -> MountPlate:
    """The plate for ``kind``, in the enclosure's frame, seated on the pads."""

    if kind not in MOUNTS:
        raise ValueError(f"mount must be one of {MOUNTS}")

    if kind in VESA_PATTERNS_MM:
        return _vesa_plate(
            kind,
            pads,
            fastener=fastener,
            plate_mm=plate_mm,
            compensation=hole_compensation_mm,
        )

    if kind == "din":
        return _din_plate(
            pads,
            fastener=fastener,
            plate_mm=plate_mm,
            compensation=hole_compensation_mm,
        )

    return _keyhole_plate(
        pads, fastener=fastener, plate_mm=plate_mm, compensation=hole_compensation_mm
    )


def require_mount_clear(base: cq.Workplane, mount: MountPlate) -> None:
    """Refuse a plate that shares volume with the base; it may only touch the
    pads' bottom faces."""

    for name, piece in mount.parts.items():
        overlap = intersection_volume(_solids(base), _solids(piece))

        if overlap > _INTERFERENCE_TOLERANCE_MM3:
            raise ValueError(
                f"The {name} part intersects the base by {overlap:.3f} mm3"
            )


def _solids(model: cq.Workplane) -> cq.Shape:
    return cq.Compound.makeCompound(
        [
            solid
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for solid in item.Solids()
        ]
    )


def countersink_depth(fastener: FastenerSpec, plate_mm: float) -> float:
    head = fastener.nominal_diameter_mm * HEAD_DIAMETER_FACTOR
    depth = (head - fastener.clearance_hole_mm) / 2

    if depth > plate_mm - _COUNTERSINK_FLOOR_MM:
        raise ValueError(
            f"A countersunk {fastener.identifier} head needs a plate at least "
            f"{depth + _COUNTERSINK_FLOOR_MM:.1f} mm thick"
        )

    return depth


def _pad_bounds(pads: MountPads) -> tuple[float, float, float, float]:
    reach = pads.diameter_mm / 2 + _PLATE_MARGIN_MM
    xs = [x for x, _ in pads.positions]
    ys = [y for _, y in pads.positions]

    return min(xs) - reach, max(xs) + reach, min(ys) - reach, max(ys) + reach


def _seat_plate(
    pads: MountPads,
    bounds: tuple[float, float, float, float],
    *,
    fastener: FastenerSpec,
    plate_mm: float,
    compensation: float,
) -> tuple[cq.Workplane, float]:
    """A blank of ``bounds`` seated on the pads, with the pads' screw holes
    cut and countersunk on its outer face; also the plate's bottom z."""

    head = fastener.nominal_diameter_mm * HEAD_DIAMETER_FACTOR
    cone_depth = countersink_depth(fastener, plate_mm)
    x0, x1, y0, y1 = bounds
    bottom = pads.mating_z_mm - plate_mm
    plate = (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, plate_mm, centered=False)
        .translate((x0, y0, bottom))
    )
    screw_hole = fastener.clearance_hole_mm + compensation

    for x, y in pads.positions:
        plate = cut_all(
            plate,
            cq.Solid.makeCylinder(
                screw_hole / 2, plate_mm + 2.0, pnt=cq.Vector(x, y, bottom - 1.0)
            ),
            # The cone opens on the plate's outer face, to sink a flat head
            # flush.
            cq.Solid.makeCone(
                head / 2 + 0.01,
                screw_hole / 2,
                cone_depth + 0.01,
                pnt=cq.Vector(x, y, bottom - 0.01),
            ),
        )

    return plate, bottom


def cut_all(plate: cq.Workplane, *cutters: cq.Shape) -> cq.Workplane:
    for cutter in cutters:
        plate = plate.cut(cq.Workplane("XY").add(cutter))

    return plate


def _keyhole_plate(
    pads: MountPads,
    *,
    fastener: FastenerSpec,
    plate_mm: float,
    compensation: float,
) -> MountPlate:
    if pads.height_mm < KEYHOLE_HEAD_HEIGHT_MM + 0.5:
        raise ValueError("The pads are too short for a wall screw's head")

    bounds = _pad_bounds(pads)
    plate, bottom = _seat_plate(
        pads,
        bounds,
        fastener=fastener,
        plate_mm=plate_mm,
        compensation=compensation,
    )
    head = fastener.nominal_diameter_mm * HEAD_DIAMETER_FACTOR

    for x, y in _keyhole_positions(pads, bounds, head):
        plate = cut_all(plate, *_keyhole_cutters(x, y, bottom, plate_mm, compensation))

    x0, x1, y0, y1 = bounds

    return MountPlate(
        plate=plate,
        thickness_mm=plate_mm,
        recommended_screw_mm=standard_screw_length(plate_mm + pads.pocket_depth_mm),
        size_mm=(x1 - x0, y1 - y0),
    )


def _vesa_plate(
    kind: str,
    pads: MountPads,
    *,
    fastener: FastenerSpec,
    plate_mm: float,
    compensation: float,
) -> MountPlate:
    """A plate with a VESA MIS-D hole pattern centred on the pads.

    The plate grows to cover the pattern, so it can be larger than the
    enclosure. The M4 screws go through it from the enclosure side, their
    heads in the gap under the floor, so the heads must clear the pads.
    """

    if pads.height_mm < VESA_HEAD_HEIGHT_MM + 0.5:
        raise ValueError("The pads are too short for a VESA screw's head")

    spacing = VESA_PATTERNS_MM[kind]
    screw = get_fastener(VESA_SCREW)
    xs = [x for x, _ in pads.positions]
    ys = [y for _, y in pads.positions]
    center_x = (min(xs) + max(xs)) / 2
    center_y = (min(ys) + max(ys)) / 2
    half = spacing / 2
    holes = tuple(
        (center_x + dx * half, center_y + dy * half)
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    )
    head_radius = VESA_HEAD_DIAMETER_MM / 2

    for hx, hy in holes:
        for px, py in pads.positions:
            gap = math.hypot(hx - px, hy - py) - head_radius - pads.diameter_mm / 2

            if gap < FEATURE_WALL_MM:
                raise ValueError(
                    f"A {VESA_SCREW} screw head on the {spacing:.0f} mm pattern "
                    f"leaves {max(gap, 0.0):.1f} mm to a mount pad, and "
                    f"{FEATURE_WALL_MM:.0f} mm is needed; use a larger "
                    "pattern or a smaller enclosure"
                )

    pad_x0, pad_x1, pad_y0, pad_y1 = _pad_bounds(pads)
    edge = head_radius + _PLATE_MARGIN_MM
    bounds = (
        min(pad_x0, center_x - half - edge),
        max(pad_x1, center_x + half + edge),
        min(pad_y0, center_y - half - edge),
        max(pad_y1, center_y + half + edge),
    )
    plate, bottom = _seat_plate(
        pads,
        bounds,
        fastener=fastener,
        plate_mm=plate_mm,
        compensation=compensation,
    )
    hole = screw.clearance_hole_mm + compensation

    for hx, hy in holes:
        plate = cut_all(
            plate,
            cq.Solid.makeCylinder(
                hole / 2, plate_mm + 2.0, pnt=cq.Vector(hx, hy, bottom - 1.0)
            ),
        )

    device_screw = standard_screw_length(plate_mm + VESA_ENGAGEMENT_MM)
    x0, x1, y0, y1 = bounds

    return MountPlate(
        plate=plate,
        thickness_mm=plate_mm,
        recommended_screw_mm=standard_screw_length(plate_mm + pads.pocket_depth_mm),
        size_mm=(x1 - x0, y1 - y0),
        device_screws=(
            f"{screw.identifier} x {device_screw} mm, 4 on a "
            f"{spacing:.0f} x {spacing:.0f} mm pattern"
        ),
    )


def flexure_for(deflection_mm: float, reach_mm: float) -> Flexure:
    """The tongue for a deflection at a load point ``reach_mm`` from its root,
    with the strain an end-loaded cantilever sees: 3 t d / (2 L^2)."""

    strain = 3 * FLEXURE_THICKNESS_MM * deflection_mm / (2 * reach_mm**2)

    return Flexure(
        thickness_mm=FLEXURE_THICKNESS_MM,
        length_mm=reach_mm,
        deflection_mm=deflection_mm,
        strain=strain,
        strain_limit=FLEXURE_STRAIN_LIMIT,
    )


def flexure_payload(flexure: Flexure | None) -> dict[str, float] | None:
    """A flexure as the build output reports it."""

    if flexure is None:
        return None

    return {
        "thickness_mm": flexure.thickness_mm,
        "length_mm": flexure.length_mm,
        "deflection_mm": flexure.deflection_mm,
        "strain_percent": round(100 * flexure.strain, 2),
        "strain_limit_percent": round(100 * flexure.strain_limit, 2),
    }


def _hook(
    x_span: tuple[float, float],
    wall_y: tuple[float, float],
    lip_y: tuple[float, float],
    *,
    bottom: float,
) -> cq.Workplane:
    """A wall standing off the plate's outer face, with a lip at its far end
    that turns toward the rail to reach under a flange."""

    reach_z = DIN_FLANGE_THICKNESS_MM + _DIN_GRIP_CLEARANCE_MM + _DIN_LIP_THICKNESS_MM
    x0, x1 = x_span
    # The wall runs 0.5 mm into the plate so the two fuse.
    wall = cq.Solid.makeBox(
        x1 - x0,
        wall_y[1] - wall_y[0],
        reach_z + 0.5,
        pnt=cq.Vector(x0, wall_y[0], bottom - reach_z),
    )
    lip = cq.Solid.makeBox(
        x1 - x0,
        lip_y[1] - lip_y[0],
        _DIN_LIP_THICKNESS_MM,
        pnt=cq.Vector(x0, lip_y[0], bottom - reach_z),
    )

    return cq.Workplane("XY").add(wall).union(cq.Workplane("XY").add(lip))


def _din_plate(
    pads: MountPads,
    *,
    fastener: FastenerSpec,
    plate_mm: float,
    compensation: float,
) -> MountPlate:
    """A plate that clips onto a 35 mm DIN rail: a fixed hook at +Y and a
    latch at -Y whose tongue is cut from the plate.

    Print it enclosure face down, hooks up: the tongue then bends in the
    layer plane, and each lip overhangs by 2.5 mm, inside the manufacturing
    limit for unsupported overhang.
    """

    if plate_mm < FLEXURE_THICKNESS_MM + 1.0:
        raise ValueError("The plate is too thin to carry a latch tongue")

    xs = [x for x, _ in pads.positions]
    ys = [y for _, y in pads.positions]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    half = DIN_RAIL_WIDTH_MM / 2 + _DIN_EDGE_CLEARANCE_MM
    t = FLEXURE_THICKNESS_MM
    swing = _DIN_LIP_WIDTH_MM + _DIN_SWING_MARGIN_MM
    outer_slit = swing + 0.5 + compensation
    inner_slit = _DIN_INNER_SLIT_MM + compensation
    end_slit = _DIN_END_SLIT_MM + compensation

    # The shortest tongue that keeps the strain within its limit, measured to
    # the latch hook's centre, where the flange pushes.
    reach = math.ceil(math.sqrt(3 * t * swing / (2 * FLEXURE_STRAIN_LIMIT)))
    length = reach + _DIN_LATCH_HOOK_WIDTH_MM / 2 + 1.0
    flexure = flexure_for(swing, reach)

    if flexure.strain > FLEXURE_STRAIN_LIMIT:
        raise ValueError("The latch tongue would strain past its limit")

    # The tongue runs from its free end to its root; plate lies past both.
    x_free = cx - length / 2
    x_root = cx + length / 2
    latch_inner = cy - half
    tongue_low = latch_inner - t
    slot_low = tongue_low - outer_slit
    hook_inner = cy + half
    fixed_high = hook_inner + _DIN_WALL_MM

    pad_x0, pad_x1, pad_y0, pad_y1 = _pad_bounds(pads)
    bounds = (
        min(pad_x0, x_free - end_slit - _PLATE_MARGIN_MM),
        max(pad_x1, x_root + _DIN_ROOT_MM),
        min(pad_y0, slot_low - _PLATE_MARGIN_MM),
        max(pad_y1, fixed_high + _PLATE_MARGIN_MM),
    )
    plate, bottom = _seat_plate(
        pads,
        bounds,
        fastener=fastener,
        plate_mm=plate_mm,
        compensation=compensation,
    )

    slot_x0 = x_free - end_slit
    slot = (slot_x0, x_root, slot_low, latch_inner + inner_slit)
    head = fastener.nominal_diameter_mm * HEAD_DIAMETER_FACTOR

    for px, py in pads.positions:
        if gap_to_rectangle(px, py, *slot) < head / 2 + FEATURE_WALL_MM:
            raise ValueError(
                "The latch slot would come within 2 mm of a screw hole; the "
                "plate is too small for a DIN clip"
            )

    z0 = bottom - 1.0
    depth = plate_mm + 2.0
    # The tongue is what a U-shaped slot leaves standing.
    plate = cut_all(
        plate,
        cq.Solid.makeBox(
            x_root - slot_x0, outer_slit, depth, pnt=cq.Vector(slot_x0, slot_low, z0)
        ),
        cq.Solid.makeBox(
            x_root - slot_x0,
            inner_slit,
            depth,
            pnt=cq.Vector(slot_x0, latch_inner, z0),
        ),
        cq.Solid.makeBox(end_slit, t, depth, pnt=cq.Vector(slot_x0, tongue_low, z0)),
    )
    fixed = _DIN_FIXED_HOOK_WIDTH_MM
    plate = plate.union(
        _hook(
            (cx - fixed / 2, cx + fixed / 2),
            (hook_inner, fixed_high),
            (hook_inner - _DIN_LIP_WIDTH_MM, hook_inner),
            bottom=bottom,
        )
    ).union(
        _hook(
            (x_free, x_free + _DIN_LATCH_HOOK_WIDTH_MM),
            (tongue_low, latch_inner),
            (latch_inner, latch_inner + _DIN_LIP_WIDTH_MM),
            bottom=bottom,
        )
    )
    x0, x1, y0, y1 = bounds

    return MountPlate(
        plate=plate,
        thickness_mm=plate_mm,
        recommended_screw_mm=standard_screw_length(plate_mm + pads.pocket_depth_mm),
        size_mm=(x1 - x0, y1 - y0),
        attachment=(
            "35 mm DIN rail (TS35): hook the +Y edge over the top flange, press "
            "the -Y edge on until the latch clicks; release with a flat "
            "screwdriver in the latch slot"
        ),
        flexure=flexure,
    )


def _keyhole_positions(
    pads: MountPads,
    plate: tuple[float, float, float, float],
    screw_head_mm: float,
) -> tuple[tuple[float, float], ...]:
    """Two keyholes on the plate's centreline, clear of the pads' screw holes
    and the plate's edges.

    Each is a large hole with its slot running toward -Y, so the plate hangs
    with +Y up and slides down onto the wall screws.
    """

    x0, x1, y0, y1 = plate
    center_x = (x0 + x1) / 2
    center_y = (y0 + y1) / 2
    xs = [x for x, _ in pads.positions]
    radius = KEYHOLE_HEAD_DIAMETER_MM / 2
    below = KEYHOLE_TRAVEL_MM + KEYHOLE_SLOT_WIDTH_MM / 2
    offset = min((max(xs) - min(xs)) / 2, 40.0) * 0.6
    y = center_y - (radius - below) / 2
    wall = FEATURE_WALL_MM

    for x in (center_x - offset, center_x + offset):
        left, right, low, high = x - radius, x + radius, y - below, y + radius

        inside = (
            left >= x0 + wall
            and right <= x1 - wall
            and low >= y0 + wall
            and high <= y1 - wall
        )
        clear = all(
            gap_to_rectangle(px, py, left, right, low, high) >= screw_head_mm / 2 + wall
            for px, py in pads.positions
        )

        if not (inside and clear):
            raise ValueError(
                "The plate has no room for a keyhole clear of its screw holes "
                "and edges; the enclosure is too small to hang"
            )

    return ((center_x - offset, y), (center_x + offset, y))


def gap_to_rectangle(
    px: float, py: float, left: float, right: float, low: float, high: float
) -> float:
    """Distance from a point to a rectangle; zero inside it."""

    return math.hypot(max(left - px, 0.0, px - right), max(low - py, 0.0, py - high))


def _keyhole_cutters(
    x: float, y: float, bottom: float, plate_mm: float, compensation: float
) -> list[cq.Shape]:
    head = KEYHOLE_HEAD_DIAMETER_MM + compensation
    slot = KEYHOLE_SLOT_WIDTH_MM + compensation
    length = KEYHOLE_TRAVEL_MM
    height = plate_mm + 2.0
    z = bottom - 1.0

    return [
        cq.Solid.makeCylinder(head / 2, height, pnt=cq.Vector(x, y, z)),
        cq.Solid.makeBox(
            slot, length, height, pnt=cq.Vector(x - slot / 2, y - length, z)
        ),
        cq.Solid.makeCylinder(slot / 2, height, pnt=cq.Vector(x, y - length, z)),
    ]


def insert_dimensions(fastener: FastenerSpec) -> tuple[float, float]:
    diameter = fastener.heat_set_insert_diameter_mm
    depth = fastener.heat_set_insert_depth_mm

    if diameter is None or depth is None:
        raise ValueError(
            f"Fastener {fastener.identifier} has no heat-set insert dimensions"
        )

    return diameter, depth


def standard_screw_length(reach_mm: float) -> int:
    fitting = [length for length in _SCREW_LENGTHS_MM if length <= reach_mm]

    if not fitting:
        raise ValueError(f"No standard screw is short enough for {reach_mm:.1f} mm")

    return fitting[-1]
