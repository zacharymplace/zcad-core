"""A housing file: what is worn, the style of housing, and its walls.

A housing file names the thing to house by hash, as a PCB test fixture's names its
board, so a housing is refused if what it was built round has changed:

- a ``cradle`` houses a **sealed device**, which a wearable file (a caliper capture,
  see :mod:`zcad_core.hardware.wearables.capture`) describes; or
- a ``case`` houses a **board**, which a board file describes.

A third style, ``shell`` (the existing snap-shell clips), joins when there is a way
of wearing one, in the next release. Nothing here says how the housing is worn: this
release builds one you hold.

Frame, for a cradle: the device's own, from the capture: it lies with the face away
from the body up, centred, its length along X and its width along Y, its underside at
``z == 0`` and its top face at ``z == thickness``; the floor is below ``z == 0``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.guide_common import IDENTIFIER, Findings, number, section
from zcad_core.features.housing_wear import (
    FIGURES,
    PATCH_RANGE_MM,
    WEAR_KINDS,
    Wear,
    conflicts,
)
from zcad_core.hardware import load_board
from zcad_core.hardware.electronics.board_file import BoardFileSpec
from zcad_core.hardware.wearables import WearableCapture, check_capture, load_capture

HOUSING_SCHEMA_VERSION = "1.0.0"
STYLES = ("cradle", "case")
EDGES = ("north", "south", "east", "west")
DEFAULT_WALL_MM = 1.2
DEFAULT_FLOOR_MM = 1.2
DEFAULT_LID_MM = 2.0
DEFAULT_CLEARANCE_MM = 0.3
DEFAULT_CORNER_RADIUS_MM = 1.0
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "style",
        "wearable",
        "board",
        "wall_mm",
        "floor_mm",
        "lid_mm",
        "clearance_mm",
        "corner_radius_mm",
        "retention_edges",
        "wear",
        "needs_review",
    }
)


@dataclass(frozen=True)
class HousingSpec:
    """A housing as its file describes it."""

    identifier: str
    name: str
    style: str
    input_path: Path
    input_sha256: str
    wall_mm: float
    floor_mm: float
    lid_mm: float
    clearance_mm: float
    corner_radius_mm: float
    retention_edges: tuple[str, ...]
    wear: tuple[Wear, ...]
    source: str
    notes: str
    file_path: Path
    file_sha256: str


@dataclass(frozen=True)
class HousingCheck:
    """What a check found: errors make a housing unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


_EXAMPLE_WEAR: dict[str, dict[str, Any]] = {
    "strap": {"strap_width_mm": 20.0, "bar_diameter_mm": 1.8},
    "band": {"band_width_mm": 20.0, "band_thickness_mm": 2.0},
    "clip": {"belt_thickness_mm": 4.0},
    "adhesive": {"patch_mm": [60.0, 45.0]},
    "lanyard": {"cord_diameter_mm": 3.0},
}


def housing_template(
    style: str, input_file: Path | None = None, wear: tuple[str, ...] = ()
) -> dict[str, Any]:
    """An example housing file to edit, naming ``input_file`` by its real hash if
    one is given."""

    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")

    digest = (
        hashlib.sha256(input_file.read_bytes()).hexdigest()
        if input_file is not None and input_file.is_file()
        else "0" * 64
    )
    key = "wearable" if style == "cradle" else "board"
    file = str(input_file) if input_file is not None else f"{key}.json"
    data: dict[str, Any] = {
        "schema_version": HOUSING_SCHEMA_VERSION,
        "identifier": "EXAMPLE_HOUSING",
        "name": "Example housing: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what this housing is for and what it houses",
        "style": style,
        key: {"file": file, "sha256": digest},
        "wall_mm": DEFAULT_WALL_MM,
        "floor_mm": DEFAULT_FLOOR_MM,
    }

    if style == "cradle":
        data["clearance_mm"] = DEFAULT_CLEARANCE_MM
        data["retention_edges"] = list(EDGES)
    else:
        data["lid_mm"] = DEFAULT_LID_MM
        data["corner_radius_mm"] = DEFAULT_CORNER_RADIUS_MM

    if wear:
        unknown = [kind for kind in wear if kind not in WEAR_KINDS]

        if unknown:
            raise ValueError(f"wear must be drawn from {WEAR_KINDS}, not {unknown}")

        data["wear"] = [
            {
                "kind": kind,
                **_EXAMPLE_WEAR[kind],
                "source": (
                    "EXAMPLE ONLY: where these figures came from, such as the strap "
                    "or band you will use, measured"
                ),
            }
            for kind in wear
        ]

    return data


def _check_input(data: Mapping[str, Any], findings: Findings) -> None:
    style = data.get("style")
    wanted, other = (
        ("wearable", "board") if style == "cradle" else ("board", "wearable")
    )

    if style in STYLES and data.get(other) is not None:
        findings.errors.append(f"a {style} houses a {wanted}: remove {other!r}")

    entry = section(data, wanted, findings) if style in STYLES else None

    if entry is None:
        return

    file = entry.get("file")

    if not isinstance(file, str) or not file.strip():
        findings.errors.append(f"{wanted}.file must name the file")

    digest = entry.get("sha256")

    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        findings.errors.append(
            f"{wanted}.sha256 must be the file's SHA-256 as 64 lower-case hex digits"
        )


def check_housing_data(data: Any) -> HousingCheck:
    """Check a housing file's contents without reading what it names."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return HousingCheck(("A housing file must hold a JSON object",), ())

    if data.get("schema_version") != HOUSING_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {HOUSING_SCHEMA_VERSION!r}, not "
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

    if data.get("style") not in STYLES:
        findings.errors.append(
            f"style must be one of {STYLES}, not {data.get('style')!r}"
        )

    if data.get("needs_review"):
        findings.errors.append(
            f"The file is not reviewed: {data['needs_review']}; settle these, then "
            "remove needs_review"
        )

    _check_input(data, findings)

    for name, low, high in (
        ("wall_mm", 0.4, 10.0),
        ("floor_mm", 0.4, 10.0),
        ("lid_mm", 0.4, 10.0),
        ("clearance_mm", 0.05, 2.0),
        ("corner_radius_mm", 0.0, 20.0),
    ):
        number(data, name, "", findings, low=low, high=high, required=False)

    _check_edges(data, findings)
    _check_wear(data, findings)

    if not str(data.get("source", "")).strip():
        findings.warnings.append(
            "No source is stated: say what this housing is for and what it houses"
        )

    return HousingCheck(tuple(findings.errors), tuple(findings.warnings))


def _check_wear(data: Mapping[str, Any], findings: Findings) -> None:
    """The ways of wearing: each a kind, the figures it needs, and their source."""

    entries = data.get("wear")

    if entries is None:
        return

    if not isinstance(entries, list):
        findings.errors.append("wear must be a list of ways of wearing")

        return

    kinds: list[str] = []

    for index, entry in enumerate(entries):
        where = f"wear[{index}]"

        if not isinstance(entry, Mapping):
            findings.errors.append(f"{where} must be an object")

            continue

        kind = entry.get("kind")

        if kind not in WEAR_KINDS:
            findings.errors.append(f"{where}.kind must be one of {WEAR_KINDS}")

            continue

        if kind in kinds:
            findings.errors.append(f"{where}: {kind} is listed twice")

        kinds.append(str(kind))
        _check_wear_entry(entry, str(kind), where, findings)

    findings.errors.extend(conflicts(kinds))


def _check_wear_entry(
    entry: Mapping[str, Any], kind: str, where: str, findings: Findings
) -> None:
    allowed = {"kind", "source", *FIGURES[kind]}

    if kind == "adhesive":
        allowed |= {"patch_mm", "corner_radius_mm"}

    unknown = sorted(set(entry) - allowed)

    if unknown:
        findings.errors.append(f"{where} has unknown fields: {', '.join(unknown)}")

    for name, (low, high) in FIGURES[kind].items():
        number(entry, name, where, findings, low=low, high=high)

    if kind == "adhesive":
        patch = entry.get("patch_mm")

        if (
            not isinstance(patch, list)
            or len(patch) != 2
            or not all(
                isinstance(v, int | float)
                and not isinstance(v, bool)
                and PATCH_RANGE_MM[0] <= v <= PATCH_RANGE_MM[1]
                for v in patch
            )
        ):
            findings.errors.append(
                f"{where}.patch_mm must be [width, depth] in millimetres, each from "
                f"{PATCH_RANGE_MM[0]:g} to {PATCH_RANGE_MM[1]:g}"
            )

        number(
            entry,
            "corner_radius_mm",
            where,
            findings,
            low=0.5,
            high=50.0,
            required=False,
        )

    source = entry.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.errors.append(
            f"{where}.source must say where the figures came from: they are yours, "
            "and the engine has none of its own"
        )
    elif source.strip().upper().startswith("EXAMPLE"):
        findings.errors.append(
            f"{where}.source is still the template's example: replace the figures "
            "and say where they came from"
        )


def _check_edges(data: Mapping[str, Any], findings: Findings) -> None:
    edges = data.get("retention_edges")

    if edges is None:
        return

    if data.get("style") != "cradle":
        findings.errors.append("retention_edges is for a cradle")

        return

    if (
        not isinstance(edges, list)
        or not all(edge in EDGES for edge in edges)
        or len(set(edges)) != len(edges)
    ):
        findings.errors.append(f"retention_edges must be a list drawn from {EDGES}")
    elif len(edges) < 3:
        findings.errors.append(
            "retention_edges needs at least three edges: two hold a device against "
            "lifting but not against rocking"
        )


def read_housing_file(path: Path) -> tuple[Any, str]:
    """A housing file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def housing_from_data(data: Mapping[str, Any], path: Path, sha256: str) -> HousingSpec:
    """A housing from checked contents; refuses a file with errors."""

    report = check_housing_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid housing file:\n- " + "\n- ".join(report.errors)
        )

    style = str(data["style"])
    entry = data["wearable"] if style == "cradle" else data["board"]
    input_path = Path(entry["file"])
    edges = data.get("retention_edges", list(EDGES) if style == "cradle" else [])

    return HousingSpec(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        style=style,
        input_path=(
            input_path
            if input_path.is_absolute()
            else (path.parent / input_path).resolve()
        ),
        input_sha256=str(entry["sha256"]),
        wall_mm=float(data.get("wall_mm", DEFAULT_WALL_MM)),
        floor_mm=float(data.get("floor_mm", DEFAULT_FLOOR_MM)),
        lid_mm=float(data.get("lid_mm", DEFAULT_LID_MM)),
        clearance_mm=float(data.get("clearance_mm", DEFAULT_CLEARANCE_MM)),
        corner_radius_mm=float(data.get("corner_radius_mm", DEFAULT_CORNER_RADIUS_MM)),
        retention_edges=tuple(edges),
        wear=tuple(
            Wear(
                kind=str(entry["kind"]),
                figures={
                    key: value
                    for key, value in entry.items()
                    if key not in ("kind", "source")
                },
                source=str(entry["source"]),
            )
            for entry in data.get("wear") or []
        ),
        source=str(data.get("source", "")),
        notes=str(data.get("notes", "")),
        file_path=path,
        file_sha256=sha256,
    )


def load_housing(path: Path) -> HousingSpec:
    """A housing file, checked; raises ``ValueError`` listing every error."""

    data, digest = read_housing_file(path)

    return housing_from_data(data, path, digest)


def load_housing_input(spec: HousingSpec) -> WearableCapture | BoardFileSpec:
    """What the housing houses, loaded and checked, refused if it has changed since
    the housing file named it."""

    if not spec.input_path.is_file():
        raise ValueError(f"{spec.input_path} is missing")

    digest = hashlib.sha256(spec.input_path.read_bytes()).hexdigest()

    if digest != spec.input_sha256:
        raise ValueError(
            f"{spec.input_path} has changed since the housing file named it: its "
            f"hash is {digest}, not {spec.input_sha256}"
        )

    if spec.style == "cradle":
        return load_capture(spec.input_path)

    return load_board(spec.input_path)


def check_housing_file(
    path: Path, profile: Mapping[str, Any] | None = None
) -> HousingCheck:
    """Check a housing file, what it houses, and its walls against the printer."""

    data, digest = read_housing_file(path)
    report = check_housing_data(data)

    if not report.valid:
        return report

    spec = housing_from_data(data, path, digest)
    errors: list[str] = []
    warnings = list(report.warnings)

    try:
        housed = load_housing_input(spec)
    except ValueError as error:
        return HousingCheck((*report.errors, str(error)), tuple(warnings))

    if spec.style == "cradle":
        capture_check = check_capture(spec.input_path)
        warnings.extend(f"{spec.input_path.name}: {w}" for w in capture_check.warnings)

    if profile is not None:
        _check_walls(spec, profile, errors)

    summary: dict[str, Any] = {
        "style": spec.style,
        "houses": (
            housed.name if isinstance(housed, WearableCapture) else housed.identifier
        ),
        "input_sha256": spec.input_sha256,
        "wall_mm": spec.wall_mm,
        "floor_mm": spec.floor_mm,
    }

    return HousingCheck(tuple(errors), tuple(warnings), summary)


def _check_walls(
    spec: HousingSpec, profile: Mapping[str, Any], errors: list[str]
) -> None:
    _, least_wall, least_floor = printer_numbers(profile)

    if spec.wall_mm < least_wall:
        errors.append(
            f"wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm "
            "minimum wall"
        )

    for name, value in (("floor_mm", spec.floor_mm), ("lid_mm", spec.lid_mm)):
        if spec.style == "cradle" and name == "lid_mm":
            continue

        if value < least_floor:
            errors.append(
                f"{name} is {value:g}, under the printer's {least_floor:g} mm "
                "minimum floor"
            )
