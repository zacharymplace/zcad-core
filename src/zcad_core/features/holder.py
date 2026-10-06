"""Build an object holder: a cup on a back plate, for an object measured by a caliper capture
or given as a STEP model.

The object stands in the cup on its ``down_edge``, its face toward the room or the wall. The pocket
is the object's outline seen from the room, grown by a clearance on every side but the floor it
rests on, and open at the top, so the object lifts straight out. The front and sides climb
``front_mm``, a finger notch is cut down the front's middle, and the object's edge and face
features that a wall would cover are left open by a slot in the floor or a notch down a wall,
each open to the top so nothing overhangs. The back plate stands the object's whole height and
carries the mount (:mod:`zcad_core.features.holder_mounts`). Retaining tabs, if asked for, are cut
from the side walls (:mod:`zcad_core.features.holder_tabs`), and the sides then climb the
object's whole height.

The holder prints as it hangs, floor down, so a hole through the back plate is horizontal: each is
a teardrop, pointed up, and a countersink is a 90-degree cone whose top is 45 degrees from level.

Frame: X along the wall (to the right seen from the room), Y out from the wall, Z up. The back
plate's front face is ``y == 0`` and the floor's top ``z == 0``. Millimetres throughout.
"""

from __future__ import annotations

import json
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
from zcad_core.features.holder_model import HolderModel
from zcad_core.features.holder_mounts import (
    Fixing,
    MountPlan,
    pegs_on_pitch,
    plan_mount,
)
from zcad_core.features.holder_shapes import (
    Box,
    Placed,
    Point,
    box,
    object_solid,
    outline,
    xz_prism,
)
from zcad_core.features.holder_tabs import (
    HolderTab,
    hooks_over_object,
    plan_tabs,
    tab_solids,
)
from zcad_core.features.holder_trial import holder_checks
from zcad_core.features.nest_core import clear, lifts_out
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.hardware.wearables.capture import WearableCapture

HOLDER_RECORD_SCHEMA_VERSION = "1.3.0"
HOLDER_RECORD = "holder.json"
RECORD_KIND = "holder-build"
NOT_CLAIMED = (
    "The engine states nothing about the load a holder bears, whether its screws hold in a "
    "wall, what a pegboard or an adhesive pad takes, or how long it lasts; only that the "
    "object fits its pocket, lifts straight out, and that the features it named stay open. A "
    "holder is unverified until a printed trial with the real object has passed."
)
# A finger notch down the front's middle, and the front it needs either side of it.
NOTCH_WIDTH_MM = 20.0
NOTCH_MARGIN_MM = 5.0
# An edge or face feature is left open this far past each of its ends.
FEATURE_MARGIN_MM = 1.0
# The narrowest clearance a measured shortfall may bring the fit down to.
MINIMUM_CLEARANCE_MM = 0.05
TOLERANCE_MM3 = 1e-6


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
class Holder:
    """The built holder and what it was built from."""

    spec: HolderSpec
    # The object: its capture, or its model turned to hang.
    item: WearableCapture | HolderModel
    body: cq.Workplane
    placed: Placed
    clearance_mm: float
    clearance_from: str
    front_mm: float
    openings: tuple[Opening, ...]
    mount: MountPlan
    notch: bool
    checks: dict[str, bool]
    profile_id: str
    tolerance_status: str
    tabs: tuple[HolderTab, ...] = ()

    @property
    def fixings(self) -> tuple[Fixing, ...]:
        return self.mount.fixings

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def size_mm(self) -> tuple[float, float, float]:
        bounds = self.body.val().BoundingBox()  # type: ignore[union-attr]

        return bounds.xlen, bounds.ylen, bounds.zlen


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


# --- what the holder must leave open -------------------------------------------------


def _openings(
    capture: WearableCapture,
    spec: HolderSpec,
    p: Placed,
    clearance: float,
    front: float,
    side_top: float,
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
        elif feature.edge == _OPPOSITE[spec.down_edge] or z - reach >= side_top:
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
                        side_top,
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


def _cup(
    spec: HolderSpec,
    p: Placed,
    clearance: float,
    front: float,
    side_top: float,
    plate_half: float,
) -> cq.Workplane:
    """The back plate, floor, front and sides, with the pocket cut out."""

    half = p.width_mm / 2 + clearance + spec.wall_mm
    inner = p.width_mm / 2 + clearance
    pocket_y = 2 * clearance + p.depth_mm
    body = box(
        -plate_half, plate_half, -spec.back_mm, 0.0, -spec.floor_mm, p.height_mm
    ).union(box(-half, half, 0.0, pocket_y + spec.wall_mm, -spec.floor_mm, front))

    if side_top > front:
        for x0, x1 in ((-half, -inner), (inner, half)):
            body = body.union(
                box(x0, x1, 0.0, pocket_y + spec.wall_mm, front, side_top)
            )

    pocket = xz_prism(
        outline(p.width_mm, p.height_mm, p.radius_mm, clearance), 0.0, pocket_y
    ).union(box(-inner, inner, 0.0, pocket_y, p.height_mm / 2, p.height_mm + 1.0))

    return body.cut(pocket)


def _checks(
    spec: HolderSpec,
    p: Placed,
    body: cq.Workplane,
    plain: cq.Workplane,
    item: cq.Shape,
    openings: list[Opening],
    mount: MountPlan,
    tabs: tuple[HolderTab, ...],
) -> dict[str, bool]:
    """Every check on the built holder; ``plain`` is the body without the tabs' hooks, which
    give as the object is lifted."""

    solid = body.val()
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "object_fits_pocket": clear(solid, item),
        "object_lifts_out": lifts_out(item, plain.val(), p.height_mm),
        "features_open": all(_open(solid, opening.probe) for opening in openings),
        "fixings_open": all(
            _open(solid, _hole_probe(fixing, spec.back_mm))
            for fixing in mount.fixings
            if fixing.has_hole
        ),
    }

    if spec.mount == "pegboard":
        checks["pegs_on_pitch"] = pegs_on_pitch(
            mount.fixings, spec.mount_figures["pitch_mm"]
        )

    if tabs and spec.tab_overhang_mm is not None:
        checks["hooks_over_object"] = hooks_over_object(
            tabs, p, item, spec.tab_overhang_mm
        )

    return checks


def _model_cup(
    spec: HolderSpec,
    model: HolderModel,
    p: Placed,
    clearance: float,
    front: float,
    plate_half: float,
) -> cq.Workplane:
    """The back plate, and a cup round the model's shadow seen from above, open at the top."""

    shift = clearance + p.depth_mm / 2
    points = [(x, y + shift) for x, y in model.shadow.points]
    reach = plate_half + spec.wall_mm + 10.0
    wall = outline_prism(points, -spec.floor_mm, front, clearance + spec.wall_mm).cut(
        box(
            -reach,
            reach,
            -reach - p.depth_mm,
            -spec.back_mm,
            -spec.floor_mm - 1.0,
            front + 1.0,
        )
    )
    body = box(
        -plate_half, plate_half, -spec.back_mm, 0.0, -spec.floor_mm, p.height_mm
    ).union(wall)

    return body.cut(outline_prism(points, 0.0, p.height_mm + 1.0, clearance))


@dataclass(frozen=True)
class _Shaped:
    """What the object asks of the holder before the mount and the finishing cuts."""

    p: Placed
    front: float
    openings: list[Opening]
    tabs: tuple[HolderTab, ...]
    mount: MountPlan
    body: cq.Workplane
    item: cq.Shape
    # The finger notch is cut from here forward, through the front.
    notch_from_y: float


def _shape_model(
    spec: HolderSpec,
    model: HolderModel,
    clearance: float,
    fits: dict[str, float],
) -> _Shaped:
    if spec.tab_overhang_mm is not None:
        raise ValueError(
            "Retaining tabs need a captured object, whose flat top the hooks hold; a model's "
            "holder takes none yet"
        )

    width, depth, height = model.size_mm
    p = Placed(width, depth, height, None)
    front = front_height(spec, p)
    # The shadow is drawn to a grid and can be a pixel wider than the model, so the plate is
    # as wide as the cup round the shadow.
    reach = max(abs(x) for x, _ in model.shadow.points)
    mount = plan_mount(spec, p, clearance, reach + clearance + spec.wall_mm, fits)
    shape = model.shape.moved(cq.Location(cq.Vector(0, clearance, 0)))

    return _Shaped(
        p=p,
        front=front,
        openings=[],
        tabs=(),
        mount=mount,
        body=_model_cup(spec, model, p, clearance, front, mount.plate_half_width_mm),
        item=shape,
        notch_from_y=clearance + depth / 2,
    )


def _shape_capture(
    spec: HolderSpec,
    capture: WearableCapture,
    clearance: float,
    fits: dict[str, float],
) -> _Shaped:
    p = placed(capture, spec.down_edge)
    front = front_height(spec, p)
    side_top = p.height_mm if spec.tab_overhang_mm is not None else front
    openings, problems = _openings(capture, spec, p, clearance, front, side_top)

    if problems:
        raise ValueError("The holder cannot be built:\n- " + "\n- ".join(problems))

    tabs: tuple[HolderTab, ...] = ()

    if spec.tab_overhang_mm is not None:
        notched = {
            1.0 if o.probe[0] > 0 else -1.0 for o in openings if o.kind == "side_notch"
        }
        tabs = plan_tabs(
            p, clearance, spec.wall_mm, spec.tab_overhang_mm, sorted(notched)
        )

    half = p.width_mm / 2 + clearance + spec.wall_mm
    mount = plan_mount(spec, p, clearance, half, fits)

    return _Shaped(
        p=p,
        front=front,
        openings=openings,
        tabs=tabs,
        mount=mount,
        body=_cup(spec, p, clearance, front, side_top, mount.plate_half_width_mm),
        item=object_solid(p, clearance),
        notch_from_y=2 * clearance + p.depth_mm - 0.5,
    )


def build_holder(
    spec: HolderSpec,
    item: WearableCapture | HolderModel,
    profile: dict[str, Any],
    *,
    side_shortfall_mm: float | None = None,
) -> Holder:
    """The holder for an object, captured or modelled; refused if a wall or the floor is under
    the printer's minimum, a feature cannot be left open, the mount does not fit, or a tab
    cannot be made."""

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
    shaped = (
        _shape_model(spec, item, clearance, fits)
        if isinstance(item, HolderModel)
        else _shape_capture(spec, item, clearance, fits)
    )
    p, body = shaped.p, shaped.body
    pocket_y = 2 * clearance + p.depth_mm
    notch = 2 * (p.width_mm / 2 + clearance) >= NOTCH_WIDTH_MM + 2 * NOTCH_MARGIN_MM

    if notch:
        body = body.cut(
            box(
                -NOTCH_WIDTH_MM / 2,
                NOTCH_WIDTH_MM / 2,
                shaped.notch_from_y,
                pocket_y + spec.wall_mm + 0.5,
                0.0,
                shaped.front + 1.0,
            )
        )

    for opening in shaped.openings:
        body = body.cut(_opening_cutter(opening))

    for cutter in shaped.mount.cutters:
        body = body.cut(cutter)

    for addition in shaped.mount.additions:
        body = body.union(addition)

    plain = body

    for tab in shaped.tabs:
        rise, hook, slits = tab_solids(tab, p, clearance, spec.wall_mm)
        body = body.union(rise).union(hook)
        plain = plain.union(rise)

        for slit in slits:
            body = body.cut(slit)
            plain = plain.cut(slit)

    return Holder(
        spec=spec,
        item=item,
        body=body,
        placed=p,
        clearance_mm=clearance,
        clearance_from=clearance_from,
        front_mm=shaped.front,
        openings=tuple(shaped.openings),
        mount=shaped.mount,
        notch=notch,
        checks=_checks(
            spec,
            p,
            body,
            plain,
            shaped.item,
            shaped.openings,
            shaped.mount,
            shaped.tabs,
        ),
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        tabs=shaped.tabs,
    )


def _opening_cutter(opening: Opening) -> cq.Workplane:
    """What is cut for an opening: a floor slot through the floor only; a notch down a side
    or the front from the feature to above the wall's top, so it has no roof to overhang."""

    x0, x1, y0, y1, z0, z1 = opening.probe

    if opening.kind == "floor_slot":
        return box(x0, x1, y0, y1, z0, z1 + 0.01)

    if opening.kind == "side_notch":
        return box(x0 - 0.5, x1 + 0.5, y0, y1, z0, z1 + 1.0)

    return box(x0, x1, y0 - 0.5, y1 + 0.5, z0, z1 + 1.0)


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

    half = fixing.size_mm / 2 * 0.6

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


def _nominal_measurements(holder: Holder) -> dict[str, float]:
    """The sizes a trial measures with calipers, in mm: the holder as built, the pocket as
    designed, and the walls."""

    width, depth, height = holder.size_mm
    p, clearance, spec = holder.placed, holder.clearance_mm, holder.spec

    return {
        "overall_width_mm": round(width, 3),
        "overall_depth_mm": round(depth, 3),
        "overall_height_mm": round(height, 3),
        "pocket_width_mm": round(p.width_mm + 2 * clearance, 3),
        "pocket_depth_mm": round(p.depth_mm + 2 * clearance, 3),
        "front_mm": round(holder.front_mm, 3),
        "wall_mm": spec.wall_mm,
        "floor_mm": spec.floor_mm,
        "back_mm": spec.back_mm,
    }


def _object_record(holder: Holder) -> dict[str, Any]:
    item, spec = holder.item, holder.spec

    if isinstance(item, HolderModel):
        return {
            "kind": "model",
            "step": str(spec.object_path),
            "sha256": item.sha256,
            "name": item.name,
            "solid_index": item.solid_index,
            "up": item.up,
            "out": item.out,
            "size_in_holder_mm": [round(v, 3) for v in item.size_mm],
            "mass_g": None,
        }

    return {
        "kind": "capture",
        "capture": str(spec.object_path),
        "sha256": item.sha256,
        "name": item.name,
        "size_mm": [item.length_mm, item.width_mm, item.thickness_mm],
        "outline_radius_mm": item.outline_radius_mm,
        "mass_g": item.mass_g,
        "mass_source": item.mass_source or None,
    }


def holder_record(holder: Holder, files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a build says of itself: the object by hash, the settings, what was cut, and that it
    is unverified."""

    spec, p = holder.spec, holder.placed
    width, depth, height = holder.size_mm

    return {
        "schema_version": HOLDER_RECORD_SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "design_name": spec.identifier.lower().replace("_", "-"),
        "holder_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "object": _object_record(holder),
        "settings": {
            "down_edge": spec.down_edge or None,
            "face": spec.face or None,
            "front_mm": round(holder.front_mm, 3),
            "wall_mm": spec.wall_mm,
            "floor_mm": spec.floor_mm,
            "back_mm": spec.back_mm,
            "clearance_per_side_mm": round(holder.clearance_mm, 3),
            "clearance_from": holder.clearance_from,
            "mount": {
                "type": spec.mount,
                "figures": dict(spec.mount_figures),
                "source": spec.mount_source or None,
                **dict(holder.mount.details),
            },
            "retention": (
                None
                if spec.tab_overhang_mm is None
                else {"type": "tabs", "overhang_mm": spec.tab_overhang_mm}
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
        "tabs": [tab.to_dict() for tab in holder.tabs],
        "size_mm": [round(width, 3), round(depth, 3), round(height, 3)],
        "printer_profile_id": holder.profile_id,
        "tolerance_status": holder.tolerance_status,
        "parts": files,
        "fit_checks": holder.checks,
        "checks": holder_checks(
            mount=spec.mount, openings=bool(holder.openings), tabs=bool(holder.tabs)
        ),
        "nominal_measurements_mm": _nominal_measurements(holder),
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
