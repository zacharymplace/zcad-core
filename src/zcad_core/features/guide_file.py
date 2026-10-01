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
BEARINGS = ("top",)
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
            f"nest.bearing must be one of {BEARINGS}, not {bearing!r}; a "
            "ledge for a part with no flat top comes in a later release"
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

    if not spec.part_path.is_file():
        raise ValueError(f"The part's STEP file is missing: {spec.part_path}")

    digest = hashlib.sha256(spec.part_path.read_bytes()).hexdigest()

    if digest != spec.part_sha256:
        raise ValueError(
            f"{spec.part_path.name} has changed since the guide file was written: "
            f"its SHA-256 is {digest}, the file says {spec.part_sha256}"
        )

    # Imported here: reading a model needs CadQuery's STEP reader.
    from zcad_core.hardware.electronics.board_import import load_solids

    solids = load_solids(spec.part_path)

    if not solids:
        raise ValueError(f"{spec.part_path.name} holds no solids")

    if spec.solid_index is not None:
        if spec.solid_index > len(solids):
            raise ValueError(
                f"part.solid_index is {spec.solid_index}; the model has "
                f"{len(solids)} solids"
            )

        chosen = [solids[spec.solid_index - 1]]
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

    if part.silhouette.top_share < MINIMUM_TOP_SHARE:
        errors.append(
            f"The part has no flat top for the plate to bear on: only "
            f"{part.silhouette.top_share:.0%} of its shadow is flat at the top, "
            f"and the least is {MINIMUM_TOP_SHARE:.0%}. A ledge for such a part "
            "comes in a later release"
        )

    if part.solids > 1 and spec.solid_index is None:
        notes.append(
            f"The model has {part.solids} solids and part.solid_index is not "
            "set, so the nest is built around all of them together"
        )

    plan_summary: dict[str, Any] = {}

    if spec.bores and profile is None:
        errors.append(
            "The bores can be checked only against a printer profile: give "
            "--printer-profile"
        )
    elif profile is not None:
        try:
            fits, least_wall, _ = printer_numbers(profile)
        except ValueError as error:
            errors.append(str(error))
        else:
            plan = plan_bores(
                Sections(spec.drill, spec.bushing, spec.bores),
                height_mm=part.height_mm,
                shadow=part.silhouette.points,
                tolerances=fits,
                minimum_wall_mm=least_wall,
                nest_wall_mm=spec.nest_wall_mm,
                plate_thickness_mm=spec.plate_thickness_mm,
                default_plate_mm=DEFAULT_PLATE_MM,
            )
            errors.extend(plan.errors)
            notes.extend(plan.warnings)
            plan_summary = {
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
