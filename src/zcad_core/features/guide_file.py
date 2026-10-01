"""A drill guide described in a file, and the part it is built around.

The file names the part by a STEP path and its hash, says how deep the nest
goes and how thick the walls and plate are, and (in a later release) lists the
bores. The engine does not trust it: :func:`check_guide_data` refuses what
cannot be right, and :func:`check_guide_file` also reads the part and refuses
one that cannot be nested.

Frame: the part's own, centred on its bounding box in X and Y, +X right and +Y
up the page seen from above, with the part's top face at ``z == 0`` and the
part below it. Bore positions, when they come, are on that top plane. All
numbers are millimetres.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.guide_bores import (
    Bore,
    Bushing,
    Drill,
    Sections,
    check_bore_sections,
    parse_sections,
    plan_bores,
    printer_numbers,
)
from zcad_core.features.guide_common import IDENTIFIER, Findings, number, section
from zcad_core.geometry.silhouette import Silhouette, silhouette

GUIDE_SCHEMA_VERSION = "1.0.0"
BEARINGS = ("top", "ledge")
GAP_RANGE_MM = (0.3, 30.0)
DEFAULT_GAP_MM = 1.0
# A ledge nest must rest on at least this much of the part, a design default.
MINIMUM_BEARING_AREA_MM2 = 25.0
# A nest this deep or more leaves no part below it to rest on.
LEDGE_SHOULDER_MM = 0.5
NEST_DEPTH_RANGE_MM = (0.5, 200.0)
WALL_RANGE_MM = (0.8, 20.0)
PLATE_RANGE_MM = (1.2, 40.0)
DEFAULT_WALL_MM = 2.0
DEFAULT_PLATE_MM = 6.0
# A part must have at least this much flat material at its top, as a share of
# its shadow, for the plate to bear on it.
MINIMUM_TOP_SHARE = 0.1
# A nest shallower than this barely locates the part.
SHALLOW_NEST_MM = 3.0
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "part",
        "nest",
        "plate",
        "drill",
        "bushing",
        "bores",
        "needs_review",
    }
)


@dataclass(frozen=True)
class GuideCheck:
    """What a check found: errors make a guide unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    # What reading the part found, when it could be read.
    part: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class GuideSpec:
    """A guide as its file describes it."""

    identifier: str
    name: str
    part_path: Path
    part_sha256: str
    solid_index: int | None
    nest_depth_mm: float
    nest_wall_mm: float
    bearing: str
    # How far the plate stands above the part's top: 0 when it rests on the part.
    nest_gap_mm: float
    # None: sized to the bores (or the default, with none).
    plate_thickness_mm: float | None
    drill: Drill | None
    bushing: Bushing | None
    bores: tuple[Bore, ...]
    source: str
    notes: str
    file_path: Path
    file_sha256: str


@dataclass(frozen=True)
class GuidePart:
    """The part, in the guide's frame, with its shadow."""

    shape: cq.Shape
    silhouette: Silhouette
    height_mm: float
    size_mm: tuple[float, float]
    solids: int
    sha256: str


def _check_partsection(part: Mapping[str, Any], findings: Findings) -> None:
    step = part.get("step")

    if not isinstance(step, str) or not step.strip():
        findings.errors.append("part.step must be the path of a STEP file")

    digest = part.get("sha256")

    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        findings.errors.append(
            "part.sha256 must be the STEP file's SHA-256 as 64 lower-case hex digits"
        )

    index = part.get("solid_index")

    if index is not None and (
        isinstance(index, bool) or not isinstance(index, int) or index < 1
    ):
        findings.errors.append(
            "part.solid_index must be a whole number from 1, or left out for all "
            "the model's solids"
        )


def _check_nest(data: Mapping[str, Any], findings: Findings) -> None:
    nest = section(data, "nest", findings)

    if nest is None:
        return

    number(
        nest,
        "depth_mm",
        "nest",
        findings,
        low=NEST_DEPTH_RANGE_MM[0],
        high=NEST_DEPTH_RANGE_MM[1],
    )
    number(
        nest,
        "wall_mm",
        "nest",
        findings,
        low=WALL_RANGE_MM[0],
        high=WALL_RANGE_MM[1],
        required=False,
    )
    bearing = nest.get("bearing", "top")

    if bearing not in BEARINGS:
        findings.errors.append(
            f"nest.bearing must be one of {BEARINGS}, not {bearing!r}"
        )
    elif bearing == "ledge":
        number(
            nest,
            "gap_mm",
            "nest",
            findings,
            low=GAP_RANGE_MM[0],
            high=GAP_RANGE_MM[1],
            required=False,
        )
    elif nest.get("gap_mm") is not None:
        findings.errors.append(
            "nest.gap_mm is for a ledge bearing: with bearing 'top' the plate "
            "rests on the part and there is no gap"
        )


def check_guide_data(data: Any) -> GuideCheck:
    """Check a guide file's contents without reading the part."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return GuideCheck(("A guide file must hold a JSON object",), ())

    if data.get("schema_version") != GUIDE_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {GUIDE_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    unknown = sorted(set(data) - _TOP_LEVEL)

    if unknown:
        findings.errors.append(f"Unknown field(s): {', '.join(unknown)}")

    if data.get("units", "mm") != "mm":
        findings.errors.append("units must be 'mm'; every number is millimetres")

    identifier = data.get("identifier")

    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        findings.errors.append("identifier must be a name of letters, digits, _ . -")

    if data.get("needs_review"):
        findings.errors.append(
            f"The file is not reviewed: {data['needs_review']}; settle these, then "
            "remove needs_review"
        )

    part = section(data, "part", findings)

    if part is not None:
        _check_partsection(part, findings)

    _check_nest(data, findings)

    plate = section(data, "plate", findings, required=False)

    if plate is not None:
        number(
            plate,
            "thickness_mm",
            "plate",
            findings,
            low=PLATE_RANGE_MM[0],
            high=PLATE_RANGE_MM[1],
            required=False,
        )

    check_bore_sections(data, findings)

    if not data.get("source"):
        findings.warnings.append(
            "No source is stated: say what the part is and where its model came from"
        )

    return GuideCheck(tuple(findings.errors), tuple(findings.warnings))


def read_guide_file(path: Path) -> tuple[Any, str]:
    """A guide file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def guide_from_data(data: Mapping[str, Any], path: Path, sha256: str) -> GuideSpec:
    """Build a guide from checked contents; refuses a file with errors."""

    report = check_guide_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid guide file:\n- " + "\n- ".join(report.errors)
        )

    part, nest = data["part"], data["nest"]
    plate = data.get("plate") or {}
    step = Path(part["step"])
    sections = parse_sections(data)

    return GuideSpec(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        part_path=step if step.is_absolute() else (path.parent / step).resolve(),
        part_sha256=str(part["sha256"]),
        solid_index=part.get("solid_index"),
        nest_depth_mm=float(nest["depth_mm"]),
        nest_wall_mm=float(nest.get("wall_mm", DEFAULT_WALL_MM)),
        bearing=str(nest.get("bearing", "top")),
        nest_gap_mm=(
            float(nest.get("gap_mm", DEFAULT_GAP_MM))
            if nest.get("bearing", "top") == "ledge"
            else 0.0
        ),
        plate_thickness_mm=(
            float(plate["thickness_mm"]) if "thickness_mm" in plate else None
        ),
        drill=sections.drill,
        bushing=sections.bushing,
        bores=sections.bores,
        source=str(data.get("source", "")),
        notes=str(data.get("notes", "")),
        file_path=path,
        file_sha256=sha256,
    )


def load_guide(path: Path) -> GuideSpec:
    """Load and check a guide file, refusing one that cannot be right."""

    data, sha256 = read_guide_file(path)

    return guide_from_data(data, path, sha256)


def load_part(spec: GuideSpec) -> GuidePart:
    """Read the part from its STEP file, refusing one that has changed, and put
    it in the guide's frame with its shadow."""

    return load_part_file(spec.part_path, spec.part_sha256, spec.solid_index)


def load_part_file(
    path: Path, expected_sha256: str | None, solid_index: int | None
) -> GuidePart:
    """A STEP model as a part in the guide's frame, with its shadow. A hash is
    checked when one is given."""

    if not path.is_file():
        raise ValueError(f"The part's STEP file is missing: {path}")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(
            f"{path.name} has changed since the guide file was written: "
            f"its SHA-256 is {digest}, the file says {expected_sha256}"
        )

    # Imported here: reading a model needs CadQuery's STEP reader.
    from zcad_core.hardware.electronics.board_import import load_solids

    solids = load_solids(path)

    if not solids:
        raise ValueError(f"{path.name} holds no solids")

    if solid_index is not None:
        if solid_index > len(solids):
            raise ValueError(
                f"part.solid_index is {solid_index}; the model has {len(solids)} solids"
            )

        chosen = [solids[solid_index - 1]]
    else:
        chosen = solids

    shape: cq.Shape = (
        chosen[0] if len(chosen) == 1 else cq.Compound.makeCompound(chosen)
    )
    bounds = shape.BoundingBox()
    centre_x, centre_y = (
        (bounds.xmin + bounds.xmax) / 2,
        (bounds.ymin + bounds.ymax) / 2,
    )
    shape = shape.moved(cq.Location(cq.Vector(-centre_x, -centre_y, -bounds.zmax)))
    shadow = silhouette(shape)

    return GuidePart(
        shape=shape,
        silhouette=shadow,
        height_mm=bounds.zlen,
        size_mm=(bounds.xlen, bounds.ylen),
        solids=len(chosen),
        sha256=digest,
    )


@dataclass(frozen=True)
class NestOutline:
    """The outline the nest follows, and what a ledge nest rests on."""

    points: tuple[tuple[float, float], ...]
    # For a ledge nest: the part's area under the nest's rim, in mm2.
    bearing_area_mm2: float | None = None


def nest_outline(
    spec: GuideSpec, part: GuidePart, clearance_mm: float = 0.2
) -> NestOutline:
    """The outline of the nest's pocket. A nest that rests on the part's top
    follows the part's whole shadow. A **ledge** nest follows the shadow of only
    the part's top ``nest.depth_mm``, and rests where the part widens below it:
    the part's own shoulder is the ledge."""

    if spec.bearing == "top":
        return NestOutline(part.silhouette.points)

    from zcad_core.geometry.intersection import intersection_volume
    from zcad_core.geometry.outline_prism import outline_prism

    depth = spec.nest_depth_mm
    box = cq.Solid.makeBox(1e4, 1e4, depth, pnt=cq.Vector(-5e3, -5e3, -depth))
    slab = part.shape.intersect(box)

    if slab.isNull() or not slab.Solids():
        raise ValueError(f"The part has no material in its top {depth:g} mm")

    box_slab = slab.BoundingBox()
    centre = (
        (box_slab.xmin + box_slab.xmax) / 2,
        (box_slab.ymin + box_slab.ymax) / 2,
    )
    shadow = silhouette(slab)
    points = tuple((x + centre[0], y + centre[1]) for x, y in shadow.points)
    ring = outline_prism(
        points, -depth - 1.0, -depth, clearance_mm + spec.nest_wall_mm
    ).cut(outline_prism(points, -depth - 2.0, -depth + 1.0, clearance_mm))
    area = intersection_volume(ring.val(), part.shape)  # type: ignore[arg-type]

    return NestOutline(points, area)


def check_guide_file(
    path: Path, profile: Mapping[str, Any] | None = None
) -> GuideCheck:
    """Check a guide file and the part it names."""

    return inspect_guide_file(path, profile)[0]


def inspect_guide_file(
    path: Path, profile: Mapping[str, Any] | None = None
) -> tuple[GuideCheck, GuideSpec | None, GuidePart | None]:
    """Check a guide file and the part it names, and give back the spec and the
    part when they could be read, so a build need not read them again. The bores
    are placed and checked against the printer profile, if one is given."""

    data, sha256 = read_guide_file(path)
    report = check_guide_data(data)

    if not report.valid:
        return report, None, None

    spec = guide_from_data(data, path, sha256)

    try:
        part = load_part(spec)
    except ValueError as error:
        return (
            GuideCheck((*report.errors, str(error)), report.warnings),
            spec,
            None,
        )

    return check_part(spec, part, report.warnings, profile), spec, part


def _check_nest_outline(
    spec: GuideSpec,
    part: GuidePart,
    fits: dict[str, float] | None,
    errors: list[str],
    summary: dict[str, Any],
) -> NestOutline | None:
    """The outline the nest follows; for a ledge, whether the part widens under
    it enough to rest on."""

    clearance = fits["sliding_clearance_per_side"] if fits is not None else 0.2
    summary["bearing"] = spec.bearing

    if spec.bearing == "ledge":
        summary["gap_mm"] = spec.nest_gap_mm

        if spec.nest_depth_mm > part.height_mm - LEDGE_SHOULDER_MM:
            errors.append(
                f"A ledge nest rests on part below it: nest.depth_mm is "
                f"{spec.nest_depth_mm:g} and the part is {part.height_mm:.1f} mm "
                f"high, so there is no shoulder under the nest. Make it at least "
                f"{LEDGE_SHOULDER_MM:g} mm less than the part's height"
            )

            return None

    try:
        outline = nest_outline(spec, part, clearance)
    except ValueError as error:
        errors.append(str(error))

        return None

    if outline.bearing_area_mm2 is not None:
        summary["bearing_area_mm2"] = round(outline.bearing_area_mm2, 1)

        if outline.bearing_area_mm2 < MINIMUM_BEARING_AREA_MM2:
            errors.append(
                f"The part widens under a ledge nest by only "
                f"{outline.bearing_area_mm2:.1f} mm2 where the rim lands, and the "
                f"least is {MINIMUM_BEARING_AREA_MM2:g} mm2: set nest.depth_mm at "
                "a shoulder of the part, where it grows wider"
            )

    return outline


def check_part(
    spec: GuideSpec,
    part: GuidePart,
    warnings: tuple[str, ...] = (),
    profile: Mapping[str, Any] | None = None,
) -> GuideCheck:
    """What the part's own numbers say about the guide's nest and bores."""

    errors: list[str] = []
    notes = list(warnings)

    if spec.nest_depth_mm > part.height_mm + 1e-6:
        errors.append(
            f"nest.depth_mm is {spec.nest_depth_mm:g}, deeper than the part's "
            f"{part.height_mm:.1f} mm height"
        )
    elif spec.nest_depth_mm < SHALLOW_NEST_MM:
        notes.append(
            f"A nest {spec.nest_depth_mm:g} mm deep barely locates the part; "
            f"under {SHALLOW_NEST_MM:g} mm it can ride up and tilt"
        )

    if spec.bearing == "top" and part.silhouette.top_share < MINIMUM_TOP_SHARE:
        errors.append(
            f"The part has no flat top for the plate to bear on: only "
            f"{part.silhouette.top_share:.0%} of its shadow is flat at the top, "
            f"and the least is {MINIMUM_TOP_SHARE:.0%}. Set nest.bearing to "
            "'ledge' and the nest rests on the part's shoulder instead"
        )

    if part.solids > 1 and spec.solid_index is None:
        notes.append(
            f"The model has {part.solids} solids and part.solid_index is not "
            "set, so the nest is built around all of them together"
        )

    plan_summary: dict[str, Any] = {}
    fits: dict[str, float] | None = None
    least_wall = 1.2

    if profile is not None:
        try:
            fits, least_wall, _ = printer_numbers(profile)
        except ValueError as error:
            errors.append(str(error))

    outline = _check_nest_outline(spec, part, fits, errors, plan_summary)

    if spec.bores and profile is None:
        errors.append(
            "The bores can be checked only against a printer profile: give "
            "--printer-profile"
        )
    elif fits is not None and outline is not None:
        plan = plan_bores(
            Sections(spec.drill, spec.bushing, spec.bores),
            height_mm=part.height_mm,
            shadow=outline.points,
            tolerances=fits,
            minimum_wall_mm=least_wall,
            nest_wall_mm=spec.nest_wall_mm,
            plate_thickness_mm=spec.plate_thickness_mm,
            default_plate_mm=DEFAULT_PLATE_MM,
            plate_base_mm=spec.nest_gap_mm,
        )
        errors.extend(plan.errors)
        notes.extend(plan.warnings)
        plan_summary = {
            **plan_summary,
            "plate_thickness_mm": plan.plate_thickness_mm,
            "bores": [item.to_dict() for item in plan.bores],
        }

    summary = {
        **plan_summary,
        "step": str(spec.part_path),
        "sha256": part.sha256,
        "solids": part.solids,
        "size_mm": [round(part.size_mm[0], 3), round(part.size_mm[1], 3)],
        "height_mm": round(part.height_mm, 3),
        "shadow_points": len(part.silhouette.points),
        "shadow_area_mm2": round(part.silhouette.area_mm2, 1),
        "top_flat_share": round(part.silhouette.top_share, 3),
    }

    return GuideCheck(tuple(errors), tuple(notes), summary)


def guide_template(part_step: Path | None = None) -> dict[str, Any]:
    """A valid example guide file to copy and edit. Given a STEP path, it names
    that file and its real hash."""

    digest = (
        hashlib.sha256(part_step.read_bytes()).hexdigest()
        if part_step is not None
        else "0" * 64
    )

    return {
        "schema_version": GUIDE_SCHEMA_VERSION,
        "identifier": "EXAMPLE_GUIDE",
        "name": "Example guide: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what the part is and where its model came from",
        "notes": (
            "The part's frame is its own: centred on its bounding box in X and Y, "
            "+X right and +Y up the page seen from above, with its top face at "
            "z = 0. The nest is a pocket that follows the part's shadow seen from "
            "above, so the part always lifts out. A bore's x_mm and y_mm are where "
            "its axis crosses that top plane; a tilt leans the drill's lower end "
            "toward +Y (tilt_about x) or +X (tilt_about y). The drill's sizes are "
            "yours: the engine looks none of them up."
        ),
        "part": {
            "step": str(part_step) if part_step is not None else "part.step",
            "sha256": digest,
        },
        "nest": {"depth_mm": 8.0, "wall_mm": DEFAULT_WALL_MM, "bearing": "top"},
        "plate": {"thickness_mm": DEFAULT_PLATE_MM},
        "drill": {
            "diameter_mm": 4.0,
            "chuck_diameter_mm": 14.0,
            "depth_mm": 6.0,
            "stickout_mm": 60.0,
        },
        "bores": [
            {"identifier": "B1", "x_mm": 0.0, "y_mm": 0.0, "kind": "printed"},
        ],
    }
