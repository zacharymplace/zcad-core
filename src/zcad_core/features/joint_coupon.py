"""Joint coupons: small prints that sweep the figure deciding a joint across rungs.

A product's trial judges one design point of a joint, pass or fail, and a failure
does not say which way to move. A joint coupon builds the same joint at a ladder
of values of its deciding figure, so one print shows where the joint starts to
work and where it stops. Its trial records how each rung felt, and a joint profile
(:mod:`zcad_core.profiles.joints`) picks a rung for each figure by a stated rule.

The **fit** coupon settles the printer profile's two clearances, which guides,
jigs, nests, holders, PCB test fixtures, housings, stacks and fitted Gridfinity
bins read. Its rungs are round holes for a metal reference (a 6 mm drill's shank
or a dowel pin, measured), each sized as those products size a hole for a metal
part (:func:`fit_hole_diameter_mm`): the part's diameter, the clearance each
side, and the printer profile's ``hole_oversize``. Clearances run from 0 to
0.4 mm a side in 0.05 mm steps, twice:

- **in a layer**: the front row, through a block, each hole's axis vertical, so
  its wall is printed perimeters; and
- **across layers**: the back row, through a standing wall, each hole's axis
  front to back, so its wall is layer lines and its top an overhang.

The reference is pushed into each hole by hand and the hole read as won't go,
press, slides or loose. The coupon is built from the printer profile's
``hole_oversize`` as it stands, and records it: a rung measured with one oversize
says nothing about holes built with another.

Frame: the coupon's front-left corner at the origin, a notch there to orient it;
both rows run left to right from the tightest rung.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.profiles.joints import FIT_READINGS, JOINT_TRIAL_RECORD, ORIENTATIONS

JOINT_COUPON_SCHEMA_VERSION = "1.0.0"
# The rungs' geometry; a profile records it, so a rung built by older geometry is known.
GENERATOR_VERSION = "1.0.0"
BUILD_RECORD = "joint-coupon.json"
OBSERVATIONS = "observations.json"

# The reference: a drill's shank or a dowel pin, the metal parts these fits hold.
# The engine's own choice of size; any measured rod will do, passed as --reference-mm.
REFERENCE_DIAMETER_MM = 6.0
# The rungs: clearance each side, the tightest first.
FIT_CLEARANCES_MM = (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4)
# How far the reference engages each hole: as long as a guide's shortest bore.
BORE_LENGTH_MM = 6.0
# Plastic round the holes: the coupon's design choices, each above the
# printer's minimum wall.
MARGIN_MM = 4.5
HOLE_WALL_MM = 3.0
COVER_MM = 2.0
ROW_GAP_MM = 6.0
PLATE_MM = 2.0
NOTCH_MM = 3.0
MINIMUM_WALL_MM = 1.2

READING_GUIDANCE = (
    "Push the reference into the hole by hand, square to the face: wont_go if it "
    "will not enter, press if it goes in only with firm pressure and stays put, "
    "slides if it goes in with light pressure and no play you can feel, loose if "
    "it rattles or tips; skipped if you did not try it."
)
CHECKS = (
    (
        "printed_cleanly",
        "The coupon printed without warping, and no hole is closed by stringing or a sagging top.",
    ),
    (
        "reference_measured",
        "The reference was measured with calipers and is the diameter the record gives.",
    ),
)


def fit_hole_diameter_mm(
    reference_mm: float, clearance_per_side_mm: float, hole_oversize_mm: float
) -> float:
    """The CAD diameter of a hole for a metal part: the part, the clearance each
    side, and what a printer takes off a hole. The same sum a guide's bore
    (:func:`zcad_core.features.guide_bores._hole_sizes`), a jig's
    (:func:`zcad_core.features.jig.bore_diameter_mm`) and a fixture's pin bore
    (:func:`zcad_core.features.pcb_fixture_plan.bore_diameter`) are built from."""

    return reference_mm + 2 * clearance_per_side_mm + hole_oversize_mm


@dataclass(frozen=True)
class Rung:
    """One hole: its orientation, its clearance, its CAD diameter, and its centre."""

    name: str
    orientation: str
    clearance_per_side_mm: float
    hole_diameter_mm: float
    x_mm: float
    y_mm: float
    z_mm: float


@dataclass(frozen=True)
class FitCoupon:
    """The fit coupon as built."""

    reference_mm: float
    hole_oversize_mm: float
    rungs: tuple[Rung, ...]
    size_mm: tuple[float, float, float]
    solid: cq.Workplane


def _rung_name(orientation: str, clearance: float) -> str:
    return f"{orientation}_{clearance:.2f}".replace(".", "_")


def _layout(reference_mm: float, hole_oversize_mm: float) -> dict[str, float]:
    widest = fit_hole_diameter_mm(
        reference_mm, max(FIT_CLEARANCES_MM), hole_oversize_mm
    )
    count = len(FIT_CLEARANCES_MM)
    front_depth = 2 * MARGIN_MM + widest

    return {
        "widest": widest,
        "pitch": widest + HOLE_WALL_MM,
        "length": 2 * MARGIN_MM + count * widest + (count - 1) * HOLE_WALL_MM,
        "front_depth": front_depth,
        "wall_front": front_depth + ROW_GAP_MM,
        "depth": front_depth + ROW_GAP_MM + BORE_LENGTH_MM,
        "wall_height": PLATE_MM + 2 * COVER_MM + widest,
    }


def fit_rungs(reference_mm: float, hole_oversize_mm: float) -> tuple[Rung, ...]:
    """Every rung, the front row then the back, each left to right from the tightest."""

    layout = _layout(reference_mm, hole_oversize_mm)
    rungs = []

    for orientation in ORIENTATIONS:
        for index, clearance in enumerate(FIT_CLEARANCES_MM):
            x = MARGIN_MM + layout["widest"] / 2 + index * layout["pitch"]

            if orientation == "in_layer":
                y, z = layout["front_depth"] / 2, BORE_LENGTH_MM / 2
            else:
                y = layout["wall_front"] + BORE_LENGTH_MM / 2
                z = PLATE_MM + COVER_MM + layout["widest"] / 2

            rungs.append(
                Rung(
                    name=_rung_name(orientation, clearance),
                    orientation=orientation,
                    clearance_per_side_mm=clearance,
                    hole_diameter_mm=fit_hole_diameter_mm(
                        reference_mm, clearance, hole_oversize_mm
                    ),
                    x_mm=x,
                    y_mm=y,
                    z_mm=z,
                )
            )

    return tuple(rungs)


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            x[1] - x[0], y[1] - y[0], z[1] - z[0], pnt=cq.Vector(x[0], y[0], z[0])
        )
    )


def build_fit_coupon(reference_mm: float, hole_oversize_mm: float) -> FitCoupon:
    """The block of vertical holes, the plate, and the wall of horizontal ones."""

    if reference_mm <= 0:
        raise ValueError(
            "The reference's diameter must be a positive number of millimetres"
        )

    if hole_oversize_mm < 0:
        raise ValueError("The printer profile's hole_oversize cannot be negative")

    layout = _layout(reference_mm, hole_oversize_mm)
    length = layout["length"]
    solid = (
        _box((0.0, length), (0.0, layout["front_depth"]), (0.0, BORE_LENGTH_MM))
        .union(_box((0.0, length), (0.0, layout["depth"]), (0.0, PLATE_MM)))
        .union(
            _box(
                (0.0, length),
                (layout["wall_front"], layout["depth"]),
                (0.0, layout["wall_height"]),
            )
        )
    )
    solid = solid.cut(
        _box((-1.0, NOTCH_MM), (-1.0, NOTCH_MM), (-1.0, layout["wall_height"] + 1.0))
    )
    rungs = fit_rungs(reference_mm, hole_oversize_mm)

    for rung in rungs:
        radius = rung.hole_diameter_mm / 2

        if rung.orientation == "in_layer":
            hole = (
                cq.Workplane("XY")
                .workplane(offset=-1.0)
                .center(rung.x_mm, rung.y_mm)
                .circle(radius)
                .extrude(BORE_LENGTH_MM + 2.0)
            )
        else:
            hole = cq.Workplane("XY").add(
                cq.Solid.makeCylinder(
                    radius,
                    BORE_LENGTH_MM + 2.0,
                    cq.Vector(rung.x_mm, layout["wall_front"] - 1.0, rung.z_mm),
                    cq.Vector(0, 1, 0),
                )
            )

        solid = solid.cut(hole)

    return FitCoupon(
        reference_mm=reference_mm,
        hole_oversize_mm=hole_oversize_mm,
        rungs=rungs,
        size_mm=(length, layout["depth"], layout["wall_height"]),
        solid=solid,
    )


def fit_coupon_checks(
    coupon: FitCoupon, build_volume_mm: dict[str, float] | None
) -> dict[str, dict[str, Any]]:
    """What a fit coupon must pass before it is worth printing."""

    length, depth, height = coupon.size_mm
    between = HOLE_WALL_MM
    # The first hole's edge stands MARGIN_MM in from the left, past the notch.
    edge = min(MARGIN_MM, COVER_MM, MARGIN_MM - NOTCH_MM)
    fits = build_volume_mm is None or (
        length <= float(build_volume_mm["x"])
        and depth <= float(build_volume_mm["y"])
        and height <= float(build_volume_mm["z"])
    )
    solids = len(coupon.solid.solids().vals())

    return {
        "fits_bed": {
            "passed": fits,
            "detail": f"{length:.1f} x {depth:.1f} x {height:.1f} mm",
        },
        "walls_round_holes": {
            "passed": min(between, edge) >= MINIMUM_WALL_MM,
            "detail": (
                f"{between:g} mm between holes, {edge:g} mm to an edge, "
                f"at least {MINIMUM_WALL_MM:g} mm"
            ),
        },
        "one_solid": {"passed": solids == 1, "detail": f"{solids} solid(s)"},
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_fit_coupon_record(
    coupon: FitCoupon,
    *,
    name: str,
    stl_path: Path,
    output_directory: Path,
    printer_profile_id: str,
    reference_source: str,
    checks: dict[str, dict[str, Any]],
) -> Path:
    """Write ``joint-coupon.json`` beside the coupon's STL."""

    record = {
        "schema_version": JOINT_COUPON_SCHEMA_VERSION,
        "family": "fit",
        "design_name": name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "generator_version": GENERATOR_VERSION,
        "printer_profile_id": printer_profile_id,
        "reference": {"diameter_mm": coupon.reference_mm, "source": reference_source},
        "hole_oversize_mm": coupon.hole_oversize_mm,
        "bore_length_mm": BORE_LENGTH_MM,
        "size_mm": [round(value, 3) for value in coupon.size_mm],
        "rungs": [
            {
                "name": rung.name,
                "orientation": rung.orientation,
                "clearance_per_side_mm": rung.clearance_per_side_mm,
                "hole_diameter_mm": round(rung.hole_diameter_mm, 4),
                "x_mm": round(rung.x_mm, 3),
                "y_mm": round(rung.y_mm, 3),
                "z_mm": round(rung.z_mm, 3),
            }
            for rung in coupon.rungs
        ],
        "parts": {
            "coupon": {"stl_path": str(stl_path), "stl_sha256": sha256(stl_path)}
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


def start_joint_trial(build_record_path: Path) -> Path:
    """Write the next trial's observations template: the two checks and a
    reading for every rung."""

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
                "reading": "pending",
                "choices": [*FIT_READINGS, "skipped"],
                "orientation": rung["orientation"],
                "clearance_per_side_mm": rung["clearance_per_side_mm"],
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


def complete_joint_trial(
    trial: Path, *, material_profile_id: str, notes: str = ""
) -> Path:
    """Validate a filled-in trial and write its record. A joint coupon has no
    disposition: how each rung felt is the result."""

    record_path = trial / JOINT_TRIAL_RECORD

    if record_path.exists():
        raise FileExistsError(
            f"Trial already completed: {record_path}; record another print as "
            "the next trial"
        )

    build_path = trial.parent.parent / BUILD_RECORD
    build = _read(build_path)
    part = build["parts"]["coupon"]

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
            "the printer fits. Print another"
        )

    readings = []

    for rung in build["rungs"]:
        reading = observed.get(rung["name"], {}).get("reading")

        if reading == "skipped":
            continue

        if reading not in FIT_READINGS:
            raise ValueError(
                f"{rung['name']} must be one of {', '.join(FIT_READINGS)} or skipped, "
                f"not {reading}"
            )

        readings.append(
            {
                "name": rung["name"],
                "orientation": rung["orientation"],
                "clearance_per_side_mm": rung["clearance_per_side_mm"],
                "reading": reading,
                "notes": str(observed[rung["name"]].get("notes", "")),
            }
        )

    if not readings:
        raise ValueError("A joint coupon trial needs at least one rung read")

    record = {
        "schema_version": JOINT_COUPON_SCHEMA_VERSION,
        "family": build["family"],
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": sha256(build_path),
        "generator_version": build["generator_version"],
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "reference": build["reference"],
        "hole_oversize_mm": build["hole_oversize_mm"],
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "observations": observations,
        "readings": readings,
        "notes": notes,
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    return record_path
