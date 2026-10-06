"""A calibration coupon: one small print that measures how a printer prints a fit.

Every clearance the engine models (an insert pocket, a screw hole, the gap beside a
board, the play above it) is printed by a real printer that prints holes small,
walls fat and bridges low. A compensation profile
(:mod:`zcad_core.profiles.compensation`) corrects for that, pooled from recorded
trials. A coupon gives those figures from one quick print instead of waiting on
fixtures and enclosures:

- **holes**, each the size an enclosure models: the M3 insert pocket and the M3
  lid screw hole, three of each, through the plate; their measured diameters give
  ``hole_shortfall_mm``;
- **pockets** of three widths cut into the top face; a pocket prints narrower by
  a wall's growth on each side, so half its width's shortfall gives
  ``side_gap_shortfall_mm``, the per-side figure a fixture's side gap reads; and
- **slots** under a bridge, at the heights a fixture's vertical play is modelled
  at; their measured heights give ``vertical_play_shortfall_mm``; and
- **tongues**, upright posts each bent back against a stop through the deflection
  that strains it to its own figure, 1 to 4 per cent by the end-loaded cantilever
  every flexure check uses (:func:`zcad_core.features.mounts.flexure_for`). Which
  spring back unharmed and which crack or stay bent gives the profile's
  ``strain_limit``. A post bends across its printed layers, the weakest way
  printed plastic bends, so the limit it gives is the cautious one for a flexure
  bending along its layers too; and it prints with no overhang, as a tongue lying
  in a layer could not.

A notch in the front-left corner orients it. The build writes the coupon's STL and
``coupon.json``, the record of every feature's name, kind, figure, nominal size and
place. A trial (:func:`start_coupon_trial`, then :func:`complete_coupon_trial`)
records one print of exactly that STL: whether it printed cleanly, and each feature
measured, written as ``calibration-coupon-trial.json``, which the compensation
profile reads.

The coupon is built with no hole compensation, so it measures the printer itself;
the record says so (``hole_compensation_mm`` is 0).

Frame: the plate's front-left corner at the origin, its top face at ``z == PLATE_MM``;
the holes are the front row, then the pockets, the slots and the tongues, each row
left to right in the order of its record. A tongue's stop stands behind it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.mounts import flexure_for
from zcad_core.hardware import FastenerSpec

COUPON_SCHEMA_VERSION = "1.0.0"
BUILD_RECORD = "coupon.json"
TRIAL_RECORD = "calibration-coupon-trial.json"
OBSERVATIONS = "observations.json"
MEASUREMENTS = "measurements.json"

# The plate: thick enough for a caliper's inside jaws in a hole, and for a pocket
# with a floor under it.
PLATE_MM = 3.0
# Plastic round the features, and between neighbours in a row and between rows.
MARGIN_MM = 4.5
FEATURE_GAP_MM = 5.0
ROW_GAP_MM = 6.0
HOLE_COUNT = 3
# Pockets: wide enough for a caliper's inside jaws, as deep as a capture's wall
# stands, in a plate with a floor left under them.
POCKET_WIDTHS_MM = (6.0, 8.0, 10.0)
POCKET_LENGTH_MM = 9.0
POCKET_DEPTH_MM = 2.0
# Slots: the heights the fixtures' vertical play is modelled at, under a bridge
# whose span the printer bridges in a fixture's capture ledge.
SLOT_HEIGHTS_MM = (0.85, 0.9, 1.0)
SLOT_SPAN_MM = 8.0
SLOT_DEPTH_MM = 8.0
SLOT_ROOF_MM = 1.6
SLOT_CHEEK_MM = 1.5
# Tongues: posts as long and as thick as the flexures they stand for (a snap
# clip's 1 mm wall), bent to these strains; the stop beside each sets how far.
TONGUE_STRAINS = (0.01, 0.015, 0.02, 0.03, 0.04)
TONGUE_LENGTH_MM = 12.0
TONGUE_THICKNESS_MM = 1.0
TONGUE_WIDTH_MM = 4.0
TONGUE_STOP_MM = 2.0
TONGUE_ORIENTATION = "across_layers"
NOTCH_MM = 3.0
# The least plastic left between two neighbouring features.
MINIMUM_WALL_MM = 1.2

HOLE = "hole"
POCKET = "pocket"
SLOT = "slot"
FIGURES = {
    HOLE: "hole_shortfall_mm",
    POCKET: "side_gap_shortfall_mm",
    SLOT: "vertical_play_shortfall_mm",
}
GUIDANCE = {
    HOLE: "Calipers' inside jaws across the hole, at its top face; record the smallest of two readings at right angles.",
    POCKET: "Calipers' inside jaws across the pocket, left to right, halfway along it.",
    SLOT: "Feeler gauges: the thickest that slides under the bridge without forcing.",
}
TONGUE_GUIDANCE = (
    "Push the post's top back until it touches its stop, hold it there for five "
    "seconds, and let go: pass if it springs back upright with no crack or white "
    "mark, fail if it cracks, whitens or stays bent; skipped if you did not test it."
)
TONGUE_RESULTS = ("pass", "fail", "skipped")
CHECKS = (
    (
        "printed_cleanly",
        "The coupon printed without warping, stringing across a hole, or a sagging bridge.",
    ),
    (
        "features_open",
        "Every hole is open through, and every slot is open under its bridge from end to end.",
    ),
)


@dataclass(frozen=True)
class CouponFeature:
    """One measured feature: its measurement name, what it is, its modelled size,
    and where its middle is on the plate."""

    name: str
    kind: str
    nominal_mm: float
    x_mm: float
    y_mm: float

    @property
    def figure(self) -> str:
        return FIGURES[self.kind]


@dataclass(frozen=True)
class Tongue:
    """One tongue: the strain it is bent to, the deflection its stop allows, and
    where its post's middle is on the plate."""

    name: str
    strain: float
    deflection_mm: float
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class Coupon:
    """The coupon as built: its features, its tongues, its size, and its solid."""

    fastener: str
    features: tuple[CouponFeature, ...]
    tongues: tuple[Tongue, ...]
    size_mm: tuple[float, float, float]
    solid: cq.Workplane


def tongue_deflection_mm(strain: float) -> float:
    """How far a tongue's tip must swing to reach ``strain``: the end-loaded
    cantilever's strain, 3 t d / (2 L^2), solved for d."""

    return 2 * strain * TONGUE_LENGTH_MM**2 / (3 * TONGUE_THICKNESS_MM)


def coupon_tongues(front_mm: float) -> tuple[Tongue, ...]:
    """The tongues in a row whose front edge is at ``front_mm``, left to right
    from the gentlest strain."""

    tongues = []
    left = MARGIN_MM

    for strain in TONGUE_STRAINS:
        percent = f"{strain * 100:g}".replace(".", "_")
        tongues.append(
            Tongue(
                name=f"tongue_{percent}_percent",
                strain=strain,
                deflection_mm=tongue_deflection_mm(strain),
                x_mm=left + TONGUE_WIDTH_MM / 2,
                y_mm=front_mm + TONGUE_THICKNESS_MM / 2,
            )
        )
        left += TONGUE_WIDTH_MM + FEATURE_GAP_MM

    return tuple(tongues)


def _tongue_footprint(tongue: Tongue) -> tuple[float, float, float, float]:
    """The post and its stop, from the post's front face to the stop's back."""

    front = tongue.y_mm - TONGUE_THICKNESS_MM / 2

    return (
        tongue.x_mm - TONGUE_WIDTH_MM / 2,
        tongue.x_mm + TONGUE_WIDTH_MM / 2,
        front,
        front + TONGUE_THICKNESS_MM + tongue.deflection_mm + TONGUE_STOP_MM,
    )


def _slug(value: float) -> str:
    return f"{value:g}".replace(".", "")


def coupon_features(fastener: FastenerSpec) -> tuple[CouponFeature, ...]:
    """Every feature, front row to back, each row left to right: the holes, the
    pockets, the slots."""

    insert = fastener.heat_set_insert_diameter_mm

    if insert is None:
        raise ValueError(
            f"{fastener.identifier} has no heat-set insert; a coupon measures its pocket"
        )

    holes = [
        (f"insert_pocket_{n}_diameter_mm", HOLE, insert)
        for n in range(1, HOLE_COUNT + 1)
    ] + [
        (f"screw_hole_{n}_diameter_mm", HOLE, fastener.clearance_hole_mm)
        for n in range(1, HOLE_COUNT + 1)
    ]
    pockets = [
        (f"pocket_{_slug(width)}_width_mm", POCKET, width) for width in POCKET_WIDTHS_MM
    ]
    slots = [
        (f"slot_{_slug(height)}_height_mm", SLOT, height) for height in SLOT_HEIGHTS_MM
    ]
    features: list[CouponFeature] = []
    front = MARGIN_MM

    for row in (holes, pockets, slots):
        placed = []
        left = MARGIN_MM

        for name, kind, size in row:
            half_x, _ = _half_extent(kind, size)
            placed.append(CouponFeature(name, kind, size, left + half_x, 0.0))
            left += 2 * half_x + FEATURE_GAP_MM

        deepest = max(_half_extent(f.kind, f.nominal_mm)[1] for f in placed)
        features.extend(
            CouponFeature(f.name, f.kind, f.nominal_mm, f.x_mm, front + deepest)
            for f in placed
        )
        front += 2 * deepest + ROW_GAP_MM

    return tuple(features)


def _half_extent(kind: str, size: float) -> tuple[float, float]:
    """Half a feature's footprint along X and Y, its slot's cheeks included."""

    if kind == HOLE:
        return size / 2, size / 2

    if kind == POCKET:
        return size / 2, POCKET_LENGTH_MM / 2

    return SLOT_SPAN_MM / 2 + SLOT_CHEEK_MM, SLOT_DEPTH_MM / 2


def _footprint(feature: CouponFeature) -> tuple[float, float, float, float]:
    half_x, half_y = _half_extent(feature.kind, feature.nominal_mm)

    return (
        feature.x_mm - half_x,
        feature.x_mm + half_x,
        feature.y_mm - half_y,
        feature.y_mm + half_y,
    )


def plate_size_mm(
    features: tuple[CouponFeature, ...], tongues: tuple[Tongue, ...] = ()
) -> tuple[float, float, float]:
    """The plate: every feature and tongue and the margin round them, as tall as
    the tallest slot's roof or tongue."""

    boxes = [_footprint(feature) for feature in features] + [
        _tongue_footprint(tongue) for tongue in tongues
    ]
    tallest = max(
        [
            feature.nominal_mm + SLOT_ROOF_MM
            for feature in features
            if feature.kind == SLOT
        ]
        + ([TONGUE_LENGTH_MM] if tongues else [])
    )

    return (
        max(box[1] for box in boxes) + MARGIN_MM,
        max(box[3] for box in boxes) + MARGIN_MM,
        PLATE_MM + tallest,
    )


def _box(
    x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").add(
        cq.Solid.makeBox(
            x[1] - x[0], y[1] - y[0], z[1] - z[0], pnt=cq.Vector(x[0], y[0], z[0])
        )
    )


def build_coupon(fastener: FastenerSpec) -> Coupon:
    """The plate with every feature cut into it or stood on it."""

    features = coupon_features(fastener)
    tongues = coupon_tongues(
        max(_footprint(feature)[3] for feature in features) + ROW_GAP_MM
    )
    length, width, _ = plate_size_mm(features, tongues)
    solid = _box((0.0, length), (0.0, width), (0.0, PLATE_MM))
    solid = solid.cut(_box((-1.0, NOTCH_MM), (-1.0, NOTCH_MM), (-1.0, PLATE_MM + 1.0)))

    for feature in features:
        x, y = feature.x_mm, feature.y_mm

        if feature.kind == HOLE:
            hole = (
                cq.Workplane("XY")
                .workplane(offset=-1.0)
                .center(x, y)
                .circle(feature.nominal_mm / 2)
                .extrude(PLATE_MM + 2.0)
            )
            solid = solid.cut(hole)
        elif feature.kind == POCKET:
            half = feature.nominal_mm / 2
            solid = solid.cut(
                _box(
                    (x - half, x + half),
                    (y - POCKET_LENGTH_MM / 2, y + POCKET_LENGTH_MM / 2),
                    (PLATE_MM - POCKET_DEPTH_MM, PLATE_MM + 1.0),
                )
            )
        else:
            half_block = SLOT_SPAN_MM / 2 + SLOT_CHEEK_MM
            top = PLATE_MM + feature.nominal_mm + SLOT_ROOF_MM
            block = _box(
                (x - half_block, x + half_block),
                (y - SLOT_DEPTH_MM / 2, y + SLOT_DEPTH_MM / 2),
                (0.0, top),
            )
            slot = _box(
                (x - SLOT_SPAN_MM / 2, x + SLOT_SPAN_MM / 2),
                (y - SLOT_DEPTH_MM / 2 - 1.0, y + SLOT_DEPTH_MM / 2 + 1.0),
                (PLATE_MM, PLATE_MM + feature.nominal_mm),
            )
            solid = solid.union(block).cut(slot)

    top = PLATE_MM + TONGUE_LENGTH_MM

    for tongue in tongues:
        x0, x1, y0, y1 = _tongue_footprint(tongue)
        post = _box((x0, x1), (y0, y0 + TONGUE_THICKNESS_MM), (0.0, top))
        stop = _box((x0, x1), (y1 - TONGUE_STOP_MM, y1), (0.0, top))
        solid = solid.union(post).union(stop)

    return Coupon(
        fastener=fastener.identifier,
        features=features,
        tongues=tongues,
        size_mm=plate_size_mm(features, tongues),
        solid=solid,
    )


def _least_wall_mm(coupon: Coupon) -> float:
    """The least plastic between two features' footprints, or between one and
    the plate's edges or the orientation notch."""

    length, width, _ = coupon.size_mm
    boxes = [_footprint(feature) for feature in coupon.features] + [
        _tongue_footprint(tongue) for tongue in coupon.tongues
    ]
    least = float("inf")

    for index, (x0, x1, y0, y1) in enumerate(boxes):
        least = min(
            least,
            x0,
            y0,
            length - x1,
            width - y1,
            max(x0 - NOTCH_MM, y0 - NOTCH_MM),
        )

        for other in boxes[index + 1 :]:
            least = min(
                least, max(other[0] - x1, x0 - other[1], other[2] - y1, y0 - other[3])
            )

    return least


def coupon_checks(
    coupon: Coupon, build_volume_mm: dict[str, float] | None
) -> dict[str, dict[str, Any]]:
    """What a coupon must pass before it is worth printing."""

    length, width, height = coupon.size_mm
    wall = _least_wall_mm(coupon)
    fits = build_volume_mm is None or (
        length <= float(build_volume_mm["x"])
        and width <= float(build_volume_mm["y"])
        and height <= float(build_volume_mm["z"])
    )
    solids = len(coupon.solid.solids().vals())

    return {
        "fits_bed": {
            "passed": fits,
            "detail": f"{length:.1f} x {width:.1f} x {height:.1f} mm",
        },
        "walls_between_features": {
            "passed": wall >= MINIMUM_WALL_MM,
            "detail": f"least {wall:.2f} mm, at least {MINIMUM_WALL_MM:g} mm",
        },
        "one_solid": {
            "passed": solids == 1,
            "detail": f"{solids} solid(s)",
        },
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_coupon_record(
    coupon: Coupon,
    *,
    name: str,
    stl_path: Path,
    output_directory: Path,
    printer_profile_id: str,
    checks: dict[str, dict[str, Any]],
) -> Path:
    """Write ``coupon.json`` beside the coupon's STL."""

    record = {
        "schema_version": COUPON_SCHEMA_VERSION,
        "design_name": name,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "printer_profile_id": printer_profile_id,
        "fastener": coupon.fastener,
        # Built as modelled, so a trial measures the printer itself.
        "hole_compensation_mm": 0.0,
        "size_mm": [round(value, 3) for value in coupon.size_mm],
        "features": [
            {
                "name": feature.name,
                "kind": feature.kind,
                "figure": feature.figure,
                "nominal_mm": feature.nominal_mm,
                "x_mm": round(feature.x_mm, 3),
                "y_mm": round(feature.y_mm, 3),
            }
            for feature in coupon.features
        ],
        "nominal_measurements_mm": {
            feature.name: feature.nominal_mm for feature in coupon.features
        },
        "tongue_orientation": TONGUE_ORIENTATION,
        "tongues": [
            {
                "name": tongue.name,
                "strain": tongue.strain,
                "deflection_mm": round(tongue.deflection_mm, 3),
                "length_mm": TONGUE_LENGTH_MM,
                "thickness_mm": TONGUE_THICKNESS_MM,
                # The strain the engine's own formula gives this tongue, so the
                # record shows the two agree.
                "modelled_strain": round(
                    flexure_for(
                        tongue.deflection_mm, TONGUE_LENGTH_MM, TONGUE_THICKNESS_MM
                    ).strain,
                    6,
                ),
                "x_mm": round(tongue.x_mm, 3),
                "y_mm": round(tongue.y_mm, 3),
            }
            for tongue in coupon.tongues
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


def start_coupon_trial(build_record_path: Path) -> Path:
    """Write the next trial's observation and measurement templates."""

    build = _read(build_record_path)
    trials = build_record_path.parent / "trials"
    number = 1

    while (trials / f"trial-{number:03d}").exists():
        number += 1

    trial = trials / f"trial-{number:03d}"
    trial.mkdir(parents=True)
    observations = {
        check: {"result": "pending", "guidance": guidance, "notes": ""}
        for check, guidance in CHECKS
    }
    observations.update(
        {
            tongue["name"]: {
                "result": "pending",
                "guidance": TONGUE_GUIDANCE,
                "strain": tongue["strain"],
                "notes": "",
            }
            for tongue in build.get("tongues", [])
        }
    )
    measurements = {
        feature["name"]: {
            "nominal_mm": feature["nominal_mm"],
            "value_mm": None,
            "guidance": GUIDANCE[feature["kind"]],
            "notes": "",
        }
        for feature in build["features"]
    }
    (trial / OBSERVATIONS).write_text(
        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
    )
    (trial / MEASUREMENTS).write_text(
        json.dumps(measurements, indent=2) + "\n", encoding="utf-8"
    )

    return trial


def _tongue_results(
    build: dict[str, Any], observed: dict[str, Any]
) -> list[dict[str, Any]]:
    """Each tongue tested, and whether it survived; a skipped one is left out."""

    tongues = []

    for tongue in build.get("tongues", []):
        result = observed.get(tongue["name"], {}).get("result")

        if result not in TONGUE_RESULTS:
            raise ValueError(
                f"{tongue['name']} must be pass, fail or skipped, not {result}"
            )

        if result != "skipped":
            tongues.append(
                {
                    "name": tongue["name"],
                    "strain": tongue["strain"],
                    "survived": result == "pass",
                    "notes": str(observed[tongue["name"]].get("notes", "")),
                }
            )

    return tongues


def complete_coupon_trial(
    trial: Path, *, material_profile_id: str, notes: str = ""
) -> Path:
    """Validate a filled-in trial and write its record. A coupon has no
    disposition: what it measured is the result."""

    record_path = trial / TRIAL_RECORD

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

    features = {feature["name"]: feature for feature in build["features"]}
    measured = _read(trial / MEASUREMENTS)
    measurements = []

    for name, entry in measured.items():
        value = entry.get("value_mm")

        if value is None:
            continue

        if name not in features:
            raise ValueError(f"{name} is not a feature of this coupon")

        if not isinstance(value, int | float) or value <= 0:
            raise ValueError(f"{name} must be a positive number of millimetres")

        feature = features[name]
        measurements.append(
            {
                "name": name,
                "kind": feature["kind"],
                "figure": feature["figure"],
                "nominal_mm": feature["nominal_mm"],
                "value_mm": float(value),
                "notes": str(entry.get("notes", "")),
            }
        )

    tongues = _tongue_results(build, observed)

    if not measurements and not tongues:
        raise ValueError(
            "A coupon trial needs at least one measured feature or tested tongue"
        )

    failed = [entry["check"] for entry in observations if not entry["passed"]]
    record = {
        "schema_version": COUPON_SCHEMA_VERSION,
        "trial_id": trial.name,
        "design_name": build["design_name"],
        "build_record_path": str(build_path),
        "build_record_sha256": sha256(build_path),
        "printer_profile_id": build["printer_profile_id"],
        "material_profile_id": material_profile_id,
        "hole_compensation_mm": build.get("hole_compensation_mm", 0.0),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "failed_checks": failed,
        "observations": observations,
        "measurements": measurements,
        "tongue_orientation": build.get("tongue_orientation", TONGUE_ORIENTATION),
        "tongues": tongues,
        "notes": notes,
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    return record_path
