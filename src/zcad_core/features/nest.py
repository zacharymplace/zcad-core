"""Build a holding nest: a tray with a floor and a wall round a part's shadow.

The part stands on the floor in a pocket that follows its shadow, widened by the printer's sliding
clearance, with a wall round the pocket. The floor reaches past the wall by the flange. Finger
notches cut the wall down to the floor so the part lifts out by hand. The build refuses a nest
whose walls or floor are under the printer's minimum, whose notches do not fit the outline, or
from which the part would not lift straight up. Its record names the part by hash and says the nest
is unverified.

Frame: the part's own, as in :mod:`zcad_core.features.nest_file`: the part's top is ``z == 0``, its
bottom ``z == -height``, which is the floor's top; the wall climbs from there.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.guide_file import GuidePart
from zcad_core.features.nest_core import clear, lifts_out, pocketed
from zcad_core.features.nest_features import (
    DEFAULT_EMBOSS_MM,
    DEFAULT_TEXT_SIZE_MM,
    HOOK_FACE_MM,
    HOOK_GAP_MM,
    HOOK_HEIGHT_MM,
    SLIT_MM,
    TAB_ROOT_MM,
    TAB_WIDTH_MM,
    Label,
    StrapSlot,
    Tab,
    label_solid,
    lip_errors,
    plan_label,
    plan_strap,
    slot_cutter,
    strap_slots_clear,
    tab_strain,
)
from zcad_core.features.nest_file import (
    NOTCH_MARGIN_MM,
    NOTCH_WIDTH_MM,
    NestSpec,
    pocket_depth_mm,
)
from zcad_core.geometry.outline_prism import outline_prism

NEST_RECORD_SCHEMA_VERSION = "1.0.0"
NEST_RECORD = "nest.json"
RECORD_KIND = "nest-build"
NOT_CLAIMED = (
    "The engine states nothing about how well the nest holds a part, only that the part fits "
    "the pocket and lifts straight out. A nest is unverified until a printed trial has passed."
)
Point = tuple[float, float]


@dataclass(frozen=True)
class Notch:
    """A finger notch: where it is cut through the wall, and the stretch of outline it is on."""

    centre: Point
    # The outward direction from the outline, a unit vector.
    outward: Point
    # The direction along the outline, a unit vector.
    along: Point
    stretch_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "centre_mm": [round(self.centre[0], 3), round(self.centre[1], 3)],
            "width_mm": NOTCH_WIDTH_MM,
            "stretch_mm": round(self.stretch_mm, 3),
        }


@dataclass(frozen=True)
class Nest:
    """The built nest and what it was built from."""

    spec: NestSpec
    part: GuidePart
    body: cq.Workplane
    depth_mm: float
    clearance_mm: float
    profile_id: str
    tolerance_status: str
    notches: tuple[Notch, ...]
    checks: dict[str, bool]
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    slots: tuple[StrapSlot, ...] = ()
    label: Label | None = None
    tabs: tuple[Tab, ...] = ()

    @property
    def passed(self) -> bool:
        return all(self.checks.values()) and not self.problems

    @property
    def size_mm(self) -> tuple[float, float, float]:
        box = self.body.val().BoundingBox()  # type: ignore[union-attr]

        return box.xlen, box.ylen, box.zlen


def _signed_area(points: tuple[Point, ...]) -> float:
    return (
        sum(
            a[0] * b[1] - b[0] * a[1]
            for a, b in zip(points, (*points[1:], points[0]), strict=True)
        )
        / 2
    )


def stretch_sites(points: tuple[Point, ...]) -> list[Notch]:
    """The straight stretches of the outline long enough for a notch or a tab, the longest
    first, each with the direction along it and the one outward from the part."""

    sign = 1.0 if _signed_area(points) > 0 else -1.0
    wanted = NOTCH_WIDTH_MM + 2 * NOTCH_MARGIN_MM
    stretches = []

    for a, b in zip(points, (*points[1:], points[0]), strict=True):
        length = math.hypot(b[0] - a[0], b[1] - a[1])

        if length >= wanted:
            along = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            outward = (sign * along[1], -sign * along[0])
            centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            stretches.append(Notch(centre, outward, along, length))

    stretches.sort(key=lambda notch: -notch.stretch_mm)

    return stretches


def notch_sites(
    points: tuple[Point, ...], count: int
) -> tuple[tuple[Notch, ...], list[str]]:
    """Where ``count`` finger notches go: the middle of the longest straight stretches of the
    outline, each long enough for a notch with a margin past its ends. Fewer long stretches than
    notches asked for is refused, naming how many there are."""

    if count == 0:
        return (), []

    wanted = NOTCH_WIDTH_MM + 2 * NOTCH_MARGIN_MM
    stretches = stretch_sites(points)

    if len(stretches) < count:
        message = (
            f"{count} finger notches need {count} straight stretches of outline at least "
            f"{wanted:g} mm long; the part's shadow has {len(stretches)}"
        )

        return tuple(stretches), [message]

    return tuple(stretches[:count]), []


def _notch_cutter(
    notch: Notch, clearance: float, wall: float, z0: float, z1: float
) -> cq.Workplane:
    """The box that cuts a notch through the wall, from the floor's top to above the wall:
    across the pocket's edge and the wall, centred on the middle of the stretch."""

    inner, outer = clearance - 1.0, clearance + wall + 0.5
    thickness = outer - inner
    offset = (inner + outer) / 2
    angle = math.degrees(math.atan2(notch.along[1], notch.along[0]))
    box = (
        cq.Workplane("XY")
        .box(NOTCH_WIDTH_MM, thickness, z1 - z0, centered=(True, True, False))
        .rotate((0, 0, 0), (0, 0, 1), angle)
    )

    shift = (
        notch.centre[0] + notch.outward[0] * offset,
        notch.centre[1] + notch.outward[1] * offset,
        z0,
    )

    return box.translate(shift)


def build_nest(spec: NestSpec, part: GuidePart, profile: dict[str, Any]) -> Nest:
    """The tray for a part; refused if a wall, the floor or a notch does not fit, or the part
    would not lift out."""

    fits, least_wall, least_floor = printer_numbers(profile)
    clearance = fits["sliding_clearance_per_side"]

    if spec.wall_mm < least_wall:
        raise ValueError(
            f"nest.wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm minimum wall"
        )

    if spec.floor_mm < least_floor:
        raise ValueError(
            f"nest.floor_mm is {spec.floor_mm:g}, under the printer's {least_floor:g} mm minimum "
            "floor"
        )

    depth = pocket_depth_mm(spec, part)

    if depth > part.height_mm + 1e-6:
        raise ValueError(
            f"nest.depth_mm is {depth:g}, deeper than the part's {part.height_mm:.1f} mm height"
        )

    points = part.silhouette.points
    floor_top = -part.height_mm
    floor_bottom = floor_top - spec.floor_mm
    wall_top = floor_top + depth
    notches, problems = notch_sites(points, spec.finger_notches)

    if problems:
        raise ValueError("The notches cannot be placed:\n- " + "\n- ".join(problems))

    body = pocketed(
        points,
        clearance_mm=clearance,
        wall_mm=spec.wall_mm,
        outer_z0=floor_bottom,
        outer_z1=wall_top,
        pocket_z0=floor_top,
        pocket_z1=wall_top + 1.0,
    )

    if spec.flange_mm > 0:
        body = body.union(
            outline_prism(
                points,
                floor_bottom,
                floor_top,
                clearance + spec.wall_mm + spec.flange_mm,
            )
        )

    for notch in notches:
        body = body.cut(
            _notch_cutter(notch, clearance, spec.wall_mm, floor_top, wall_top + 1.0)
        )

    slots, label, extra = _plan_features(spec, part, profile, clearance, least_wall)
    plain = body

    if extra:
        raise ValueError("The nest cannot be built:\n- " + "\n- ".join(extra))

    for slot in slots:
        body = body.cut(slot_cutter(slot, floor_bottom - 0.5, floor_top + 0.5))
        plain = plain.cut(slot_cutter(slot, floor_bottom - 0.5, floor_top + 0.5))

    if label is not None:
        body = body.union(label_solid(label, floor_top))
        plain = plain.union(label_solid(label, floor_top))

    tabs = _tab_sites(spec, part, notches, clearance)

    for tab in tabs:
        body, plain = _add_tab(body, plain, tab, spec, clearance, floor_top, wall_top)

    checks = _nest_checks(
        spec, part, body, plain, notches, slots, tabs, clearance, least_wall, depth
    )

    return Nest(
        spec=spec,
        part=part,
        body=body,
        depth_mm=depth,
        clearance_mm=clearance,
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        notches=notches,
        checks=checks,
        warnings=(),
        slots=slots,
        label=label,
        tabs=tabs,
    )


def _nest_checks(
    spec: NestSpec,
    part: GuidePart,
    body: cq.Workplane,
    plain: cq.Workplane,
    notches: tuple[Notch, ...],
    slots: tuple[StrapSlot, ...],
    tabs: tuple[Tab, ...],
    clearance: float,
    least_wall: float,
    depth: float,
) -> dict[str, bool]:
    """Every check on the built nest; ``plain`` is the body without a lip's hooks."""

    points = part.silhouette.points
    floor_top = -part.height_mm
    floor_bottom = floor_top - spec.floor_mm
    wall_top = floor_top + depth
    solid = body.val()
    checks = {
        "one_solid": len(body.solids().vals()) == 1,
        "part_fits_pocket": clear(solid, part.shape),
        # A lip's hooks give way as the part is lifted, so the part lifts out of the nest as it
        # is without them.
        "part_lifts_out": lifts_out(part.shape, plain.val(), depth),
        "notches_open": _notches_open(
            solid, notches, clearance, spec.wall_mm, floor_top, wall_top
        ),
    }

    if slots:
        checks["strap_slots_in_flange"] = strap_slots_clear(
            slots,
            points,
            clearance,
            spec.wall_mm,
            spec.flange_mm,
            least_wall,
            floor_bottom,
            floor_top,
        )

    if tabs:
        checks["lip_over_part"] = _lip_over_part(part, tabs, clearance, spec)

    return checks


def _plan_features(
    spec: NestSpec,
    part: GuidePart,
    profile: dict[str, Any],
    clearance: float,
    least_wall: float,
) -> tuple[tuple[StrapSlot, ...], Label | None, list[str]]:
    """The strap slots and the label, and everything that stops the nest's features being built."""

    points = part.silhouette.points
    slots, errors = plan_strap(spec, points, clearance, least_wall)
    minimums = profile.get("minimums_mm", {})
    label, label_errors = plan_label(
        spec,
        points,
        clearance,
        float(minimums.get("text_size", DEFAULT_TEXT_SIZE_MM)),
        float(minimums.get("emboss_height", DEFAULT_EMBOSS_MM)),
        slots,
    )
    errors += label_errors
    errors += lip_errors(spec, part.height_mm, part.silhouette.top_share, clearance)

    return slots, label, errors


def _tab_sites(
    spec: NestSpec, part: GuidePart, notches: tuple[Notch, ...], clearance: float
) -> tuple[Tab, ...]:
    """The lip's tabs: on the longest stretches the finger notches have not taken."""

    if spec.lip_tabs == 0:
        return ()

    taken = {n.centre for n in notches}
    free = [
        site
        for site in stretch_sites(part.silhouette.points)
        if site.centre not in taken
    ]

    if len(free) < spec.lip_tabs:
        raise ValueError(
            f"{spec.lip_tabs} lip tabs need {spec.lip_tabs} straight stretches of outline at "
            f"least {NOTCH_WIDTH_MM + 2 * NOTCH_MARGIN_MM:g} mm long that the finger notches "
            f"have not taken; the part's shadow has {len(free)}"
        )

    strain, reach, deflection = tab_strain(
        part.height_mm, spec.wall_mm, spec.lip_overhang_mm, clearance
    )

    return tuple(
        Tab(site.centre, site.outward, site.along, strain, reach, deflection)
        for site in free[: spec.lip_tabs]
    )


def _add_tab(
    body: cq.Workplane,
    plain: cq.Workplane,
    tab: Tab,
    spec: NestSpec,
    clearance: float,
    floor_top: float,
    wall_top: float,
) -> tuple[cq.Workplane, cq.Workplane]:
    """The tab's wall rises above the wall's top, carries a hook that overhangs the part's top
    face, and is cut free of the wall beside it by a slit each side. Returns the body with the
    hook and the body without it, for the release check."""

    top = wall_top + HOOK_GAP_MM + HOOK_HEIGHT_MM
    angle = math.degrees(math.atan2(tab.along[1], tab.along[0]))
    wall = spec.wall_mm
    mid = clearance + wall / 2

    def placed(
        box: cq.Workplane, along: float, across: float, z: float
    ) -> cq.Workplane:
        return box.rotate((0, 0, 0), (0, 0, 1), angle).translate(
            (
                tab.centre[0] + tab.along[0] * along + tab.outward[0] * across,
                tab.centre[1] + tab.along[1] * along + tab.outward[1] * across,
                z,
            )
        )

    rise = cq.Workplane("XY").box(
        TAB_WIDTH_MM, wall, top - wall_top, centered=(True, True, False)
    )
    extension = placed(rise, 0.0, mid, wall_top)
    length = clearance + spec.lip_overhang_mm
    wedge = (
        cq.Workplane("XZ")
        .polyline(
            [
                (0.0, HOOK_GAP_MM),
                (length, HOOK_GAP_MM),
                (length, HOOK_GAP_MM + HOOK_FACE_MM),
                (0.0, HOOK_GAP_MM + HOOK_HEIGHT_MM),
            ]
        )
        .close()
        .extrude(TAB_WIDTH_MM / 2, both=True)
    )
    inward = math.degrees(math.atan2(-tab.outward[1], -tab.outward[0]))
    face = (
        tab.centre[0] + tab.outward[0] * clearance,
        tab.centre[1] + tab.outward[1] * clearance,
    )
    hook = wedge.rotate((0, 0, 0), (0, 0, 1), inward).translate(
        (face[0], face[1], wall_top)
    )
    slit_height = top + 1.0 - (floor_top + TAB_ROOT_MM)
    slits = [
        placed(
            cq.Workplane("XY").box(
                SLIT_MM, wall + 1.5, slit_height, centered=(True, True, False)
            ),
            sign * (TAB_WIDTH_MM / 2 + SLIT_MM / 2),
            mid,
            floor_top + TAB_ROOT_MM,
        )
        for sign in (1.0, -1.0)
    ]
    body = body.union(extension).union(hook)
    plain = plain.union(extension)

    for slit in slits:
        body = body.cut(slit)
        plain = plain.cut(slit)

    return body, plain


def _lip_over_part(
    part: GuidePart, tabs: tuple[Tab, ...], clearance: float, spec: NestSpec
) -> bool:
    """Each hook has the part's top face under it: the point under the middle of the hook's
    overhang, just below the part's top, is inside the part."""

    reach = clearance + spec.lip_overhang_mm
    solids = part.shape.Solids()

    for tab in tabs:
        x = tab.centre[0] + tab.outward[0] * (clearance - reach / 2)
        y = tab.centre[1] + tab.outward[1] * (clearance - reach / 2)

        if not any(solid.isInside(cq.Vector(x, y, -0.1)) for solid in solids):
            return False

    return True


def _notches_open(
    body: object,
    notches: tuple[Notch, ...],
    clearance: float,
    wall: float,
    floor_top: float,
    wall_top: float,
) -> bool:
    """Every notch is open: no material in the wall at the middle of each, just above the floor
    and at the wall's top."""

    if not isinstance(body, cq.Shape):
        raise TypeError("Expected a shape")

    solids = body.Solids()

    for notch in notches:
        x = notch.centre[0] + notch.outward[0] * (clearance + wall / 2)
        y = notch.centre[1] + notch.outward[1] * (clearance + wall / 2)

        for z in (wall_top - 0.2, floor_top + 0.2):
            if any(solid.isInside(cq.Vector(x, y, z)) for solid in solids):
                return False

    return True


def print_oriented(nest: Nest) -> cq.Workplane:
    """The nest as it goes on the bed: its floor flat down, the pocket opening up."""

    low = nest.body.val().BoundingBox().zmin  # type: ignore[union-attr]

    return nest.body.translate((0.0, 0.0, -low))


def require_fits_bed(nest: Nest, profile: dict[str, Any]) -> None:
    """Refuse a nest that will not lie on the printer's bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    width, depth, height = nest.size_mm
    fits = width <= volume["x"] and depth <= volume["y"]
    turned = width <= volume["y"] and depth <= volume["x"]

    if not (fits or turned) or height > volume["z"]:
        raise ValueError(
            f"The nest is {width:.0f} x {depth:.0f} x {height:.0f} mm; the printer's bed is "
            f"{volume['x']:.0f} x {volume['y']:.0f} x {volume['z']:.0f} mm"
        )


def nest_record(nest: Nest, files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What a build says of itself: the part by hash, the settings, what was placed, and that it
    is unverified."""

    spec, part = nest.spec, nest.part
    width, depth, height = nest.size_mm

    return {
        "schema_version": NEST_RECORD_SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "design_name": spec.identifier.lower().replace("_", "-"),
        "nest_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "part": {
            "path": str(spec.part_path),
            "sha256": part.sha256,
            "solid_index": spec.solid_index,
            "size_mm": [round(part.size_mm[0], 3), round(part.size_mm[1], 3)],
            "height_mm": round(part.height_mm, 3),
        },
        "settings": {
            "depth_mm": round(nest.depth_mm, 3),
            "wall_mm": spec.wall_mm,
            "floor_mm": spec.floor_mm,
            "flange_mm": spec.flange_mm,
            "finger_notches": spec.finger_notches,
            "lip": (
                None
                if spec.lip_tabs == 0
                else {"tabs": spec.lip_tabs, "overhang_mm": spec.lip_overhang_mm}
            ),
            "strap": (
                None
                if spec.strap is None
                else {
                    "width_mm": spec.strap.width_mm,
                    "thickness_mm": spec.strap.thickness_mm,
                    "source": spec.strap.source,
                }
            ),
            "clearance_per_side_mm": nest.clearance_mm,
        },
        "notches": [notch.to_dict() for notch in nest.notches],
        "strap_slots": [slot.to_dict() for slot in nest.slots],
        "label": None if nest.label is None else nest.label.to_dict(),
        "lip_tabs": [tab.to_dict() for tab in nest.tabs],
        "size_mm": [round(width, 3), round(depth, 3), round(height, 3)],
        "printer_profile_id": nest.profile_id,
        "tolerance_status": nest.tolerance_status,
        "parts": files,
        "fit_checks": nest.checks,
        "verified": False,
        "not_claimed": NOT_CLAIMED,
    }


def write_nest_record(
    nest: Nest, files: dict[str, dict[str, Any]], output_directory: Path
) -> Path:
    """Write ``nest.json``; refuses to replace one."""

    path = output_directory / NEST_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(nest_record(nest, files), indent=2, sort_keys=True) + "\n", "utf-8"
    )

    return path
