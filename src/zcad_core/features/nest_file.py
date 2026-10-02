"""A holding nest described in a file, and the part it holds.

A holding nest is a tray: a floor under a part and a wall round its shadow, for holding the
part while it is sanded, glued or marked. The file names the part by a STEP path and its hash,
says how deep the pocket is, how thick the wall and floor are, how far the floor reaches past the
wall (the flange), and what features it has. The engine does not trust it: :func:`check_nest_data`
refuses what cannot be right, and :func:`check_nest_file` also reads the part and refuses one that
cannot be nested.

Frame: the part's own, as for a guide: centred on its bounding box in X and Y, with the part's top
face at ``z == 0`` and the part below it. The floor's top is the part's bottom, ``z == -height``,
and the wall climbs ``depth_mm`` from there. All numbers are millimetres.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.guide_common import IDENTIFIER, Findings, number, section
from zcad_core.features.guide_file import (
    GuidePart,
    _check_partsection,
    load_part_file,
)

NEST_SCHEMA_VERSION = "1.0.0"
NEST_KIND = "nest"
DEFAULT_WALL_MM = 2.0
DEFAULT_FLOOR_MM = 2.0
DEFAULT_FLANGE_MM = 8.0
DEFAULT_NOTCHES = 2
MAXIMUM_NOTCHES = 4
# A finger notch is this wide and needs this much straight wall past each of its ends: the
# engine's own design choices.
NOTCH_WIDTH_MM = 12.0
NOTCH_MARGIN_MM = 3.0
# A pocket shallower than this barely holds the part.
SHALLOW_POCKET_MM = 3.0
DEPTH_RANGE_MM = (0.5, 200.0)
WALL_RANGE_MM = (0.8, 20.0)
FLOOR_RANGE_MM = (0.8, 20.0)
FLANGE_RANGE_MM = (0.0, 40.0)
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "file_kind",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "part",
        "nest",
        "features",
        "needs_review",
    }
)
_FEATURES = frozenset({"finger_notches", "lip", "strap", "label"})
DEFAULT_LIP_TABS = 2
MAXIMUM_LIP_TABS = 4
DEFAULT_LIP_OVERHANG_MM = 0.6
LIP_OVERHANG_RANGE_MM = (0.3, 2.0)
STRAP_RANGE_MM = (3.0, 60.0)
STRAP_THICKNESS_RANGE_MM = (0.3, 6.0)


@dataclass(frozen=True)
class StrapSpec:
    """A strap the nest is slotted for: the user's own figures, with where they came from."""

    width_mm: float
    thickness_mm: float
    source: str


@dataclass(frozen=True)
class NestSpec:
    """A holding nest as its file describes it."""

    identifier: str
    name: str
    part_path: Path
    part_sha256: str
    solid_index: int | None
    # None: half the part's height, at least 3 mm, and no more than the part's height.
    depth_mm: float | None
    wall_mm: float
    floor_mm: float
    flange_mm: float
    finger_notches: int
    source: str
    notes: str
    file_path: Path
    file_sha256: str
    # Retaining lip: 0 tabs is no lip. A lip's wall climbs the part's whole height.
    lip_tabs: int = 0
    lip_overhang_mm: float = DEFAULT_LIP_OVERHANG_MM
    strap: StrapSpec | None = None
    label: str | None = None


@dataclass(frozen=True)
class NestCheck:
    """What a check found: errors make a nest unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    # What reading the part found, when it could be read.
    part: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


def nest_template(part_step: Path | None = None) -> dict[str, Any]:
    """A valid example nest file to copy and edit; given a STEP path, it names that file and
    its real hash."""

    digest = (
        hashlib.sha256(part_step.read_bytes()).hexdigest()
        if part_step is not None
        else "0" * 64
    )

    return {
        "schema_version": NEST_SCHEMA_VERSION,
        "file_kind": NEST_KIND,
        "identifier": "EXAMPLE_NEST",
        "name": "Example nest: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what the part is and where its model came from",
        "notes": (
            "The part's frame is its own: centred on its bounding box in X and Y, +X right "
            "and +Y up the page seen from above, with its top face at z = 0. The nest is a "
            "tray: the part stands on its floor in a pocket that follows its shadow seen from "
            "above, so it always lifts straight out."
        ),
        "part": {
            "step": str(part_step) if part_step is not None else "part.step",
            "sha256": digest,
        },
        "nest": {
            "wall_mm": DEFAULT_WALL_MM,
            "floor_mm": DEFAULT_FLOOR_MM,
            "flange_mm": DEFAULT_FLANGE_MM,
        },
        "features": {"finger_notches": DEFAULT_NOTCHES},
    }


def _check_nest_section(data: Mapping[str, Any], findings: Findings) -> None:
    nest = section(data, "nest", findings)

    if nest is None:
        return

    unknown = sorted(set(nest) - {"depth_mm", "wall_mm", "floor_mm", "flange_mm"})

    if unknown:
        findings.errors.append(f"nest has unknown fields: {', '.join(unknown)}")

    number(
        nest,
        "depth_mm",
        "nest",
        findings,
        low=DEPTH_RANGE_MM[0],
        high=DEPTH_RANGE_MM[1],
        required=False,
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
    number(
        nest,
        "floor_mm",
        "nest",
        findings,
        low=FLOOR_RANGE_MM[0],
        high=FLOOR_RANGE_MM[1],
        required=False,
    )
    number(
        nest,
        "flange_mm",
        "nest",
        findings,
        low=FLANGE_RANGE_MM[0],
        high=FLANGE_RANGE_MM[1],
        required=False,
    )


def _check_features(data: Mapping[str, Any], findings: Findings) -> None:
    features = section(data, "features", findings, required=False)

    if features is None:
        return

    unknown = sorted(set(features) - _FEATURES)

    if unknown:
        findings.errors.append(f"features has unknown fields: {', '.join(unknown)}")

    notches = features.get("finger_notches", DEFAULT_NOTCHES)

    if isinstance(notches, bool) or not isinstance(notches, int):
        findings.errors.append(
            f"features.finger_notches must be a whole number, not {notches!r}"
        )
    elif not 0 <= notches <= MAXIMUM_NOTCHES:
        findings.errors.append(
            f"features.finger_notches is {notches}, outside 0 to {MAXIMUM_NOTCHES}"
        )

    _check_lip(data, features, findings)
    _check_strap(features, findings)

    label = features.get("label")

    if label is not None and (
        not isinstance(label, str) or not label.strip() or not label.isprintable()
    ):
        findings.errors.append("features.label must be a line of printable text")
    elif isinstance(label, str) and len(label) > 24:
        findings.errors.append(
            f"features.label is {len(label)} characters; the most is 24"
        )


def _check_lip(
    data: Mapping[str, Any], features: Mapping[str, Any], findings: Findings
) -> None:
    lip = features.get("lip")

    if lip is None:
        return

    if not isinstance(lip, Mapping):
        findings.errors.append("features.lip must be an object")

        return

    unknown = sorted(set(lip) - {"tabs", "overhang_mm"})

    if unknown:
        findings.errors.append(f"features.lip has unknown fields: {', '.join(unknown)}")

    tabs = lip.get("tabs", DEFAULT_LIP_TABS)

    if isinstance(tabs, bool) or not isinstance(tabs, int):
        findings.errors.append(
            f"features.lip.tabs must be a whole number, not {tabs!r}"
        )
    elif not 1 <= tabs <= MAXIMUM_LIP_TABS:
        findings.errors.append(
            f"features.lip.tabs is {tabs}, outside 1 to {MAXIMUM_LIP_TABS}"
        )

    number(
        lip,
        "overhang_mm",
        "features.lip",
        findings,
        low=LIP_OVERHANG_RANGE_MM[0],
        high=LIP_OVERHANG_RANGE_MM[1],
        required=False,
    )
    nest = data.get("nest")

    if isinstance(nest, Mapping) and nest.get("depth_mm") is not None:
        findings.errors.append(
            "nest.depth_mm cannot be set with a lip: a lip's wall climbs the part's whole height"
        )


def _check_strap(features: Mapping[str, Any], findings: Findings) -> None:
    strap = features.get("strap")

    if strap is None:
        return

    if not isinstance(strap, Mapping):
        findings.errors.append("features.strap must be an object")

        return

    unknown = sorted(set(strap) - {"width_mm", "thickness_mm", "source"})

    if unknown:
        findings.errors.append(
            f"features.strap has unknown fields: {', '.join(unknown)}"
        )

    number(
        strap,
        "width_mm",
        "features.strap",
        findings,
        low=STRAP_RANGE_MM[0],
        high=STRAP_RANGE_MM[1],
    )
    number(
        strap,
        "thickness_mm",
        "features.strap",
        findings,
        low=STRAP_THICKNESS_RANGE_MM[0],
        high=STRAP_THICKNESS_RANGE_MM[1],
    )

    if not strap.get("source"):
        findings.errors.append(
            "features.strap.source is needed: the strap's size is your figure, so say where it "
            "came from (a measurement, a data sheet)"
        )


def check_nest_data(data: Any) -> NestCheck:
    """Check a nest file's contents without reading the part."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return NestCheck(("A nest file must hold a JSON object",), ())

    if data.get("schema_version") != NEST_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {NEST_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    if data.get("file_kind") != NEST_KIND:
        findings.errors.append(
            f"file_kind must be {NEST_KIND!r}: this is not a nest file"
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

    _check_nest_section(data, findings)
    _check_features(data, findings)

    if not data.get("source"):
        findings.warnings.append(
            "No source is stated: say what the part is and where its model came from"
        )

    return NestCheck(tuple(findings.errors), tuple(findings.warnings))


def read_nest_file(path: Path) -> tuple[Any, str]:
    """A nest file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def nest_from_data(data: Mapping[str, Any], path: Path, sha256: str) -> NestSpec:
    """A nest from checked contents; refuses a file with errors."""

    report = check_nest_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid nest file:\n- " + "\n- ".join(report.errors)
        )

    part, nest = data["part"], data["nest"]
    features = data.get("features") or {}
    step = Path(part["step"])
    depth = nest.get("depth_mm")
    lip = features.get("lip")
    strap = features.get("strap")
    label = features.get("label")

    return NestSpec(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        part_path=step if step.is_absolute() else (path.parent / step).resolve(),
        part_sha256=str(part["sha256"]),
        solid_index=part.get("solid_index"),
        depth_mm=None if depth is None else float(depth),
        wall_mm=float(nest.get("wall_mm", DEFAULT_WALL_MM)),
        floor_mm=float(nest.get("floor_mm", DEFAULT_FLOOR_MM)),
        flange_mm=float(nest.get("flange_mm", DEFAULT_FLANGE_MM)),
        finger_notches=int(features.get("finger_notches", DEFAULT_NOTCHES)),
        source=str(data.get("source", "")),
        notes=str(data.get("notes", "")),
        file_path=path,
        file_sha256=sha256,
        lip_tabs=0 if lip is None else int(lip.get("tabs", DEFAULT_LIP_TABS)),
        lip_overhang_mm=(
            DEFAULT_LIP_OVERHANG_MM
            if lip is None
            else float(lip.get("overhang_mm", DEFAULT_LIP_OVERHANG_MM))
        ),
        strap=(
            None
            if strap is None
            else StrapSpec(
                float(strap["width_mm"]),
                float(strap["thickness_mm"]),
                str(strap["source"]),
            )
        ),
        label=None if label is None else str(label).strip(),
    )


def load_nest(path: Path) -> NestSpec:
    """Load and check a nest file, refusing one that cannot be right."""

    data, sha256 = read_nest_file(path)

    return nest_from_data(data, path, sha256)


def load_nest_part(spec: NestSpec) -> GuidePart:
    """Read the part from its STEP file, refusing one that has changed, and put it in the
    nest's frame with its shadow."""

    return load_part_file(spec.part_path, spec.part_sha256, spec.solid_index)


def pocket_depth_mm(spec: NestSpec, part: GuidePart) -> float:
    """How far the wall climbs the part: the file's, or half the part's height, at least
    3 mm and never more than the part's height."""

    if spec.lip_tabs:
        return part.height_mm

    if spec.depth_mm is not None:
        return spec.depth_mm

    return min(max(round(part.height_mm / 2, 1), SHALLOW_POCKET_MM), part.height_mm)


def check_nest_file(path: Path, profile: Mapping[str, Any] | None = None) -> NestCheck:
    """Check a nest file and the part it names."""

    return inspect_nest_file(path, profile)[0]


def inspect_nest_file(
    path: Path, profile: Mapping[str, Any] | None = None
) -> tuple[NestCheck, NestSpec | None, GuidePart | None]:
    """Check a nest file and the part it names, and give back the spec and the part when
    they could be read, so a build need not read them again."""

    data, sha256 = read_nest_file(path)
    report = check_nest_data(data)

    if not report.valid:
        return report, None, None

    spec = nest_from_data(data, path, sha256)

    try:
        part = load_nest_part(spec)
    except ValueError as error:
        return NestCheck((*report.errors, str(error)), report.warnings), spec, None

    return check_part(spec, part, report.warnings, profile), spec, part


def _feature_errors(
    spec: NestSpec,
    part: GuidePart,
    profile: Mapping[str, Any],
    clearance: float,
    least_wall: float,
) -> list[str]:
    """What stops the lip, strap slots and label being built on this part."""

    # Imported here: nest_features reads the spec's types from this module.
    from zcad_core.features.nest_features import (
        DEFAULT_EMBOSS_MM,
        DEFAULT_TEXT_SIZE_MM,
        lip_errors,
        plan_label,
        plan_strap,
    )

    points = part.silhouette.points
    slots, errors = plan_strap(spec, points, clearance, least_wall)
    minimums = profile.get("minimums_mm", {})
    _, label_errors = plan_label(
        spec,
        points,
        clearance,
        float(minimums.get("text_size", DEFAULT_TEXT_SIZE_MM)),
        float(minimums.get("emboss_height", DEFAULT_EMBOSS_MM)),
        slots,
    )

    return [
        *errors,
        *label_errors,
        *lip_errors(spec, part.height_mm, part.silhouette.top_share, clearance),
    ]


def check_part(
    spec: NestSpec,
    part: GuidePart,
    warnings: tuple[str, ...] = (),
    profile: Mapping[str, Any] | None = None,
) -> NestCheck:
    """What the part's own numbers say about the nest."""

    errors: list[str] = []
    notes = list(warnings)
    depth = pocket_depth_mm(spec, part)

    if depth > part.height_mm + 1e-6:
        errors.append(
            f"nest.depth_mm is {depth:g}, deeper than the part's {part.height_mm:.1f} mm height"
        )
    elif depth < SHALLOW_POCKET_MM:
        notes.append(
            f"A pocket {depth:g} mm deep barely holds the part; under "
            f"{SHALLOW_POCKET_MM:g} mm it can ride up and tilt"
        )

    if part.solids > 1 and spec.solid_index is None:
        notes.append(
            f"The model has {part.solids} solids and part.solid_index is not set, so the "
            "nest is built around all of them together"
        )

    if profile is not None:
        try:
            fits, least_wall, least_floor = printer_numbers(profile)
        except ValueError as error:
            errors.append(str(error))
        else:
            errors.extend(
                _feature_errors(
                    spec, part, profile, fits["sliding_clearance_per_side"], least_wall
                )
            )

            if spec.wall_mm < least_wall:
                errors.append(
                    f"nest.wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm "
                    "minimum wall"
                )

            if spec.floor_mm < least_floor:
                errors.append(
                    f"nest.floor_mm is {spec.floor_mm:g}, under the printer's "
                    f"{least_floor:g} mm minimum floor"
                )

    summary = {
        "step": str(spec.part_path),
        "sha256": part.sha256,
        "solids": part.solids,
        "size_mm": [round(part.size_mm[0], 3), round(part.size_mm[1], 3)],
        "height_mm": round(part.height_mm, 3),
        "shadow_points": len(part.silhouette.points),
        "shadow_area_mm2": round(part.silhouette.area_mm2, 1),
        "pocket_depth_mm": round(depth, 3),
    }

    return NestCheck(tuple(errors), tuple(notes), summary)
