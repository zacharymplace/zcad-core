"""The snap coupon: drawer detents built at a ladder of engagements.

A drawer's detent (:mod:`zcad_core.features.stack_detent`) is a bump on a tongue cut free of the
drawer's side wall, which clicks into a dimple in the frame's. How far the bump engages decides
whether it clicks at all, holds the drawer shut, lets go to a pull, or strains the tongue until it
whitens; the engine's 0.4 mm is its own guess. The snap coupon builds the joint at 0.3, 0.4, 0.5
and 0.6 mm, the least the engine builds and up, each as a short drawer in a small frame, so one
print shows where the detent starts to hold and where it stops letting go.

Every rung is built by the product's own code: a frame plan, ``plan_detent`` with only the
engagement changed, the drawer from ``drawer_solid`` with its tongues cut and bumps added, and
the dimples cut by ``cut_dimples`` into the frame's side walls. The tongue's length is solved, as
in a product, from the strain limit the build is held to, so the record keeps that limit: a rung
measured at one limit says nothing about a tongue sized for another.

The frame here is a box: a floor the drawer slides on, a roof, side walls and a back, open at the
front. A product's frame stands on a foot and carries ledges; neither touches the detent, which
acts across the side walls. Each drawer and its frame carry a row of dots, one for the first
rung, two for the second and so on, so the pieces cannot be mixed up off the plate.

Frame: the rungs run left to right from the least engagement, each frame behind its drawer,
both as they print.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.mounts import flexure_strain_limit, strain_limit_source
from zcad_core.features.stack_detent import (
    DetentPlan,
    add_bumps,
    cut_dimples,
    cut_tongues,
    plan_detent,
)
from zcad_core.features.stack_drawers import (
    LEDGE_THICKNESS_MM,
    ROOF_MM,
    TOP_CLEARANCE_MM,
    FramePlan,
    drawer_solid,
)
from zcad_core.features.stack_solids import MINIMUM_RADIUS_MM
from zcad_core.profiles.joints import JOINT_TRIAL_RECORD, SNAP_READINGS

SNAP_COUPON_SCHEMA_VERSION = "1.0.0"
# The rungs' geometry; a profile records it, so a rung built by older geometry is known.
GENERATOR_VERSION = "1.0.0"
BUILD_RECORD = "joint-coupon.json"
OBSERVATIONS = "observations.json"

# The rungs, the least the engine builds and up.
SNAP_ENGAGEMENTS_MM = (0.3, 0.4, 0.5, 0.6)
# A rung's frame and drawer: the coupon's own design choices, as small as a detent allows. The
# frame's wall leaves the printer's minimum behind the deepest dimple; the drawer's is a
# product's default wall, which the tongue is cut from.
FRAME_WALL_MM = 2.0
INNER_WIDTH_MM = 22.0
INNER_DEPTH_MM = 32.0
DRAWER_HEIGHT_MM = 9.0
DRAWER_WALL_MM = 1.2
DRAWER_FLOOR_MM = 1.2
RUNG_GAP_MM = 6.0
# The marks that number a rung: dots in the drawer's floor and the frame's roof.
DOT_DIAMETER_MM = 1.6
DOT_DEPTH_MM = 0.6
DOT_PITCH_MM = 3.0

READING_GUIDANCE = (
    "Slide the drawer into its frame, the dots matching, and push it shut. clicks_shut: it "
    "clicks home. holds_shake: hold the frame open side down and shake it lightly; the drawer "
    "stays in. lets_go: a fingertip in the pull draws it out without squeezing the frame. "
    "whitened: after ten openings, a white mark or crack on the tongue or bump. A spring scale's "
    "pull to open it, in newtons, if you have one. Mark the rung skipped if you did not try it."
)
CHECKS = (
    (
        "printed_cleanly",
        "Every frame and drawer printed without warping, and each tongue is cut free along its slits.",
    ),
    (
        "rungs_matched",
        "Each drawer was tried in the frame with the same number of dots.",
    ),
)


@dataclass(frozen=True)
class SnapRung:
    """One rung: its engagement, its detent's sizes, its frame and drawer as they print."""

    name: str
    engagement_mm: float
    detent: DetentPlan
    frame: cq.Workplane
    drawer: cq.Workplane


@dataclass(frozen=True)
class SnapCoupon:
    """The snap coupon as built."""

    clearance_mm: float
    strain_limit: float
    strain_limit_source: str
    rungs: tuple[SnapRung, ...]
    size_mm: tuple[float, float, float]

    def pieces(self, kind: str) -> cq.Workplane:
        """Every frame, or every drawer, as one model to export."""

        model = cq.Workplane("XY")

        for rung in self.rungs:
            model = model.add(getattr(rung, kind).vals())

        return model


def rung_name(engagement: float) -> str:
    return f"detent_{engagement:.2f}".replace(".", "_")


def snap_frame_plan(clearance_mm: float) -> FramePlan:
    """The shared sizes of a rung's frame and drawer, as a product's frame plan gives them."""

    roof = LEDGE_THICKNESS_MM + DRAWER_HEIGHT_MM + TOP_CLEARANCE_MM

    return FramePlan(
        outer_width=INNER_WIDTH_MM + 2 * FRAME_WALL_MM,
        outer_depth=INNER_DEPTH_MM + 2 * FRAME_WALL_MM,
        inner_width=INNER_WIDTH_MM,
        inner_depth=INNER_DEPTH_MM,
        inner_radius=MINIMUM_RADIUS_MM,
        wall_top=roof + ROOF_MM,
        floor_z=0.0,
        roof_z=roof,
        slots=1,
        pitch=roof,
        drawer_width=INNER_WIDTH_MM - 2 * clearance_mm,
        drawer_length=INNER_DEPTH_MM + FRAME_WALL_MM - clearance_mm,
        drawer_height=DRAWER_HEIGHT_MM,
        drawer_wall=DRAWER_WALL_MM,
        drawer_floor=DRAWER_FLOOR_MM,
        clearance=clearance_mm,
    )


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            x[1] - x[0], y[1] - y[0], z[1] - z[0], pnt=cq.Vector(x[0], y[0], z[0])
        )
    )


def _dots(count: int, y: float, top: float) -> cq.Workplane:
    """``count`` dots in a row across X, centred, sunk into a face at ``top``."""

    start = -(count - 1) * DOT_PITCH_MM / 2
    dots = cq.Workplane("XY")

    for index in range(count):
        dots = dots.add(
            cq.Solid.makeCylinder(
                DOT_DIAMETER_MM / 2,
                DOT_DEPTH_MM + 1.0,
                cq.Vector(start + index * DOT_PITCH_MM, y, top - DOT_DEPTH_MM),
            )
        )

    return dots


def _frame(plan: FramePlan, detent: DetentPlan, count: int) -> cq.Workplane:
    """A box open at the front, with a dimple in each side wall and ``count`` dots on its roof."""

    half_outer = plan.outer_width / 2
    half_depth = plan.outer_depth / 2
    top = plan.roof_z + ROOF_MM
    frame = _box((-half_outer, half_outer), (-half_depth, half_depth), (0.0, top))
    cavity = _box(
        (-plan.inner_width / 2, plan.inner_width / 2),
        (-half_depth - 1.0, half_depth - FRAME_WALL_MM),
        (LEDGE_THICKNESS_MM, plan.roof_z),
    )
    frame = cut_dimples(frame.cut(cavity), detent)

    for dot in _dots(count, 0.0, top).vals():
        frame = frame.cut(cq.Workplane("XY").add(dot))

    return frame


def _drawer(plan: FramePlan, detent: DetentPlan, count: int) -> cq.Workplane:
    """The product's drawer, its tongues freed and bumped, with ``count`` dots in its floor."""

    drawer = add_bumps(cut_tongues(drawer_solid(plan, pull=True), detent), detent)
    floor_top = LEDGE_THICKNESS_MM + plan.drawer_floor
    centre = -plan.outer_depth / 2 + plan.drawer_length / 2

    for dot in _dots(count, centre, floor_top).vals():
        drawer = drawer.cut(cq.Workplane("XY").add(dot))

    return drawer


def build_snap_coupon(clearance_mm: float, least_wall_mm: float) -> SnapCoupon:
    """A frame and a drawer for each rung, laid out as they print: refused if the
    product's planner refuses a rung."""

    plan = snap_frame_plan(clearance_mm)
    pitch = plan.outer_width + RUNG_GAP_MM
    drawer_shift = -(plan.outer_depth + RUNG_GAP_MM)
    rungs = []

    for index, engagement in enumerate(SNAP_ENGAGEMENTS_MM):
        detent, errors = plan_detent(
            plan, FRAME_WALL_MM, engagement, least_wall_mm, clearance_mm
        )

        if detent is None:
            raise ValueError(
                f"The {engagement:g} mm rung cannot be built:\n- " + "\n- ".join(errors)
            )

        x = index * pitch
        rungs.append(
            SnapRung(
                name=rung_name(engagement),
                engagement_mm=engagement,
                detent=detent,
                frame=_frame(plan, detent, index + 1).translate((x, 0.0, 0.0)),
                drawer=_drawer(plan, detent, index + 1).translate(
                    (x, drawer_shift, 0.0)
                ),
            )
        )

    length = len(rungs) * pitch - RUNG_GAP_MM
    depth = 2 * plan.outer_depth + RUNG_GAP_MM

    return SnapCoupon(
        clearance_mm=clearance_mm,
        strain_limit=flexure_strain_limit(),
        strain_limit_source=strain_limit_source(),
        rungs=tuple(rungs),
        size_mm=(length, depth, plan.roof_z + ROOF_MM),
    )


def snap_coupon_checks(
    coupon: SnapCoupon, build_volume_mm: dict[str, float] | None
) -> dict[str, dict[str, Any]]:
    """What a snap coupon must pass before it is worth printing."""

    length, depth, height = coupon.size_mm
    fits = build_volume_mm is None or (
        length <= float(build_volume_mm["x"])
        and depth <= float(build_volume_mm["y"])
        and height <= float(build_volume_mm["z"])
    )
    pieces = {
        f"{rung.name}_{kind}": len(getattr(rung, kind).solids().vals())
        for rung in coupon.rungs
        for kind in ("frame", "drawer")
    }
    split = sorted(name for name, solids in pieces.items() if solids != 1)
    strained = [
        rung.name for rung in coupon.rungs if rung.detent.strain > coupon.strain_limit
    ]

    return {
        "fits_bed": {
            "passed": fits,
            "detail": f"{length:.1f} x {depth:.1f} x {height:.1f} mm",
        },
        "each_piece_one_solid": {
            "passed": not split,
            "detail": f"{len(pieces)} pieces"
            + (f"; split: {', '.join(split)}" if split else ""),
        },
        "tongues_within_strain_limit": {
            "passed": not strained,
            "detail": (
                f"limit {100 * coupon.strain_limit:g} per cent ({coupon.strain_limit_source})"
                + (f"; over it: {', '.join(strained)}" if strained else "")
            ),
        },
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_snap_coupon_record(
    coupon: SnapCoupon,
    *,
    name: str,
    stl_paths: dict[str, Path],
    output_directory: Path,
    printer_profile_id: str,
    checks: dict[str, dict[str, Any]],
) -> Path:
    """Write ``joint-coupon.json`` beside the coupon's STLs."""

    record = {
        "schema_version": SNAP_COUPON_SCHEMA_VERSION,
        "family": "snap",
        "joint": "drawer_detent",
        "design_name": name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "generator_version": GENERATOR_VERSION,
        "printer_profile_id": printer_profile_id,
        "clearance_mm": coupon.clearance_mm,
        "strain_limit": coupon.strain_limit,
        "strain_limit_source": coupon.strain_limit_source,
        "size_mm": [round(value, 3) for value in coupon.size_mm],
        "rungs": [
            {
                "name": rung.name,
                "engagement_mm": rung.engagement_mm,
                "dots": index + 1,
                "detent": rung.detent.to_dict(),
            }
            for index, rung in enumerate(coupon.rungs)
        ],
        "parts": {
            part: {"stl_path": str(path), "stl_sha256": sha256(path)}
            for part, path in stl_paths.items()
        },
        "checks": checks,
    }
    path = output_directory / BUILD_RECORD
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    return path


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object in {path}")

    return payload


def start_snap_trial(build_record_path: Path) -> Path:
    """Write the next trial's observations template: the two checks and a reading
    for every rung."""

    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)
    observations: dict[str, Any] = {
        check: {"result": "pending", "guidance": guidance, "notes": ""}
        for check, guidance in CHECKS
    }
    observations.update(
        {
            rung["name"]: {
                "reading": {
                    **{field: None for field in SNAP_READINGS},
                    "pull_force_n": None,
                },
                "engagement_mm": rung["engagement_mm"],
                "dots": rung["dots"],
                "guidance": READING_GUIDANCE,
                "notes": "",
            }
            for rung in build["rungs"]
        }
    )
    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )

    return trial


def _reading(name: str, given: Any) -> dict[str, Any] | None:
    """A rung's reading, checked; None for a rung skipped."""

    if given == "skipped":
        return None

    if not isinstance(given, dict):
        raise TypeError(f"{name} must be a reading or skipped, not {given!r}")

    reading: dict[str, Any] = {}

    for field in SNAP_READINGS:
        if not isinstance(given.get(field), bool):
            raise TypeError(f"{name}.{field} must be true or false")

        reading[field] = given[field]

    force = given.get("pull_force_n")

    if force is not None and (not isinstance(force, int | float) or force < 0):
        raise ValueError(f"{name}.pull_force_n must be a number of newtons, or null")

    reading["pull_force_n"] = None if force is None else float(force)

    return reading


def complete_snap_trial(
    trial: Path, *, material_profile_id: str, notes: str = ""
) -> Path:
    """Validate a filled-in trial and write its record. A snap coupon has no
    disposition: how each rung behaved is the result."""

    record_path = trial / JOINT_TRIAL_RECORD

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as "
            "the next trial"
        )

    build_path = trial.parent.parent / BUILD_RECORD
    build = _read(build_path)

    for part in build["parts"].values():
        if (
            not Path(part["stl_path"]).is_file()
            or sha256(Path(part["stl_path"])) != part["stl_sha256"]
        ):
            raise ValueError("The printed coupon no longer matches its build record")

    observed = _read(trial / OBSERVATIONS)
    observations = []

    for check, _ in CHECKS:
        result = observed.get(check, {}).get("result")

        if result not in ("pass", "fail"):
            raise ValueError(f"Observation {check} must be pass or fail, not {result}")

        observations.append(
            {
                "check": check,
                "passed": result == "pass",
                "notes": str(observed[check].get("notes", "")),
            }
        )

    if not all(entry["passed"] for entry in observations):
        failed = [entry["check"] for entry in observations if not entry["passed"]]
        raise ValueError(
            f"The coupon failed {', '.join(failed)}; its readings would not say how "
            "the detent holds. Print another"
        )

    readings = []

    for rung in build["rungs"]:
        reading = _reading(rung["name"], observed.get(rung["name"], {}).get("reading"))

        if reading is not None:
            readings.append(
                {
                    "name": rung["name"],
                    "engagement_mm": rung["engagement_mm"],
                    **reading,
                    "notes": str(observed[rung["name"]].get("notes", "")),
                }
            )

    if not readings:
        raise ValueError("A joint coupon trial needs at least one rung read")

    record = {
        "schema_version": SNAP_COUPON_SCHEMA_VERSION,
        "family": "snap",
        "joint": build["joint"],
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": sha256(build_path),
        "generator_version": build["generator_version"],
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "clearance_mm": build["clearance_mm"],
        "strain_limit": build["strain_limit"],
        "strain_limit_source": build["strain_limit_source"],
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "observations": observations,
        "readings": readings,
        "notes": notes,
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    return record_path
