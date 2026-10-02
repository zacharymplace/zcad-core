"""A stack file: the items to build on one stack profile.

A stack file names a profile by hash, as a housing file names a board, so an item is refused
if the profile it was built to has changed. It lists items of two kinds:

- a ``bin``: ``cells`` across and deep, ``units`` high, with optional dividers, a label
  tab and a scoop; and
- a ``baseplate``: ``cells`` across and deep, a plate with a pocket for each cell.

A footprint is whole cells and a height is whole units, because both are counts: there is
no way to write a bin that is not.
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
from zcad_core.features.stack_profile import (
    StackProfile,
    load_profile,
    read_profile_file,
)
from zcad_core.features.stack_solids import DIVIDER_MM

STACK_SCHEMA_VERSION = "1.0.0"
STACK_KIND = "stack"
KINDS = ("bin", "baseplate")
DEFAULT_WALL_MM = 1.2
DEFAULT_FLOOR_MM = 1.2
DEFAULT_RIM_MM = 1.2
DEFAULT_TAB_MM = 12.0
DEFAULT_SCOOP_MM = 10.0
MAXIMUM_CELLS = 20
MAXIMUM_UNITS = 30
# The narrowest a compartment may be between dividers or walls.
MINIMUM_COMPARTMENT_MM = 5.0
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "file_kind",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "profile",
        "items",
        "needs_review",
    }
)
_ITEM = {
    "bin": frozenset(
        {
            "kind",
            "name",
            "cells",
            "units",
            "wall_mm",
            "floor_mm",
            "dividers",
            "label_tab",
            "scoop",
        }
    ),
    "baseplate": frozenset({"kind", "name", "cells", "floor_mm", "rim_mm"}),
}


@dataclass(frozen=True)
class Item:
    """One item to build."""

    kind: str
    name: str
    cells: tuple[int, int]
    units: int = 1
    wall_mm: float = DEFAULT_WALL_MM
    floor_mm: float = DEFAULT_FLOOR_MM
    rim_mm: float = DEFAULT_RIM_MM
    dividers: tuple[int, int] = (0, 0)
    label_tab: bool = False
    scoop: bool = False


@dataclass(frozen=True)
class StackSpec:
    """A stack file as it describes the items."""

    identifier: str
    name: str
    profile_path: Path
    profile_sha256: str
    items: tuple[Item, ...]
    source: str
    file_path: Path
    file_sha256: str


@dataclass(frozen=True)
class StackCheck:
    """What a check found: errors make the stack unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


def stack_template(profile_file: Path | None = None) -> dict[str, Any]:
    """An example stack file to edit, naming ``profile_file`` by its real hash if one
    is given."""

    digest = (
        hashlib.sha256(profile_file.read_bytes()).hexdigest()
        if profile_file is not None and profile_file.is_file()
        else "0" * 64
    )

    return {
        "schema_version": STACK_SCHEMA_VERSION,
        "file_kind": STACK_KIND,
        "identifier": "EXAMPLE_STACK",
        "name": "Example stack: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what these items are for",
        "profile": {
            "file": str(profile_file) if profile_file is not None else "profile.json",
            "sha256": digest,
        },
        "items": [
            {
                "kind": "bin",
                "name": "parts-bin",
                "cells": [2, 1],
                "units": 3,
                "dividers": {"x": 1, "y": 0},
                "label_tab": False,
                "scoop": True,
            },
            {"kind": "baseplate", "name": "base", "cells": [2, 2]},
        ],
    }


def _check_profile_entry(data: Mapping[str, Any], findings: Findings) -> None:
    entry = section(data, "profile", findings)

    if entry is None:
        return

    file = entry.get("file")

    if not isinstance(file, str) or not file.strip():
        findings.errors.append("profile.file must name the stack profile file")

    digest = entry.get("sha256")

    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        findings.errors.append(
            "profile.sha256 must be the file's SHA-256 as 64 lower-case hex digits"
        )


def _whole(
    value: Any, name: str, low: int, high: int, findings: Findings
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        findings.errors.append(f"{name} must be a whole number, not {value!r}")

        return None

    if not low <= value <= high:
        findings.errors.append(f"{name} is {value}, outside {low} to {high}")

        return None

    return value


def _check_cells(entry: Mapping[str, Any], where: str, findings: Findings) -> None:
    cells = entry.get("cells")

    if not isinstance(cells, list) or len(cells) != 2:
        findings.errors.append(
            f"{where}.cells must be [across, deep], two whole numbers"
        )

        return

    for axis, value in zip(("across", "deep"), cells, strict=True):
        _whole(value, f"{where}.cells {axis}", 1, MAXIMUM_CELLS, findings)


def _check_bin(entry: Mapping[str, Any], where: str, findings: Findings) -> None:
    _whole(entry.get("units"), f"{where}.units", 1, MAXIMUM_UNITS, findings)
    dividers = entry.get("dividers", {})

    if not isinstance(dividers, Mapping) or set(dividers) - {"x", "y"}:
        findings.errors.append(
            f"{where}.dividers must be an object with x and y counts"
        )
    else:
        for axis in ("x", "y"):
            if axis in dividers:
                _whole(dividers[axis], f"{where}.dividers.{axis}", 0, 20, findings)

    for flag in ("label_tab", "scoop"):
        if not isinstance(entry.get(flag, False), bool):
            findings.errors.append(f"{where}.{flag} must be true or false")

    number(entry, "wall_mm", where, findings, low=0.4, high=10.0, required=False)
    number(entry, "floor_mm", where, findings, low=0.4, high=10.0, required=False)


def _check_item(entry: Any, index: int, names: list[str], findings: Findings) -> None:
    where = f"items[{index}]"

    if not isinstance(entry, Mapping):
        findings.errors.append(f"{where} must be an object")

        return

    kind = entry.get("kind")

    if kind not in KINDS:
        findings.errors.append(f"{where}.kind must be one of {KINDS}")

        return

    unknown = sorted(set(entry) - _ITEM[kind])

    if unknown:
        findings.errors.append(f"{where} has unknown fields: {', '.join(unknown)}")

    name = entry.get("name")

    if not isinstance(name, str) or not IDENTIFIER.fullmatch(name):
        findings.errors.append(f"{where}.name must be a name of letters, digits, _ . -")
    elif name in names:
        findings.errors.append(f"{where}.name {name!r} is used twice")
    else:
        names.append(name)

    _check_cells(entry, where, findings)

    if kind == "bin":
        _check_bin(entry, where, findings)
    else:
        number(entry, "floor_mm", where, findings, low=0.4, high=10.0, required=False)
        number(entry, "rim_mm", where, findings, low=0.4, high=10.0, required=False)


def check_stack_data(data: Any) -> StackCheck:
    """Check a stack file's contents without reading what it names."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return StackCheck(("A stack file must hold a JSON object",), ())

    if data.get("schema_version") != STACK_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {STACK_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    if data.get("file_kind") != STACK_KIND:
        findings.errors.append(
            f"file_kind must be {STACK_KIND!r}: this is not a stack file"
        )

    unknown = sorted(set(data) - _TOP_LEVEL)

    if unknown:
        findings.errors.append(f"Unknown field(s): {', '.join(unknown)}")

    identifier = data.get("identifier")

    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        findings.errors.append("identifier must be a name of letters, digits, _ . -")

    if data.get("needs_review"):
        findings.errors.append(
            f"The file is not reviewed: {data['needs_review']}; settle these, then "
            "remove needs_review"
        )

    _check_profile_entry(data, findings)
    items = data.get("items")

    if not isinstance(items, list) or not items:
        findings.errors.append("items must be a list of at least one item")
    else:
        names: list[str] = []

        for index, entry in enumerate(items):
            _check_item(entry, index, names, findings)

    if not str(data.get("source", "")).strip():
        findings.warnings.append("No source is stated: say what these items are for")

    return StackCheck(tuple(findings.errors), tuple(findings.warnings))


def read_stack_file(path: Path) -> tuple[Any, str]:
    """A stack file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def _item(entry: Mapping[str, Any]) -> Item:
    dividers = entry.get("dividers", {})

    return Item(
        kind=str(entry["kind"]),
        name=str(entry["name"]),
        cells=(int(entry["cells"][0]), int(entry["cells"][1])),
        units=int(entry.get("units", 1)),
        wall_mm=float(entry.get("wall_mm", DEFAULT_WALL_MM)),
        floor_mm=float(entry.get("floor_mm", DEFAULT_FLOOR_MM)),
        rim_mm=float(entry.get("rim_mm", DEFAULT_RIM_MM)),
        dividers=(int(dividers.get("x", 0)), int(dividers.get("y", 0))),
        label_tab=bool(entry.get("label_tab", False)),
        scoop=bool(entry.get("scoop", False)),
    )


def stack_from_data(data: Mapping[str, Any], path: Path, sha256: str) -> StackSpec:
    """A stack from checked contents; refuses a file with errors."""

    report = check_stack_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid stack file:\n- " + "\n- ".join(report.errors)
        )

    entry = data["profile"]
    profile_path = Path(entry["file"])

    return StackSpec(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        profile_path=(
            profile_path
            if profile_path.is_absolute()
            else (path.parent / profile_path).resolve()
        ),
        profile_sha256=str(entry["sha256"]),
        items=tuple(_item(item) for item in data["items"]),
        source=str(data.get("source", "")),
        file_path=path,
        file_sha256=sha256,
    )


def load_stack(path: Path) -> StackSpec:
    """A stack from a file, refused if it has errors."""

    data, digest = read_stack_file(path)

    return stack_from_data(data, path, digest)


def load_stack_profile(spec: StackSpec) -> StackProfile:
    """The profile a stack names, refused if it has changed since the stack file named it."""

    if not spec.profile_path.is_file():
        raise ValueError(f"{spec.profile_path} is missing")

    _, digest = read_profile_file(spec.profile_path)

    if digest != spec.profile_sha256:
        raise ValueError(
            f"{spec.profile_path} has changed since the stack file named it: its hash "
            f"is {digest}, not {spec.profile_sha256}"
        )

    return load_profile(spec.profile_path)


def _check_item_fits(
    item: Item,
    profile: StackProfile,
    least_wall: float,
    least_floor: float,
    errors: list[str],
) -> None:
    if item.kind == "baseplate":
        if item.floor_mm < least_floor:
            errors.append(
                f"{item.name}: floor_mm is {item.floor_mm:g}, under the printer's "
                f"{least_floor:g} mm minimum floor"
            )

        return

    if item.wall_mm < least_wall:
        errors.append(
            f"{item.name}: wall_mm is {item.wall_mm:g}, under the printer's "
            f"{least_wall:g} mm minimum wall"
        )

    if item.floor_mm < least_floor:
        errors.append(
            f"{item.name}: floor_mm is {item.floor_mm:g}, under the printer's "
            f"{least_floor:g} mm minimum floor"
        )

    _check_bin_fits(item, profile, errors)


def _check_bin_fits(item: Item, profile: StackProfile, errors: list[str]) -> None:
    reach = profile.lip[0][0]

    if item.wall_mm > reach:
        errors.append(
            f"{item.name}: wall_mm is {item.wall_mm:g}, thicker than the {reach:g} mm "
            "the profile's lip reaches in from the wall"
        )

    inner = (
        item.cells[0] * profile.pitch_mm - profile.gap_mm - 2 * item.wall_mm,
        item.cells[1] * profile.pitch_mm - profile.gap_mm - 2 * item.wall_mm,
    )

    for axis, count, length in (
        ("x", item.dividers[0], inner[0]),
        ("y", item.dividers[1], inner[1]),
    ):
        room = (length - count * DIVIDER_MM) / (count + 1)

        if count and room < MINIMUM_COMPARTMENT_MM:
            errors.append(
                f"{item.name}: {count} dividers along {axis} leave compartments "
                f"{room:.1f} mm wide, under {MINIMUM_COMPARTMENT_MM:g} mm"
            )

    _check_tab_and_scoop(item, profile, inner, errors)


def _check_tab_and_scoop(
    item: Item, profile: StackProfile, inner: tuple[float, float], errors: list[str]
) -> None:
    wall_top = item.units * profile.height_unit_mm
    depth = wall_top - profile.foot_height_mm - item.floor_mm

    if item.label_tab and (
        depth < DEFAULT_TAB_MM + 0.5 or inner[1] < 4 * DEFAULT_TAB_MM / 3
    ):
        errors.append(
            f"{item.name}: a label tab needs {DEFAULT_TAB_MM + 0.5:g} mm of height inside "
            f"and room across; this bin has {depth:.1f} mm and {inner[1]:.1f} mm"
        )

    if item.scoop and (depth < DEFAULT_SCOOP_MM or inner[1] < 3 * DEFAULT_SCOOP_MM):
        errors.append(
            f"{item.name}: a scoop needs {DEFAULT_SCOOP_MM:g} mm of height inside and room "
            f"across; this bin has {depth:.1f} mm and {inner[1]:.1f} mm"
        )


def check_stack_file(
    path: Path, printer: Mapping[str, Any] | None = None
) -> StackCheck:
    """Check a stack file, the profile it names, and its items against the printer."""

    data, digest = read_stack_file(path)
    report = check_stack_data(data)

    if not report.valid:
        return report

    spec = stack_from_data(data, path, digest)

    try:
        profile = load_stack_profile(spec)
    except ValueError as error:
        return StackCheck((*report.errors, str(error)), report.warnings)

    errors: list[str] = []
    warnings = list(report.warnings)
    _, least_wall, least_floor = (
        printer_numbers(printer) if printer is not None else ({}, 0.0, 0.0)
    )

    for item in spec.items:
        _check_item_fits(item, profile, least_wall, least_floor, errors)

    summary = {
        "profile": profile.identifier,
        "profile_sha256": spec.profile_sha256,
        "items": [
            {"name": item.name, "kind": item.kind, "cells": list(item.cells)}
            for item in spec.items
        ],
    }

    return StackCheck(tuple(errors), tuple(warnings), summary)
