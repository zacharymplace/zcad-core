"""An object holder described in a file, and the object it holds.

A holder is a cup on a back plate that hangs on a wall: the object drops into it from above
and sits on its floor. The file names the object by a caliper capture (a ``wearable`` capture
of a ``custom`` device) and its hash, says which of the object's edges sits on the floor and
which way its face looks, how high the front climbs, and how the holder is fixed to the wall.
The engine does not trust it: :func:`check_holder_data` refuses what cannot be right, and
:func:`inspect_holder_file` also reads the capture and refuses one that ``wearable check``
refuses.

Frame: the holder's, as it hangs and as it prints. X runs along the wall, to the right seen from
the room; Y out from the wall; Z up. The back plate's front face is ``y == 0`` and the pocket's
floor ``z == 0``. All numbers are millimetres.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.features.guide_common import IDENTIFIER, Findings, number, section
from zcad_core.hardware.wearables.capture import (
    CUSTOM,
    EDGES,
    WearableCapture,
    check_capture,
    load_capture,
)

HOLDER_SCHEMA_VERSION = "1.0.0"
HOLDER_KIND = "holder"
FACES = ("out", "wall")
DEFAULT_WALL_MM = 2.0
DEFAULT_FLOOR_MM = 2.0
# A plate for countersunk screws, pegs or a pad, and one deep enough to hide a keyhole
# screw's head.
DEFAULT_BACK_MM = 4.0
DEFAULT_KEYHOLE_BACK_MM = 6.0
# The front climbs a third of the object's height, and no less than this.
FRONT_SHARE = 1 / 3
MINIMUM_FRONT_MM = 10.0
WALL_RANGE_MM = (0.8, 20.0)
BACK_RANGE_MM = (2.0, 20.0)
FRONT_RANGE_MM = (2.0, 300.0)
CLEARANCE_RANGE_MM = (0.05, 3.0)
HEAD_RANGE_MM = (3.0, 20.0)
SHANK_RANGE_MM = (1.5, 10.0)
PITCH_RANGE_MM = (10.0, 100.0)
PEG_HOLE_RANGE_MM = (3.0, 12.0)
BOARD_RANGE_MM = (2.0, 12.0)
PAD_RANGE_MM = (10.0, 300.0)
# Each mount's figures, which are the user's and so need a source; a keyhole is the mounts'.
MOUNT_FIGURES: dict[str, dict[str, tuple[float, float]]] = {
    "screws": {"head_diameter_mm": HEAD_RANGE_MM, "shank_diameter_mm": SHANK_RANGE_MM},
    "keyhole": {},
    "pegboard": {
        "pitch_mm": PITCH_RANGE_MM,
        "hole_diameter_mm": PEG_HOLE_RANGE_MM,
        "board_thickness_mm": BOARD_RANGE_MM,
    },
    "flat": {"width_mm": PAD_RANGE_MM, "height_mm": PAD_RANGE_MM},
}
MOUNTS = tuple(MOUNT_FIGURES)
DEFAULT_TAB_OVERHANG_MM = 0.6
TAB_OVERHANG_RANGE_MM = (0.3, 2.0)
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "file_kind",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "object",
        "down_edge",
        "face",
        "holder",
        "fit",
        "mount",
        "retention",
        "needs_review",
    }
)
_HOLDER = frozenset({"front_mm", "wall_mm", "floor_mm", "back_mm"})


@dataclass(frozen=True)
class HolderSpec:
    """An object holder as its file describes it."""

    identifier: str
    name: str
    capture_path: Path
    capture_sha256: str
    down_edge: str
    face: str
    # None: a third of the object's height, at least 10 mm.
    front_mm: float | None
    wall_mm: float
    floor_mm: float
    back_mm: float
    mount: str
    # The mount's figures (a screw's head and shank, a pegboard's pitch, hole and thickness,
    # a pad's size), which are the user's, and where they came from.
    mount_figures: Mapping[str, float]
    mount_source: str
    # The user's clearance per side, with its source; None takes the printer's.
    clearance_mm: float | None
    clearance_source: str
    source: str
    notes: str
    file_path: Path
    file_sha256: str
    # Retaining tabs: None is none; else how far each hook reaches over the object's top.
    tab_overhang_mm: float | None = None


@dataclass(frozen=True)
class HolderCheck:
    """What a check found: errors make a holder unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    # What reading the capture found, when it could be read.
    capture: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


def holder_template(capture: Path | None = None) -> dict[str, Any]:
    """A valid example holder file to copy and edit; given a capture, it names that file and
    its real hash."""

    digest = (
        hashlib.sha256(capture.read_bytes()).hexdigest()
        if capture is not None
        else "0" * 64
    )

    return {
        "schema_version": HOLDER_SCHEMA_VERSION,
        "file_kind": HOLDER_KIND,
        "identifier": "EXAMPLE_HOLDER",
        "name": "Example holder: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what the object is and where it hangs",
        "notes": (
            "The object stands in a cup on a back plate, its down_edge on the floor and its "
            "face toward the room (out) or the wall. The holder prints as it hangs, floor "
            "down. Its frame: X along the wall, Y out from it, Z up."
        ),
        "object": {
            "capture": str(capture) if capture is not None else "object.json",
            "sha256": digest,
        },
        "down_edge": "south",
        "face": "out",
        "holder": {"wall_mm": DEFAULT_WALL_MM, "floor_mm": DEFAULT_FLOOR_MM},
        "mount": {
            "type": "screws",
            "head_diameter_mm": 8.0,
            "shank_diameter_mm": 4.0,
            "source": "EXAMPLE ONLY: measure your screw's head and shank",
        },
    }


def _check_mount(data: Mapping[str, Any], findings: Findings) -> None:
    mount = section(data, "mount", findings)

    if mount is None:
        return

    kind = mount.get("type")

    if kind not in MOUNTS:
        findings.errors.append(f"mount.type must be one of {MOUNTS}, not {kind!r}")

        return

    figures = MOUNT_FIGURES[kind]
    allowed = {"type"} | set(figures) | ({"source"} if figures else set())
    unknown = sorted(set(mount) - allowed)

    if unknown:
        findings.errors.append(f"mount has no {', '.join(unknown)} for {kind}")

    found = {
        name: number(mount, name, "mount", findings, low=low, high=high)
        for name, (low, high) in figures.items()
    }
    source = mount.get("source")

    if figures and (not isinstance(source, str) or not source.strip()):
        findings.errors.append(
            f"mount.source must say where the {kind} figures came from"
        )

    head, shank = found.get("head_diameter_mm"), found.get("shank_diameter_mm")

    if head is not None and shank is not None and head <= shank:
        findings.errors.append(
            f"mount.head_diameter_mm ({head:g}) must be wider than the shank ({shank:g})"
        )


def _check_retention(data: Mapping[str, Any], findings: Findings) -> None:
    retention = section(data, "retention", findings, required=False)

    if retention is None:
        return

    if retention.get("type") != "tabs":
        findings.errors.append(
            f"retention.type must be 'tabs', not {retention.get('type')!r}"
        )

    unknown = sorted(set(retention) - {"type", "overhang_mm"})

    if unknown:
        findings.errors.append(f"retention has no {', '.join(unknown)}")

    number(
        retention,
        "overhang_mm",
        "retention",
        findings,
        low=TAB_OVERHANG_RANGE_MM[0],
        high=TAB_OVERHANG_RANGE_MM[1],
        required=False,
    )


def _check_holder_section(data: Mapping[str, Any], findings: Findings) -> None:
    holder = section(data, "holder", findings, required=False)

    if holder is None:
        return

    unknown = sorted(set(holder) - _HOLDER)

    if unknown:
        findings.errors.append(f"holder has no {', '.join(unknown)}")

    number(
        holder,
        "wall_mm",
        "holder",
        findings,
        low=WALL_RANGE_MM[0],
        high=WALL_RANGE_MM[1],
        required=False,
    )
    number(
        holder,
        "floor_mm",
        "holder",
        findings,
        low=WALL_RANGE_MM[0],
        high=WALL_RANGE_MM[1],
        required=False,
    )
    number(
        holder,
        "back_mm",
        "holder",
        findings,
        low=BACK_RANGE_MM[0],
        high=BACK_RANGE_MM[1],
        required=False,
    )
    number(
        holder,
        "front_mm",
        "holder",
        findings,
        low=FRONT_RANGE_MM[0],
        high=FRONT_RANGE_MM[1],
        required=False,
    )


def _check_fit(data: Mapping[str, Any], findings: Findings) -> None:
    fit = section(data, "fit", findings, required=False)

    if fit is None:
        return

    unknown = sorted(set(fit) - {"clearance_mm", "source"})

    if unknown:
        findings.errors.append(f"fit has no {', '.join(unknown)}")

    number(
        fit,
        "clearance_mm",
        "fit",
        findings,
        low=CLEARANCE_RANGE_MM[0],
        high=CLEARANCE_RANGE_MM[1],
    )
    source = fit.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.errors.append(
            "fit.source must say why this clearance: a clearance with no source is a guess"
        )


def _check_header(data: Mapping[str, Any], findings: Findings) -> None:
    unknown = sorted(set(data) - _TOP_LEVEL)

    if unknown:
        findings.errors.append(f"Unknown field(s): {', '.join(unknown)}")

    if data.get("schema_version") != HOLDER_SCHEMA_VERSION:
        findings.errors.append(f"schema_version must be {HOLDER_SCHEMA_VERSION}")

    if data.get("file_kind") != HOLDER_KIND:
        findings.errors.append(f"file_kind must be {HOLDER_KIND!r}")

    if data.get("units") != "mm":
        findings.errors.append("units must be mm")

    identifier = data.get("identifier")

    if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
        findings.errors.append("identifier must be a name of letters, digits, _ . -")

    for name in ("name", "source"):
        if not isinstance(data.get(name), str) or not str(data.get(name)).strip():
            findings.errors.append(f"{name} must be text")

    if data.get("needs_review"):
        findings.errors.append(
            "The file still carries needs_review: settle it and remove it"
        )


def _check_object(data: Mapping[str, Any], findings: Findings) -> None:
    obj = section(data, "object", findings)

    if obj is not None:
        if not isinstance(obj.get("capture"), str) or not obj["capture"]:
            findings.errors.append("object.capture must name the capture file")

        if not isinstance(obj.get("sha256"), str) or len(obj["sha256"]) != 64:
            findings.errors.append("object.sha256 must be the capture's SHA-256")


def check_holder_data(data: Any) -> HolderCheck:
    """Refuse a holder file that cannot be right, without reading its capture."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return HolderCheck(("A holder file must be a JSON object",), ())

    _check_header(data, findings)
    _check_object(data, findings)

    if data.get("down_edge") not in EDGES:
        findings.errors.append(
            f"down_edge must be one of {EDGES}, not {data.get('down_edge')!r}"
        )

    if data.get("face") not in FACES:
        findings.errors.append(f"face must be one of {FACES}, not {data.get('face')!r}")

    _check_holder_section(data, findings)
    _check_fit(data, findings)
    _check_mount(data, findings)
    _check_retention(data, findings)

    return HolderCheck(tuple(findings.errors), tuple(findings.warnings))


def read_holder_file(path: Path) -> tuple[Any, str]:
    raw = path.read_bytes()

    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def _capture_path(data: Mapping[str, Any], path: Path) -> Path:
    named = Path(str(data["object"]["capture"]))

    return named if named.is_absolute() else path.parent / named


def holder_from_data(data: Mapping[str, Any], path: Path, sha256: str) -> HolderSpec:
    """A checked holder file as a spec; refuses one ``check_holder_data`` refuses."""

    check = check_holder_data(data)

    if not check.valid:
        raise ValueError(f"{path} cannot be used: " + "; ".join(check.errors))

    holder = data.get("holder") or {}
    mount = data["mount"]
    fit = data.get("fit") or {}
    kind = str(mount["type"])
    default_back = DEFAULT_KEYHOLE_BACK_MM if kind == "keyhole" else DEFAULT_BACK_MM
    retention = data.get("retention")

    return HolderSpec(
        identifier=str(data["identifier"]),
        name=str(data["name"]),
        capture_path=_capture_path(data, path),
        capture_sha256=str(data["object"]["sha256"]),
        down_edge=str(data["down_edge"]),
        face=str(data["face"]),
        front_mm=(
            float(holder["front_mm"]) if holder.get("front_mm") is not None else None
        ),
        wall_mm=float(holder.get("wall_mm", DEFAULT_WALL_MM)),
        floor_mm=float(holder.get("floor_mm", DEFAULT_FLOOR_MM)),
        back_mm=float(holder.get("back_mm", default_back)),
        mount=kind,
        mount_figures={name: float(mount[name]) for name in MOUNT_FIGURES[kind]},
        mount_source=str(mount.get("source", "")).strip(),
        clearance_mm=(
            float(fit["clearance_mm"]) if fit.get("clearance_mm") is not None else None
        ),
        clearance_source=str(fit.get("source", "")).strip(),
        source=str(data["source"]),
        notes=str(data.get("notes", "")),
        file_path=path,
        file_sha256=sha256,
        tab_overhang_mm=(
            float(retention.get("overhang_mm", DEFAULT_TAB_OVERHANG_MM))
            if retention
            else None
        ),
    )


def load_holder(path: Path) -> HolderSpec:
    data, sha256 = read_holder_file(path)

    return holder_from_data(data, path, sha256)


def load_holder_capture(spec: HolderSpec) -> WearableCapture:
    """The capture a holder names, refused if it is missing, has changed since the holder
    file was written, is not a custom device's, or is not a valid capture."""

    path = spec.capture_path

    if not path.is_file():
        raise ValueError(f"The capture is missing: {path}")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    if digest != spec.capture_sha256:
        raise ValueError(
            f"The capture {path} has changed since the holder file named it: its SHA-256 "
            f"is {digest}, not {spec.capture_sha256}"
        )

    capture = load_capture(path)

    if capture.device != CUSTOM:
        raise ValueError(
            f"{path} is a {capture.name} capture; a holder takes a custom device's capture"
        )

    return capture


def inspect_holder_file(
    path: Path,
) -> tuple[HolderCheck, HolderSpec | None, WearableCapture | None]:
    """Check a holder file and its capture, listing every problem at once; with them, the
    spec and the capture when both can be used."""

    try:
        data, sha256 = read_holder_file(path)
    except (OSError, ValueError) as error:
        return HolderCheck((f"{path} cannot be read: {error}",), ()), None, None

    check = check_holder_data(data)

    if not check.valid:
        return check, None, None

    spec = holder_from_data(data, path, sha256)
    captured = check_capture(spec.capture_path) if spec.capture_path.is_file() else None

    if captured is not None and not captured.valid:
        return (
            HolderCheck(
                tuple(f"capture: {error}" for error in captured.errors),
                tuple(f"capture: {warning}" for warning in captured.warnings),
            ),
            spec,
            None,
        )

    try:
        capture = load_holder_capture(spec)
    except ValueError as error:
        return HolderCheck((str(error),), check.warnings), spec, None

    warnings = (
        *check.warnings,
        *(f"capture: {warning}" for warning in (captured.warnings if captured else ())),
    )

    return (
        HolderCheck(
            (),
            warnings,
            {
                "name": capture.name,
                "sha256": capture.sha256,
                "size_mm": [capture.length_mm, capture.width_mm, capture.thickness_mm],
                "outline_radius_mm": capture.outline_radius_mm,
                "edge_features": [f.identifier for f in capture.edge_features],
                "face_features": [f.identifier for f in capture.face_features],
                "mass_g": capture.mass_g,
            },
        ),
        spec,
        capture,
    )
