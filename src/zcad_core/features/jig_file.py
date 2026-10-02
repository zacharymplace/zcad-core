"""An insert jig described in a file, and the part it holds.

An insert jig holds a part, and a heat-set insert square over its pocket, while a soldering iron
presses the insert in. It is a nest round the part's shadow with a plate on the part's top face,
and a bore through the plate over each insert. The iron's tip goes down the bore; its shoulder
rests on the plate, so the plate is the depth stop. The file names the part by a STEP path and its
hash, the catalogued insert, the iron's figures with their source, and where each insert goes.
The engine does not trust it: :func:`check_jig_data` refuses what cannot be right, and
:func:`check_jig_file` also reads the part and refuses one that cannot be fitted.

Frame: the part's own, as for a guide: centred on its bounding box in X and Y, with the part's top
face at ``z == 0`` and the part below it. The plate stands on the top face. All numbers are
millimetres. The iron's figures are the user's: the engine states no temperature, time or force.
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
    MINIMUM_TOP_SHARE,
    GuidePart,
    _check_partsection,
    load_part_file,
)
from zcad_core.hardware.fasteners import get_fastener

JIG_SCHEMA_VERSION = "1.0.0"
JIG_KIND = "jig"
DEFAULT_WALL_MM = 2.0
DEPTH_RANGE_MM = (0.5, 200.0)
WALL_RANGE_MM = (0.8, 20.0)
BELOW_FACE_RANGE_MM = (0.0, 20.0)
POSITION_RANGE_MM = (-500.0, 500.0)
TIP_RANGE_MM = (1.0, 15.0)
SHOULDER_RANGE_MM = (2.0, 40.0)
TIP_LENGTH_RANGE_MM = (1.0, 40.0)
POCKET_RANGE_MM = (1.0, 15.0)
POCKET_DEPTH_RANGE_MM = (0.5, 40.0)
# A typed pocket this far from the insert's catalogued size gets a warning; one smaller by more
# than this is refused, because the insert could not be started in it.
POCKET_TOLERANCE_MM = 0.3
MAXIMUM_INSERTS = 24
SHALLOW_POCKET_MM = 3.0
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
        "jig",
        "insert",
        "iron",
        "inserts",
        "needs_review",
    }
)


@dataclass(frozen=True)
class IronSpec:
    """The iron's tip, shoulder and reach, as the user gives them, with their source."""

    tip_diameter_mm: float
    shoulder_diameter_mm: float
    tip_length_mm: float
    source: str


@dataclass(frozen=True)
class InsertSite:
    """Where one insert goes: its place in the part's frame and, if the user gives them, the
    sizes of the pocket the part already has there."""

    identifier: str
    x_mm: float
    y_mm: float
    pocket_diameter_mm: float | None = None
    pocket_depth_mm: float | None = None


@dataclass(frozen=True)
class JigSpec:
    """An insert jig as its file describes it."""

    identifier: str
    name: str
    part_path: Path
    part_sha256: str
    solid_index: int | None
    # None: half the part's height, at least 3 mm, and no more than the part's height.
    depth_mm: float | None
    wall_mm: float
    # How far below the part's face the insert's top ends: 0 is flush.
    depth_below_face_mm: float
    insert_size: str
    iron: IronSpec
    sites: tuple[InsertSite, ...]
    source: str
    notes: str
    file_path: Path
    file_sha256: str


@dataclass(frozen=True)
class JigCheck:
    """What a check found: errors make a jig unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    # What reading the part found, when it could be read.
    part: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


def jig_template(part_step: Path | None = None) -> dict[str, Any]:
    """An example jig file to copy and edit; given a STEP path, it names that file and its real
    hash. The iron's source is a placeholder the check refuses until it is replaced."""

    digest = (
        hashlib.sha256(part_step.read_bytes()).hexdigest()
        if part_step is not None
        else "0" * 64
    )

    return {
        "schema_version": JIG_SCHEMA_VERSION,
        "file_kind": JIG_KIND,
        "identifier": "EXAMPLE_JIG",
        "name": "Example jig: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what the part is and where its model came from",
        "notes": (
            "The part's frame is its own: centred on its bounding box in X and Y, +X right and "
            "+Y up the page seen from above, with its top face at z = 0. The jig is a nest "
            "round the part's shadow with a plate on its top face and a bore over each insert. "
            "The iron figures are yours: measure the iron and say where the figures came from."
        ),
        "part": {
            "step": str(part_step) if part_step is not None else "part.step",
            "sha256": digest,
        },
        "jig": {"wall_mm": DEFAULT_WALL_MM, "depth_below_face_mm": 0.0},
        "insert": {"size": "M3"},
        "iron": {
            "tip_diameter_mm": 3.5,
            "shoulder_diameter_mm": 9.0,
            "tip_length_mm": 6.0,
            "source": "EXAMPLE ONLY: measure your iron's tip and say how",
        },
        "inserts": [{"id": "I1", "x_mm": 0.0, "y_mm": 0.0}],
    }


def _check_jig_section(data: Mapping[str, Any], findings: Findings) -> None:
    jig = section(data, "jig", findings, required=False)

    if jig is None:
        return

    unknown = sorted(set(jig) - {"depth_mm", "wall_mm", "depth_below_face_mm"})

    if unknown:
        findings.errors.append(f"jig has unknown fields: {', '.join(unknown)}")

    number(
        jig,
        "depth_mm",
        "jig",
        findings,
        low=DEPTH_RANGE_MM[0],
        high=DEPTH_RANGE_MM[1],
        required=False,
    )
    number(
        jig,
        "wall_mm",
        "jig",
        findings,
        low=WALL_RANGE_MM[0],
        high=WALL_RANGE_MM[1],
        required=False,
    )
    number(
        jig,
        "depth_below_face_mm",
        "jig",
        findings,
        low=BELOW_FACE_RANGE_MM[0],
        high=BELOW_FACE_RANGE_MM[1],
        required=False,
    )


def _check_insert_section(data: Mapping[str, Any], findings: Findings) -> None:
    insert = section(data, "insert", findings)

    if insert is None:
        return

    unknown = sorted(set(insert) - {"size"})

    if unknown:
        findings.errors.append(f"insert has unknown fields: {', '.join(unknown)}")

    size = insert.get("size")

    if not isinstance(size, str):
        findings.errors.append("insert.size must be a fastener size such as 'M3'")

        return

    try:
        fastener = get_fastener(size)
    except ValueError:
        findings.errors.append(f"insert.size {size!r} is not a catalogued fastener")

        return

    if (
        fastener.heat_set_insert_diameter_mm is None
        or fastener.heat_set_insert_depth_mm is None
    ):
        findings.errors.append(f"The catalogue has no heat-set insert for {size}")


def _check_iron(data: Mapping[str, Any], findings: Findings) -> None:
    iron = section(data, "iron", findings)

    if iron is None:
        return

    unknown = sorted(
        set(iron)
        - {"tip_diameter_mm", "shoulder_diameter_mm", "tip_length_mm", "source"}
    )

    if unknown:
        findings.errors.append(f"iron has unknown fields: {', '.join(unknown)}")

    tip = number(
        iron,
        "tip_diameter_mm",
        "iron",
        findings,
        low=TIP_RANGE_MM[0],
        high=TIP_RANGE_MM[1],
    )
    shoulder = number(
        iron,
        "shoulder_diameter_mm",
        "iron",
        findings,
        low=SHOULDER_RANGE_MM[0],
        high=SHOULDER_RANGE_MM[1],
    )
    number(
        iron,
        "tip_length_mm",
        "iron",
        findings,
        low=TIP_LENGTH_RANGE_MM[0],
        high=TIP_LENGTH_RANGE_MM[1],
    )

    if tip is not None and shoulder is not None and shoulder <= tip:
        findings.errors.append(
            f"iron.shoulder_diameter_mm ({shoulder:g}) must be wider than the tip ({tip:g}): "
            "the shoulder is what rests on the plate"
        )

    source = iron.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.errors.append(
            "iron.source is needed: the iron's figures are yours, so say where they came "
            "from (a measurement, a data sheet)"
        )
    elif source.strip().upper().startswith("EXAMPLE"):
        findings.errors.append(
            "iron.source is still the example's: measure the iron and say how"
        )


def _check_sites(data: Mapping[str, Any], findings: Findings) -> None:
    sites = data.get("inserts")

    if not isinstance(sites, list) or not sites:
        findings.errors.append("inserts must be a list of at least one insert")

        return

    if len(sites) > MAXIMUM_INSERTS:
        findings.errors.append(
            f"inserts has {len(sites)} entries; the most is {MAXIMUM_INSERTS}"
        )

    seen: set[str] = set()

    for index, site in enumerate(sites):
        where = f"inserts[{index}]"

        if not isinstance(site, Mapping):
            findings.errors.append(f"{where} must be an object")

            continue

        unknown = sorted(
            set(site) - {"id", "x_mm", "y_mm", "pocket_diameter_mm", "pocket_depth_mm"}
        )

        if unknown:
            findings.errors.append(f"{where} has unknown fields: {', '.join(unknown)}")

        identifier = site.get("id")

        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            findings.errors.append(
                f"{where}.id must be a name of letters, digits, _ . -"
            )
        elif identifier in seen:
            findings.errors.append(f"{where}.id {identifier!r} is used twice")
        else:
            seen.add(identifier)

        for name in ("x_mm", "y_mm"):
            number(
                site,
                name,
                where,
                findings,
                low=POSITION_RANGE_MM[0],
                high=POSITION_RANGE_MM[1],
            )

        number(
            site,
            "pocket_diameter_mm",
            where,
            findings,
            low=POCKET_RANGE_MM[0],
            high=POCKET_RANGE_MM[1],
            required=False,
        )
        number(
            site,
            "pocket_depth_mm",
            where,
            findings,
            low=POCKET_DEPTH_RANGE_MM[0],
            high=POCKET_DEPTH_RANGE_MM[1],
            required=False,
        )


def check_jig_data(data: Any) -> JigCheck:
    """Check a jig file's contents without reading the part."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return JigCheck(("A jig file must hold a JSON object",), ())

    if data.get("schema_version") != JIG_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {JIG_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    if data.get("file_kind") != JIG_KIND:
        findings.errors.append(
            f"file_kind must be {JIG_KIND!r}: this is not a jig file"
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

    _check_jig_section(data, findings)
    _check_insert_section(data, findings)
    _check_iron(data, findings)
    _check_sites(data, findings)

    if not data.get("source"):
        findings.warnings.append(
            "No source is stated: say what the part is and where its model came from"
        )

    return JigCheck(tuple(findings.errors), tuple(findings.warnings))


def read_jig_file(path: Path) -> tuple[Any, str]:
    """A jig file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def jig_from_data(data: Mapping[str, Any], path: Path, sha256: str) -> JigSpec:
    """A jig from checked contents; refuses a file with errors."""

    report = check_jig_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid jig file:\n- " + "\n- ".join(report.errors)
        )

    part = data["part"]
    jig = data.get("jig") or {}
    iron = data["iron"]
    step = Path(part["step"])
    depth = jig.get("depth_mm")

    return JigSpec(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        part_path=step if step.is_absolute() else (path.parent / step).resolve(),
        part_sha256=str(part["sha256"]),
        solid_index=part.get("solid_index"),
        depth_mm=None if depth is None else float(depth),
        wall_mm=float(jig.get("wall_mm", DEFAULT_WALL_MM)),
        depth_below_face_mm=float(jig.get("depth_below_face_mm", 0.0)),
        insert_size=str(data["insert"]["size"]),
        iron=IronSpec(
            float(iron["tip_diameter_mm"]),
            float(iron["shoulder_diameter_mm"]),
            float(iron["tip_length_mm"]),
            str(iron["source"]).strip(),
        ),
        sites=tuple(
            InsertSite(
                str(site["id"]),
                float(site["x_mm"]),
                float(site["y_mm"]),
                _optional(site, "pocket_diameter_mm"),
                _optional(site, "pocket_depth_mm"),
            )
            for site in data["inserts"]
        ),
        source=str(data.get("source", "")),
        notes=str(data.get("notes", "")),
        file_path=path,
        file_sha256=sha256,
    )


def _optional(site: Mapping[str, Any], name: str) -> float | None:
    value = site.get(name)

    return None if value is None else float(value)


def load_jig(path: Path) -> JigSpec:
    """Load and check a jig file, refusing one that cannot be right."""

    data, sha256 = read_jig_file(path)

    return jig_from_data(data, path, sha256)


def load_jig_part(spec: JigSpec) -> GuidePart:
    """Read the part from its STEP file, refusing one that has changed."""

    return load_part_file(spec.part_path, spec.part_sha256, spec.solid_index)


def insert_figures(spec: JigSpec) -> tuple[float, float]:
    """The catalogued insert's diameter and length."""

    fastener = get_fastener(spec.insert_size)

    if (
        fastener.heat_set_insert_diameter_mm is None
        or fastener.heat_set_insert_depth_mm is None
    ):
        raise ValueError(f"The catalogue has no heat-set insert for {spec.insert_size}")

    return fastener.heat_set_insert_diameter_mm, fastener.heat_set_insert_depth_mm


def pocket_depth_mm(spec: JigSpec, part: GuidePart) -> float:
    """How far the nest climbs the part from its top: the file's, or half the part's height, at
    least 3 mm and never more than the part's height."""

    if spec.depth_mm is not None:
        return spec.depth_mm

    return min(max(round(part.height_mm / 2, 1), SHALLOW_POCKET_MM), part.height_mm)


def check_jig_file(path: Path, profile: Mapping[str, Any] | None = None) -> JigCheck:
    """Check a jig file and the part it names."""

    return inspect_jig_file(path, profile)[0]


def inspect_jig_file(
    path: Path, profile: Mapping[str, Any] | None = None
) -> tuple[JigCheck, JigSpec | None, GuidePart | None]:
    """Check a jig file and the part it names, and give back the spec and the part when they
    could be read, so a build need not read them again."""

    data, sha256 = read_jig_file(path)
    report = check_jig_data(data)

    if not report.valid:
        return report, None, None

    spec = jig_from_data(data, path, sha256)

    try:
        part = load_jig_part(spec)
    except ValueError as error:
        return JigCheck((*report.errors, str(error)), report.warnings), spec, None

    return check_part(spec, part, report.warnings, profile), spec, part


def check_part(
    spec: JigSpec,
    part: GuidePart,
    warnings: tuple[str, ...] = (),
    profile: Mapping[str, Any] | None = None,
) -> JigCheck:
    """What the part's own numbers, the insert and the printer say about the jig."""

    errors: list[str] = []
    notes = list(warnings)
    depth = pocket_depth_mm(spec, part)

    if depth > part.height_mm + 1e-6:
        errors.append(
            f"jig.depth_mm is {depth:g}, deeper than the part's {part.height_mm:.1f} mm height"
        )

    if part.silhouette.top_share < MINIMUM_TOP_SHARE:
        errors.append(
            f"The part has no flat top for the plate to stand on: only "
            f"{part.silhouette.top_share:.0%} of its shadow is flat at the top, and the least "
            f"is {MINIMUM_TOP_SHARE:.0%}"
        )

    if part.solids > 1 and spec.solid_index is None:
        notes.append(
            f"The model has {part.solids} solids and part.solid_index is not set, so the "
            "jig is built around all of them together"
        )

    diameter, length = insert_figures(spec)
    needed = spec.depth_below_face_mm + length

    if needed > part.height_mm + 1e-6:
        errors.append(
            f"A {spec.insert_size} insert {length:g} mm long, ending {spec.depth_below_face_mm:g} "
            f"mm below the face, needs {needed:g} mm of part; the part is "
            f"{part.height_mm:.1f} mm tall"
        )

    errors.extend(_site_errors(spec, diameter, needed, notes))

    if profile is not None:
        try:
            _, least_wall, _ = printer_numbers(profile)
        except ValueError as error:
            errors.append(str(error))
        else:
            if spec.wall_mm < least_wall:
                errors.append(
                    f"jig.wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm "
                    "minimum wall"
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
        "insert": {
            "size": spec.insert_size,
            "diameter_mm": diameter,
            "length_mm": length,
        },
    }

    return JigCheck(tuple(errors), tuple(notes), summary)


def _site_errors(
    spec: JigSpec, diameter: float, needed: float, notes: list[str]
) -> list[str]:
    """What the typed pockets say against the catalogued insert."""

    errors: list[str] = []

    for site in spec.sites:
        size = site.pocket_diameter_mm

        if size is not None:
            if size < diameter - POCKET_TOLERANCE_MM:
                errors.append(
                    f"{site.identifier}: the pocket is {size:g} mm across, too small for a "
                    f"{spec.insert_size} insert, whose catalogued size is {diameter:g} mm"
                )
            elif abs(size - diameter) > POCKET_TOLERANCE_MM:
                notes.append(
                    f"{site.identifier}: the pocket is {size:g} mm across and the "
                    f"{spec.insert_size} insert's catalogued size is {diameter:g} mm"
                )

        if site.pocket_depth_mm is not None and site.pocket_depth_mm < needed - 1e-6:
            errors.append(
                f"{site.identifier}: the pocket is {site.pocket_depth_mm:g} mm deep, too "
                f"shallow for the insert's {needed:g} mm below the face"
            )

        if size is None and site.pocket_depth_mm is None:
            notes.append(
                f"{site.identifier}: no pocket is given, so the part's pocket there is not "
                "checked against the insert"
            )

    return errors
