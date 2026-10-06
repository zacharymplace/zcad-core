"""Build an object holder: a cup on a back plate, for an object measured by a caliper capture.

The object stands in the cup on its ``down_edge``, its face toward the room or the wall. The pocket
is the object's outline seen from the room, grown by a clearance on every side but the floor it
rests on, and open at the top, so the object lifts straight out. The front and sides climb
``front_mm``, a finger notch is cut down the front's middle, and the object's edge and face
features that a wall would cover are left open by a slot in the floor or a notch down a wall,
each open to the top so nothing overhangs. The back plate stands the object's whole height and
carries two countersunk screw holes or two keyholes, behind the object.

The holder prints as it hangs, floor down, so a hole through the back plate is horizontal: each is
a teardrop, pointed up, and a countersink is a 90-degree cone whose top is 45 degrees from level.

Frame: X along the wall (to the right seen from the room), Y out from the wall, Z up. The back
plate's front face is ``y == 0`` and the floor's top ``z == 0``. Millimetres throughout.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.holder_file import (
    FRONT_SHARE,
    MINIMUM_FRONT_MM,
    HolderSpec,
)
from zcad_core.features.mounts import (
    FEATURE_WALL_MM,
    KEYHOLE_HEAD_DIAMETER_MM,
    KEYHOLE_HEAD_HEIGHT_MM,
    KEYHOLE_SLOT_WIDTH_MM,
    KEYHOLE_TRAVEL_MM,
)
from zcad_core.features.nest_core import clear, lifts_out
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.wearables.capture import WearableCapture

HOLDER_RECORD_SCHEMA_VERSION = "1.0.0"
HOLDER_RECORD = "holder.json"
RECORD_KIND = "holder-build"
NOT_CLAIMED = (
    "The engine states nothing about the load a holder bears, whether its screws hold in a "
    "wall, or how long it lasts; only that the object fits its pocket, lifts straight out, "
    "and that the features it named stay open. A holder is unverified until a printed trial "
    "with the real object has passed."
)
# A finger notch down the front's middle, and the front it needs either side of it.
NOTCH_WIDTH_MM = 20.0
NOTCH_MARGIN_MM = 5.0
# An edge or face feature is left open this far past each of its ends.
FEATURE_MARGIN_MM = 1.0
# A countersink stops this short of the plate's back face.
COUNTERSINK_FLOOR_MM = 1.2
# The narrowest clearance a measured shortfall may bring the fit down to.
MINIMUM_CLEARANCE_MM = 0.05
TOLERANCE_MM3 = 1e-6
Box = tuple[float, float, float, float, float, float]
Point = tuple[float, float]


@dataclass(frozen=True)
class Placed:
    """The object as it stands in the holder: its size along X, Y and Z, and its corners'
    radius seen from the room."""

    width_mm: float
    depth_mm: float
    height_mm: float
    radius_mm: float | None


@dataclass(frozen=True)
class Opening:
    """A feature left open: what it is, where, and the box that must be clear of the holder."""

    identifier: str
    kind: str
    probe: Box

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "kind": self.kind,
            "box_mm": [round(value, 3) for value in self.probe],
        }


@dataclass(frozen=True)
class Fixing:
    """A screw hole or a keyhole in the back plate: its centre seen from the room."""

    kind: str
    x_mm: float
    z_mm: float
    hole_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "centre_mm": [round(self.x_mm, 3), round(self.z_mm, 3)],
            "hole_mm": round(self.hole_mm, 3),
        }


@dataclass(frozen=True)
class Holder:
    """The built holder and what it was built from."""

    spec: HolderSpec
    capture: WearableCapture
    body: cq.Workplane
    placed: Placed
    clearance_mm: float
    clearance_from: str
    front_mm: float
    openings: tuple[Opening, ...]
    fixings: tuple[Fixing, ...]
    notch: bool
    checks: dict[str, bool]
    profile_id: str
    tolerance_status: str

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def size_mm(self) -> tuple[float, float, float]:
        box = self.body.val().BoundingBox()  # type: ignore[union-attr]

        return box.xlen, box.ylen, box.zlen


# --- the object in the holder's frame ----------------------------------------------


def to_holder(capture: WearableCapture, down: str, face: str, point: Point) -> Point:
    """A point of the capture's plan (+X east, +Y north, from its centre) as (X, Z) in the
    holder: X along the wall seen from the room, Z up from the floor's top."""

    u, v = point
    half_l, half_w = capture.length_mm / 2, capture.width_mm / 2
    x, z = {
        "south": (u, v + half_w),
        "north": (-u, half_w - v),
        "west": (-v, u + half_l),
        "east": (v, half_l - u),
    }[down]

    return (-x if face == "wall" else x), z


def placed(capture: WearableCapture, down: str) -> Placed:
    upright = down in ("north", "south")

    return Placed(
        width_mm=capture.length_mm if upright else capture.width_mm,
        depth_mm=capture.thickness_mm,
        height_mm=capture.width_mm if upright else capture.length_mm,
        radius_mm=capture.outline_radius_mm,
    )


def _edge_point(capture: WearableCapture, edge: str, offset: float) -> Point:
    half_l, half_w = capture.length_mm / 2, capture.width_mm / 2

    return {
        "north": (offset, half_w),
        "south": (offset, -half_w),
        "east": (half_l, offset),
        "west": (-half_l, offset),
    }[edge]


_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


# --- solids --------------------------------------------------------------------------


def _xz_prism(points: Sequence[Point], y0: float, y1: float) -> cq.Workplane:
    """A prism of an outline seen from the room, (X, Z) points, between two Y."""

    return (
        cq.Workplane("XY")
        .workplane(offset=-y1)
        .polyline(list(points))
        .close()
        .extrude(y1 - y0)
        .rotate((0, 0, 0), (1, 0, 0), 90)
    )


def _box(
    x0: float, x1: float, y0: float, y1: float, z0: float, z1: float
) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def _outline(
    width: float, height: float, radius: float | None, grow: float
) -> list[Point]:
    """The object's outline seen from the room, grown by ``grow``, standing on ``z == 0``."""

    if radius is None:
        w, h = width + 2 * grow, height + grow
        return [(-w / 2, 0.0), (w / 2, 0.0), (w / 2, h), (-w / 2, h)]

    points = board_outline.rounded_rectangle_points(
        width + 2 * grow, height + 2 * grow, radius + grow
    )

    return [(x, z + height / 2 + grow) for x, z in points]


def _teardrop(cx: float, cz: float, radius: float, steps: int = 24) -> list[Point]:
    """A circle with its top drawn as a 45-degree point, so a horizontal hole prints."""

    points = [(cx, cz + radius * math.sqrt(2.0))]

    for i in range(steps - 5):
        angle = math.radians(45.0 - i * 360.0 / steps)
        points.append((cx + radius * math.cos(angle), cz + radius * math.sin(angle)))

    return points


def _pointed_slot(x: float, z0: float, z1: float, width: float) -> list[Point]:
    """A vertical slot from ``z0`` to ``z1``, its top a 45-degree point."""

    half = width / 2

    return [
        (x - half, z0),
        (x + half, z0),
        (x + half, z1),
        (x, z1 + half),
        (x - half, z1),
    ]


def object_solid(holder_placed: Placed, clearance: float) -> cq.Shape:
    """The object as it stands, its back ``clearance`` off the back plate."""

    p = holder_placed
    solid = _xz_prism(
        _outline(p.width_mm, p.height_mm, p.radius_mm, 0.0),
        clearance,
        clearance + p.depth_mm,
    ).val()

    if not isinstance(solid, cq.Shape):
        raise TypeError("Expected a shape")

    return solid


# --- what the holder must leave open -------------------------------------------------


def _openings(
    capture: WearableCapture,
    spec: HolderSpec,
    p: Placed,
    clearance: float,
    front: float,
) -> tuple[list[Opening], list[str]]:
    """Each feature a wall or the floor would cover, as the box that must stay open; and the
    features nothing can leave open."""

    openings: list[Opening] = []
    problems: list[str] = []
    half = p.width_mm / 2 + clearance
    pocket_y = 2 * clearance + p.depth_mm
    margin = FEATURE_MARGIN_MM

    for feature in capture.edge_features:
        x, z = to_holder(
            capture,
            spec.down_edge,
            spec.face,
            _edge_point(capture, feature.edge, feature.center_offset_mm),
        )
        reach = feature.width_mm / 2 + margin

        if feature.edge == spec.down_edge:
            if 2 * reach >= 2 * half:
                problems.append(
                    f"{feature.identifier} runs the floor's whole width: a slot for it "
                    "would cut the cup in two"
                )
                continue

            openings.append(
                Opening(
                    feature.identifier,
                    "floor_slot",
                    (x - reach, x + reach, 0.0, pocket_y, -spec.floor_mm - 0.5, 0.0),
                )
            )
        elif feature.edge == _OPPOSITE[spec.down_edge] or z - reach >= front:
            continue
        else:
            side = 1.0 if x > 0 else -1.0
            inner, outer = side * half, side * (half + spec.wall_mm)
            openings.append(
                Opening(
                    feature.identifier,
                    "side_notch",
                    (
                        min(inner, outer),
                        max(inner, outer),
                        0.0,
                        pocket_y,
                        max(z - reach, 0.0),
                        front,
                    ),
                )
            )

    for face in capture.face_features:
        if spec.face == "wall":
            problems.append(
                f"{face.identifier} is on the object's face, which faces the wall: the back "
                "plate would cover it; hang the object with its face out"
            )
            continue

        x, z = to_holder(
            capture, spec.down_edge, spec.face, (face.center_x_mm, face.center_y_mm)
        )
        upright = spec.down_edge in ("north", "south")
        across = (face.width_mm if upright else face.depth_mm) / 2 + margin
        up = (face.depth_mm if upright else face.width_mm) / 2 + margin

        if z - up >= front:
            continue

        openings.append(
            Opening(
                face.identifier,
                "front_window",
                (
                    x - across,
                    x + across,
                    pocket_y,
                    pocket_y + spec.wall_mm,
                    max(z - up, 0.0),
                    front,
                ),
            )
        )

    return openings, problems


# --- the fixings ----------------------------------------------------------------------


def _fixing_sites(
    p: Placed, clearance: float, half_width: float, below: float, above: float
) -> list[Point]:
    """Two fixings behind the object: side by side if the pocket is wide enough for two a
    fixing's width apart, else one above the other; each clear of the plate's edges, the
    floor and the plate's top by a feature wall."""

    reach = p.width_mm / 2 + clearance - FEATURE_WALL_MM - half_width
    low = below + FEATURE_WALL_MM
    high = p.height_mm - above - FEATURE_WALL_MM
    spacing = 4 * half_width

    if 2 * reach >= spacing and high >= low:
        z = max(low, min(high, 0.6 * p.height_mm))
        offset = min(reach, 30.0)

        return [(-offset, z), (offset, z)]

    if high - low >= spacing:
        return [(0.0, low), (0.0, low + max(spacing, (high - low) / 2))]

    raise ValueError(
        f"The back plate has no room for two fixings: each needs {2 * half_width:.1f} mm and "
        f"{spacing:.1f} mm between them, behind an object {p.width_mm:.1f} mm wide and "
        f"{p.height_mm:.1f} mm tall"
    )


def _screws(
    spec: HolderSpec, p: Placed, clearance: float, oversize: float
) -> tuple[list[Fixing], list[cq.Workplane]]:
    screw = spec.screw

    if screw is None:
        raise ValueError("A screws mount needs the screw's sizes")

    hole = screw.shank_diameter_mm + oversize
    head = screw.head_diameter_mm + oversize
    depth = (head - hole) / 2

    if depth > spec.back_mm - COUNTERSINK_FLOOR_MM:
        raise ValueError(
            f"A {screw.head_diameter_mm:g} mm head needs a back plate at least "
            f"{depth + COUNTERSINK_FLOOR_MM:.1f} mm thick to sink flush; holder.back_mm is "
            f"{spec.back_mm:g}"
        )

    sites = _fixing_sites(p, clearance, head / 2, head / 2, head * math.sqrt(2.0) / 2)
    cutters = []

    for x, z in sites:
        cutters.append(_xz_prism(_teardrop(x, z, hole / 2), -spec.back_mm - 1.0, 0.5))
        cone = cq.Solid.makeCone(
            head / 2 + 0.01,
            hole / 2,
            depth + 0.01,
            pnt=cq.Vector(x, 0.01, z),
            dir=cq.Vector(0, -1, 0),
        )
        cutters.append(cq.Workplane("XY").add(cone))

    return [Fixing("countersunk_screw", x, z, hole) for x, z in sites], cutters


def _keyholes(
    spec: HolderSpec, p: Placed, clearance: float, oversize: float
) -> tuple[list[Fixing], list[cq.Workplane]]:
    channel = KEYHOLE_HEAD_HEIGHT_MM + 0.5

    if spec.back_mm < channel + FEATURE_WALL_MM:
        raise ValueError(
            f"A keyhole needs a back plate at least {channel + FEATURE_WALL_MM:.1f} mm thick, "
            f"to hide a screw head {KEYHOLE_HEAD_HEIGHT_MM:g} mm proud of the wall; "
            f"holder.back_mm is {spec.back_mm:g}"
        )

    head = KEYHOLE_HEAD_DIAMETER_MM + oversize
    slot = KEYHOLE_SLOT_WIDTH_MM + oversize
    top = KEYHOLE_TRAVEL_MM + head * math.sqrt(2.0) / 2
    sites = _fixing_sites(p, clearance, head / 2, head / 2, top)
    back = -spec.back_mm
    cutters = []

    for x, z in sites:
        cutters.append(_xz_prism(_teardrop(x, z, head / 2), back - 1.0, 0.5))
        cutters.append(
            _xz_prism(_pointed_slot(x, z, z + KEYHOLE_TRAVEL_MM, slot), back - 1.0, 0.5)
        )
        # The screw's head rides up a channel in the plate's back face as it hangs.
        cutters.append(
            _xz_prism(
                _pointed_slot(x, z - head / 2, z + KEYHOLE_TRAVEL_MM, head),
                back - 1.0,
                back + channel,
            )
        )

    return [Fixing("keyhole", x, z, head) for x, z in sites], cutters


# --- the build -------------------------------------------------------------------------


def holder_clearance(
    spec: HolderSpec, profile: dict[str, Any], side_shortfall_mm: float | None
) -> tuple[float, str]:
    """The fit per side and where it came from: the holder file's, else the printer's sliding
    clearance with a measured side-gap shortfall added."""

    if spec.clearance_mm is not None:
        return spec.clearance_mm, f"holder file: {spec.clearance_source}"

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


def front_height(spec: HolderSpec, p: Placed) -> float:
    if spec.front_mm is not None:
        if spec.front_mm > p.height_mm:
            raise ValueError(
                f"holder.front_mm is {spec.front_mm:g}, higher than the object's "
                f"{p.height_mm:.1f} mm: nothing could reach in to lift it out"
            )

        return spec.front_mm

    return min(p.height_mm, max(MINIMUM_FRONT_MM, FRONT_SHARE * p.height_mm))


def build_holder(
    spec: HolderSpec,
    capture: WearableCapture,
    profile: dict[str, Any],
    *,
    side_shortfall_mm: float | None = None,
) -> Holder:
    """The holder for a captured object; refused if a wall or the floor is under the printer's
    minimum, a feature cannot be left open, or the fixings do not fit."""

    fits, least_wall, least_floor = printer_numbers(profile)

    if spec.wall_mm < least_wall:
        raise ValueError(
            f"holder.wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm "
            "minimum wall"
        )

    if spec.floor_mm < least_floor:
        raise ValueError(
            f"holder.floor_mm is {spec.floor_mm:g}, under the printer's {least_floor:g} mm "
            "minimum floor"
        )

    clearance, clearance_from = holder_clearance(spec, profile, side_shortfall_mm)
    p = placed(capture, spec.down_edge)
    front = front_height(spec, p)
    openings, problems = _openings(capture, spec, p, clearance, front)

    if problems:
        raise ValueError("The holder cannot be built:\n- " + "\n- ".join(problems))

    half = p.width_mm / 2 + clearance + spec.wall_mm
    pocket_y = 2 * clearance + p.depth_mm
    body = _box(-half, half, -spec.back_mm, 0.0, -spec.floor_mm, p.height_mm).union(
        _box(-half, half, 0.0, pocket_y + spec.wall_mm, -spec.floor_mm, front)
    )
    pocket = _xz_prism(
        _outline(p.width_mm, p.height_mm, p.radius_mm, clearance), 0.0, pocket_y
    ).union(
        _box(
            -(p.width_mm / 2 + clearance),
            p.width_mm / 2 + clearance,
            0.0,
            pocket_y,
            p.height_mm / 2,
            p.height_mm + 1.0,
        )
    )
    body = body.cut(pocket)
    notch = 2 * (p.width_mm / 2 + clearance) >= NOTCH_WIDTH_MM + 2 * NOTCH_MARGIN_MM

    if notch:
        body = body.cut(
            _box(
                -NOTCH_WIDTH_MM / 2,
                NOTCH_WIDTH_MM / 2,
                pocket_y - 0.5,
                pocket_y + spec.wall_mm + 0.5,
                0.0,
                front + 1.0,
            )
        )

    for opening in openings:
        body = body.cut(_opening_cutter(opening))

    oversize = fits["hole_oversize"]
    fixings, cutters = (
        _screws(spec, p, clearance, oversize)
        if spec.mount == "screws"
        else _keyholes(spec, p, clearance, oversize)
    )

    for cutter in cutters:
        body = body.cut(cutter)

    item = object_solid(p, clearance)
    solid = body.val()
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "object_fits_pocket": clear(solid, item),
        "object_lifts_out": lifts_out(item, solid, p.height_mm),
        "features_open": all(_open(solid, opening.probe) for opening in openings),
        "fixings_open": all(
            _open(solid, _hole_probe(fixing, spec.back_mm)) for fixing in fixings
        ),
    }

    return Holder(
        spec=spec,
        capture=capture,
        body=body,
        placed=p,
        clearance_mm=clearance,
        clearance_from=clearance_from,
        front_mm=front,
        openings=tuple(openings),
        fixings=tuple(fixings),
        notch=notch,
        checks=checks,
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
    )


def _opening_cutter(opening: Opening) -> cq.Workplane:
    """What is cut for an opening: a floor slot through the floor only; a notch down a side
    or the front from the feature to above the wall's top, so it has no roof to overhang."""

    x0, x1, y0, y1, z0, z1 = opening.probe

    if opening.kind == "floor_slot":
        return _box(x0, x1, y0, y1, z0, z1 + 0.01)

    if opening.kind == "side_notch":
        return _box(x0 - 0.5, x1 + 0.5, y0, y1, z0, z1 + 1.0)

    return _box(x0, x1, y0 - 0.5, y1 + 0.5, z0, z1 + 1.0)


def _open(solid: object, probe: Box) -> bool:
    """Whether a box, shrunk a little so it does not graze the faces it is cut to, meets
    nothing of the holder."""

    if not isinstance(solid, cq.Shape):
        raise TypeError("Expected a shape")

    x0, x1, y0, y1, z0, z1 = probe
    inset = 0.05
    box = cq.Solid.makeBox(
        x1 - x0 - 2 * inset,
        y1 - y0 - 2 * inset,
        z1 - z0 - 2 * inset,
        pnt=cq.Vector(x0 + inset, y0 + inset, z0 + inset),
    )

    return intersection_volume(solid, box) <= TOLERANCE_MM3


def _hole_probe(fixing: Fixing, back_mm: float) -> Box:
    """A square inside a fixing's hole, through the back plate."""

    half = fixing.hole_mm / 2 * 0.6

    return (
        fixing.x_mm - half,
        fixing.x_mm + half,
        -back_mm,
        0.0,
        fixing.z_mm - half,
        fixing.z_mm + half,
    )


def require_fits_bed(holder: Holder, profile: dict[str, Any]) -> None:
    """Refuse a holder that will not stand on the printer's bed as it hangs."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, height = holder.size_mm
    bed = (float(volume["x"]), float(volume["y"]), float(volume["z"]))

    if width > bed[0] or depth > bed[1] or height > bed[2]:
        raise ValueError(
            f"The holder is {width:.1f} x {depth:.1f} x {height:.1f} mm standing as it "
            f"hangs, larger than the printer's {bed[0]:g} x {bed[1]:g} x {bed[2]:g} mm"
        )


def print_oriented(holder: Holder) -> cq.Workplane:
    """The holder as it goes on the bed: as it hangs, its floor's underside on the bed."""

    return holder.body.translate((0, 0, holder.spec.floor_mm))


def holder_record(holder: Holder, files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a build says of itself: the object by hash, the settings, what was cut, and that it
    is unverified."""

    spec, capture, p = holder.spec, holder.capture, holder.placed
    width, depth, height = holder.size_mm

    return {
        "schema_version": HOLDER_RECORD_SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "design_name": spec.identifier.lower().replace("_", "-"),
        "holder_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "object": {
            "capture": str(spec.capture_path),
            "sha256": capture.sha256,
            "name": capture.name,
            "size_mm": [capture.length_mm, capture.width_mm, capture.thickness_mm],
            "outline_radius_mm": capture.outline_radius_mm,
            "mass_g": capture.mass_g,
            "mass_source": capture.mass_source or None,
        },
        "settings": {
            "down_edge": spec.down_edge,
            "face": spec.face,
            "front_mm": round(holder.front_mm, 3),
            "wall_mm": spec.wall_mm,
            "floor_mm": spec.floor_mm,
            "back_mm": spec.back_mm,
            "clearance_per_side_mm": round(holder.clearance_mm, 3),
            "clearance_from": holder.clearance_from,
            "mount": spec.mount,
            "screw": (
                None
                if spec.screw is None
                else {
                    "head_diameter_mm": spec.screw.head_diameter_mm,
                    "shank_diameter_mm": spec.screw.shank_diameter_mm,
                    "source": spec.screw.source,
                }
            ),
        },
        "object_in_holder_mm": {
            "width": round(p.width_mm, 3),
            "depth": round(p.depth_mm, 3),
            "height": round(p.height_mm, 3),
        },
        "finger_notch": holder.notch,
        "openings": [opening.to_dict() for opening in holder.openings],
        "fixings": [fixing.to_dict() for fixing in holder.fixings],
        "size_mm": [round(width, 3), round(depth, 3), round(height, 3)],
        "printer_profile_id": holder.profile_id,
        "tolerance_status": holder.tolerance_status,
        "parts": files,
        "fit_checks": holder.checks,
        "verified": False,
        "not_claimed": NOT_CLAIMED,
    }


def write_holder_record(
    holder: Holder, files: dict[str, dict[str, Any]], output_directory: Path
) -> Path:
    """Write ``holder.json``; refuses to replace one."""

    path = output_directory / HOLDER_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(holder_record(holder, files), indent=2, sort_keys=True) + "\n",
        "utf-8",
    )

    return path
