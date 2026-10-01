"""A board described in a file, for an enclosure the catalog has no board for.

The engine reads a board as a rectangle, its thickness and mounting holes, one
cable connector, the parts on it as boxes, and any openings it needs in a wall
(see :class:`~zcad_core.hardware.boards.BoardSpec`). A board file carries exactly
those, as JSON, and loads into an object the builder reads like a catalogued
board, so nothing downstream changes.

Frame: the board's centre is the origin, seen from above; +X is to the right and
+Y up the page, so the edge at +Y is ``positive_y``. Width runs along X and
length along Y. Heights are millimetres above the PCB's top face, or negative
below its underside. All numbers are millimetres.

The engine does not trust a board file. :func:`check_board_data` refuses what
cannot be right and warns of what probably is not, and the build records the
file's hash and ``verified: false``; a printed trial is what verifies a board.

Two levels of detail share the file: ``components`` lists boxes by hand, or
``envelope.top_mm`` gives the height of the tallest part and stands for all of
them as one box over the board. A bottom envelope is not offered: a box under the
whole board would sit on the standoffs and cut them away. List the parts below
the board as components instead.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from zcad_core.hardware.electronics.board_components import BoardComponentSpec
from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
    WallOpeningSpec,
)
from zcad_core.hardware.thermal import PowerFigure, PowerSource

BOARD_SCHEMA_VERSION = "1.0.0"
EDGES = ("negative_x", "positive_x", "negative_y", "positive_y")
ENVELOPE_IDENTIFIER = "envelope-top"
# Sizes outside these are refused as a likely mistake in units; sizes above the
# warning limit are probably a large board or a unit mistake.
BOARD_SIZE_RANGE_MM = (5.0, 400.0)
BOARD_SIZE_WARNING_MM = 150.0
THICKNESS_RANGE_MM = (0.2, 6.0)
TYPICAL_THICKNESS_RANGE_MM = (0.4, 3.2)
HOLE_DIAMETER_RANGE_MM = (0.8, 8.0)
# A standoff is this much wider than its hole, round it.
STANDOFF_WALL_MM = 3.0
# A part overhanging an edge by more than this is almost certainly a mistake.
MAXIMUM_OVERHANG_MM = 20.0
# A part reaching past an edge by more than this needs an access edge.
OVERHANG_MM = 0.3
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]+")
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "identifier",
        "name",
        "units",
        "outline",
        "board",
        "mounting_holes",
        "standoff",
        "cable_connector",
        "envelope",
        "components",
        "wall_openings",
        "power",
        "source",
        "notes",
        "needs_review",
        "verified_by",
    }
)


@dataclass(frozen=True)
class BoardCheck:
    """What a check found: errors make a board unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class BoardOrigin:
    """Where a board came from, and how to tell it from the one that was built."""

    path: str
    sha256: str


@dataclass(frozen=True)
class BoardFileSpec:
    """A board loaded from a file, satisfying the builder's board protocols."""

    identifier: str
    board_width_mm: float
    board_length_mm: float
    board_thickness_mm: float
    usb_connector: RectangularConnectorSpec
    components: tuple[BoardComponentSpec, ...]
    wall_openings: tuple[WallOpeningSpec, ...]
    mounting_hole_diameter_mm: float | None
    mounting_hole_positions_mm: tuple[tuple[float, float], ...] | None
    mounting_hole_spacing_x_mm: float | None
    mounting_hole_spacing_y_mm: float | None
    recommended_standoff_height_mm: float
    recommended_clearance_mm: float
    name: str
    source: str
    notes: str
    power_figure: PowerFigure | None
    origin: BoardOrigin
    warnings: tuple[str, ...]
    # A file's numbers are the user's until a trial has fitted the board; only
    # a board in the catalog's data directory, promoted on its trials, is
    # verified. A ``verified_by`` in a user's own file is a claim, not a check.
    verified: bool = False
    verified_by: str = ""
    # Loaded from the catalog's data directory rather than a user's file.
    catalog: bool = False

    def provenance(self) -> dict[str, Any]:
        """What a build records about where the board came from."""

        record: dict[str, Any] = {
            "kind": "catalog" if self.catalog else "file",
            "identifier": self.identifier,
            "sha256": self.origin.sha256,
            "source": self.source,
            "verified": self.verified,
            "warnings": list(self.warnings),
        }

        if self.catalog:
            record["verified_by"] = self.verified_by
        else:
            record["path"] = self.origin.path

        return record


# --- checking --------------------------------------------------------------


class _Findings:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _number(
    section: Any,
    name: str,
    where: str,
    findings: _Findings,
    *,
    low: float | None = None,
    high: float | None = None,
    required: bool = True,
) -> float | None:
    """A number in ``section``, noting any problem; ``None`` when unusable."""

    value = section.get(name) if isinstance(section, Mapping) else None

    if value is None:
        if required:
            findings.error(f"{where}.{name} is missing")

        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        findings.error(f"{where}.{name} must be a number, not {value!r}")

        return None

    number = float(value)

    if low is not None and number < low:
        findings.error(f"{where}.{name} is {number:g}, below the least, {low:g}")

        return None

    if high is not None and number > high:
        findings.error(f"{where}.{name} is {number:g}, above the most, {high:g}")

        return None

    return number


def _edge_length(edge: str, width: float, length: float) -> float:
    return length if edge.endswith("_y") else width


def _section(
    data: Mapping[str, Any], name: str, findings: _Findings, *, required: bool = True
) -> Mapping[str, Any] | None:
    value = data.get(name)

    if value is None:
        if required:
            findings.error(f"{name} is missing")

        return None

    if not isinstance(value, Mapping):
        findings.error(f"{name} must be an object")

        return None

    return value


def _check_board(
    data: Mapping[str, Any], findings: _Findings
) -> tuple[float, float, float] | None:
    board = _section(data, "board", findings)

    if board is None:
        return None

    low, high = BOARD_SIZE_RANGE_MM
    width = _number(board, "width_mm", "board", findings, low=low, high=high)
    length = _number(board, "length_mm", "board", findings, low=low, high=high)
    thickness = _number(
        board,
        "thickness_mm",
        "board",
        findings,
        low=THICKNESS_RANGE_MM[0],
        high=THICKNESS_RANGE_MM[1],
    )

    if width is None or length is None or thickness is None:
        return None

    if max(width, length) > BOARD_SIZE_WARNING_MM:
        findings.warn(
            f"The board is {width:g} x {length:g} mm; check the numbers are "
            "millimetres, not centimetres or inches"
        )

    typical_low, typical_high = TYPICAL_THICKNESS_RANGE_MM

    if not typical_low <= thickness <= typical_high:
        findings.warn(
            f"A thickness of {thickness:g} mm is outside the usual "
            f"{typical_low:g} to {typical_high:g} mm for a PCB"
        )

    return width, length, thickness


def _hole_positions(
    holes: Mapping[str, Any], findings: _Findings
) -> tuple[tuple[tuple[float, float], ...] | None, tuple[float, float] | None]:
    """The positions a file lists, or the spacing it gives, but not both."""

    positions = holes.get("positions_mm")
    spacing = holes.get("spacing_mm")

    if (positions is None) == (spacing is None):
        findings.error(
            "mounting_holes needs exactly one of positions_mm and spacing_mm"
        )

        return None, None

    if spacing is not None:
        pair = _pair(spacing, "mounting_holes.spacing_mm", findings)

        if pair is not None and min(pair) <= 0:
            findings.error("mounting_holes.spacing_mm must be positive")

            return None, None

        return None, pair

    if (
        not isinstance(positions, Sequence)
        or isinstance(positions, str)
        or not positions
    ):
        findings.error("mounting_holes.positions_mm must be a non-empty list")

        return None, None

    listed = []

    for index, item in enumerate(positions):
        pair = _pair(item, f"mounting_holes.positions_mm[{index}]", findings)

        if pair is not None:
            listed.append(pair)

    return (tuple(listed) if len(listed) == len(positions) else None), None


def _pair(value: Any, where: str, findings: _Findings) -> tuple[float, float] | None:
    ok = (
        isinstance(value, Sequence)
        and not isinstance(value, str)
        and len(value) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    )

    if not ok:
        findings.error(f"{where} must be a pair of numbers [x, y]")

        return None

    return float(value[0]), float(value[1])


def _check_holes(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
) -> None:
    holes = _section(data, "mounting_holes", findings, required=False)

    if holes is None:
        if data.get("mounting_holes") is None:
            findings.warn(
                "No mounting holes: the board will sit in a snap-in cradle, "
                "which is held by its edges"
            )

        return

    low, high = HOLE_DIAMETER_RANGE_MM
    diameter = _number(
        holes, "diameter_mm", "mounting_holes", findings, low=low, high=high
    )
    positions, spacing = _hole_positions(holes, findings)

    if diameter is None or size is None:
        return

    width, length, _ = size
    points = positions
    radius = diameter / 2

    if spacing is not None:
        half_x, half_y = spacing[0] / 2, spacing[1] / 2
        points = (
            (-half_x, -half_y),
            (half_x, -half_y),
            (-half_x, half_y),
            (half_x, half_y),
        )

    for x, y in points or ():
        if abs(x) > width / 2 - radius or abs(y) > length / 2 - radius:
            findings.error(
                f"A mounting hole at ({x:g}, {y:g}) is not inside the "
                f"{width:g} x {length:g} mm board"
            )
        elif abs(x) > width / 2 - radius - 1.5 or abs(y) > length / 2 - radius - 1.5:
            findings.warn(
                f"A mounting hole at ({x:g}, {y:g}) is near the edge: its "
                "standoff will stand out past the board"
            )

    needed = diameter + STANDOFF_WALL_MM

    for i, a in enumerate(points or ()):
        for b in (points or ())[i + 1 :]:
            if ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 < needed:
                findings.error(
                    f"Mounting holes at {a} and {b} are closer than a standoff's "
                    f"{needed:g} mm diameter"
                )


def _check_standoff(data: Mapping[str, Any], findings: _Findings) -> None:
    standoff = _section(data, "standoff", findings, required=False)

    if standoff is None:
        return

    _number(
        standoff, "height_mm", "standoff", findings, low=0.5, high=30.0, required=False
    )
    _number(
        standoff,
        "clearance_mm",
        "standoff",
        findings,
        low=0.0,
        high=1.5,
        required=False,
    )


def _check_connector(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
) -> None:
    connector = _section(data, "cable_connector", findings)

    if connector is None:
        return

    identifier = connector.get("identifier")
    edge = connector.get("edge")

    if not isinstance(identifier, str) or not identifier.strip():
        findings.error("cable_connector.identifier must be a name")

    if edge not in EDGES:
        findings.error(f"cable_connector.edge must be one of {EDGES}, not {edge!r}")

    width = _number(
        connector, "width_mm", "cable_connector", findings, low=0.1, high=60.0
    )
    height = _number(
        connector, "height_mm", "cable_connector", findings, low=0.1, high=60.0
    )
    depth = _number(
        connector, "depth_mm", "cable_connector", findings, low=0.1, high=80.0
    )
    offset = _number(
        connector, "center_offset_mm", "cable_connector", findings, required=False
    )
    _number(
        connector,
        "bottom_offset_from_board_top_mm",
        "cable_connector",
        findings,
        low=-5.0,
        high=20.0,
        required=False,
    )

    if size is None or edge not in EDGES or width is None or depth is None:
        return

    board_width, board_length, _ = size
    along = _edge_length(edge, board_width, board_length)
    across = board_width if edge.endswith("_y") else board_length

    if abs(offset or 0.0) + width / 2 > along / 2:
        findings.error(
            f"The cable connector runs off its {edge} edge: it is {width:g} mm "
            f"wide and {offset or 0.0:g} mm from the middle of a {along:g} mm edge"
        )

    if depth > across:
        findings.error(
            f"The cable connector is {depth:g} mm deep and the board is only "
            f"{across:g} mm across"
        )

    if height is not None and height > 30.0:
        findings.warn(f"A {height:g} mm tall connector is unusual; check the units")


def _overhangs(
    part: Mapping[str, Any], width: float, length: float
) -> dict[str, float] | None:
    """How far a component box reaches past each edge, or ``None`` when its
    numbers are unusable."""

    keys = ("center_x_mm", "center_y_mm", "width_mm", "depth_mm")
    values = [part.get(key) for key in keys]

    if any(isinstance(v, bool) or not isinstance(v, int | float) for v in values):
        return None

    cx, cy, w, d = (float(cast(float, v)) for v in values)

    return {
        "negative_x": -width / 2 - (cx - w / 2),
        "positive_x": (cx + w / 2) - width / 2,
        "negative_y": -length / 2 - (cy - d / 2),
        "positive_y": (cy + d / 2) - length / 2,
    }


def _check_components(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
) -> list[str]:
    parts = data.get("components")
    envelope = data.get("envelope")

    if parts is not None and envelope is not None:
        findings.error(
            "Give components or an envelope, not both: the envelope stands for "
            "every part as one box"
        )

    if envelope is not None:
        _check_envelope(envelope, findings)
    elif not parts:
        findings.warn(
            "No components and no envelope: the enclosure clears only the board "
            "and its connector. Give envelope.top_mm, the height of the tallest "
            "part, or list the parts"
        )

    if parts is None:
        return []

    if not isinstance(parts, Sequence) or isinstance(parts, str):
        findings.error("components must be a list")

        return []

    identifiers: list[str] = []

    for index, part in enumerate(parts):
        where = f"components[{index}]"

        if not isinstance(part, Mapping):
            findings.error(f"{where} must be an object")
            continue

        name = part.get("identifier")

        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
            findings.error(
                f"{where}.identifier must be a name of letters, digits, _ . -"
            )
        else:
            identifiers.append(name)

        for key in ("width_mm", "depth_mm", "height_mm"):
            _number(part, key, where, findings, low=0.05, high=200.0)

        for key in ("center_x_mm", "center_y_mm", "bottom_offset_from_board_top_mm"):
            _number(part, key, where, findings)

        if size is not None:
            _check_one_component(part, where, size, findings)

    return identifiers


def _check_one_component(
    part: Mapping[str, Any],
    where: str,
    size: tuple[float, float, float],
    findings: _Findings,
) -> None:
    width, length, thickness = size
    bottom = part.get("bottom_offset_from_board_top_mm")
    height = part.get("height_mm")

    if (
        isinstance(bottom, int | float)
        and isinstance(height, int | float)
        and bottom < 0
        and bottom + height > -thickness
    ):
        findings.error(
            f"{where} passes through the board: a part lies wholly above the "
            "board or wholly below it, so split it into two boxes"
        )

    reach = _overhangs(part, width, length)

    if reach is None:
        return

    access = part.get("access_edge")

    if access is not None and access not in EDGES:
        findings.error(f"{where}.access_edge must be one of {EDGES} or null")
        return

    for edge, past in reach.items():
        if past > MAXIMUM_OVERHANG_MM:
            findings.error(
                f"{where} reaches {past:.1f} mm past the {edge} edge; check its "
                "position, which is from the board's centre"
            )
        elif past > OVERHANG_MM and access != edge:
            findings.warn(
                f"{where} reaches {past:.1f} mm past the {edge} edge but is not "
                f"marked access_edge: {edge!r}, so the wall will not be opened for it"
            )

    if access is not None and reach[access] <= OVERHANG_MM:
        findings.warn(f"{where} is marked access_edge {access!r} but does not reach it")


def _check_envelope(envelope: Any, findings: _Findings) -> None:
    if not isinstance(envelope, Mapping):
        findings.error("envelope must be an object")

        return

    unknown = sorted(set(envelope) - {"top_mm"})

    if unknown:
        findings.error(
            f"envelope has no {', '.join(unknown)}: only top_mm is offered, because "
            "a box under the whole board would cut the standoffs away; list the "
            "parts below the board as components"
        )

    _number(envelope, "top_mm", "envelope", findings, low=0.5, high=100.0)


def _check_wall_openings(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
) -> None:
    openings = data.get("wall_openings")

    if openings is None:
        return

    if not isinstance(openings, Sequence) or isinstance(openings, str):
        findings.error("wall_openings must be a list")

        return

    for index, opening in enumerate(openings):
        where = f"wall_openings[{index}]"

        if not isinstance(opening, Mapping):
            findings.error(f"{where} must be an object")
            continue

        edge = opening.get("edge")

        if edge not in EDGES:
            findings.error(f"{where}.edge must be one of {EDGES}, not {edge!r}")

        width = _number(opening, "width_mm", where, findings, low=0.5, high=100.0)
        _number(opening, "height_mm", where, findings, low=0.5, high=100.0)
        offset = _number(opening, "center_offset_mm", where, findings)
        _number(opening, "bottom_offset_from_board_top_mm", where, findings)
        name = opening.get("identifier")

        if not isinstance(name, str) or not name.strip():
            findings.error(f"{where}.identifier must be a name")

        if (
            size is not None
            and edge in EDGES
            and width is not None
            and offset is not None
            and abs(offset) + width / 2 > _edge_length(edge, size[0], size[1]) / 2
        ):
            findings.error(f"{where} runs off its {edge} edge")


def _check_power(data: Mapping[str, Any], findings: _Findings) -> None:
    power = _section(data, "power", findings, required=False)

    if power is None:
        return

    typical = _number(power, "typical_w", "power", findings, low=0.0001, high=500.0)
    peak = _number(
        power, "peak_w", "power", findings, low=0.0001, high=500.0, required=False
    )
    source = power.get("source")

    if not isinstance(source, str) or not source.strip():
        findings.error(
            "power.source must say where the figure came from: a power with no "
            "source is not used"
        )

    if typical is not None and peak is not None and peak < typical:
        findings.error("power.peak_w cannot be below power.typical_w")


def check_board_data(data: Any) -> BoardCheck:
    """Check a board file's contents, reporting every problem at once."""

    findings = _Findings()

    if not isinstance(data, Mapping):
        return BoardCheck(("A board file must hold a JSON object",), ())

    if data.get("schema_version") != BOARD_SCHEMA_VERSION:
        findings.error(
            f"schema_version must be {BOARD_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    unknown = sorted(set(data) - _TOP_LEVEL)

    if unknown:
        findings.error(f"Unknown field(s): {', '.join(unknown)}")

    if data.get("units", "mm") != "mm":
        findings.error("units must be 'mm'; every number is millimetres")

    if data.get("outline", "rectangle") != "rectangle":
        findings.error(
            "outline must be 'rectangle': the board is enclosed by its bounding "
            "rectangle in this version"
        )

    identifier = data.get("identifier")

    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
        findings.error("identifier must be a name of letters, digits, _ . -")

    if data.get("needs_review"):
        findings.error(
            f"The file is not reviewed: {data['needs_review']}; settle these, then "
            "remove needs_review"
        )

    verified_by = data.get("verified_by")

    if verified_by is not None and (
        not isinstance(verified_by, str) or not verified_by.strip()
    ):
        findings.error("verified_by must say which trials verified the board")

    size = _check_board(data, findings)
    _check_holes(data, size, findings)
    _check_standoff(data, findings)
    _check_connector(data, size, findings)
    names = _check_components(data, size, findings)
    _check_wall_openings(data, size, findings)
    _check_power(data, findings)
    connector = data.get("cable_connector")

    if isinstance(connector, Mapping):
        names.append(str(connector.get("identifier")))

    if len(set(names)) != len(names):
        findings.error("Component and connector identifiers must be unique")

    if not data.get("source"):
        findings.warn(
            "No source is stated: say where the numbers came from (a datasheet, "
            "calipers, a model)"
        )

    return BoardCheck(tuple(findings.errors), tuple(findings.warnings))


# --- loading ---------------------------------------------------------------


def _components(
    data: Mapping[str, Any], width: float, length: float
) -> tuple[BoardComponentSpec, ...]:
    envelope = data.get("envelope")

    if envelope is not None:
        return (
            BoardComponentSpec(
                identifier=ENVELOPE_IDENTIFIER,
                center_x_mm=0.0,
                center_y_mm=0.0,
                width_mm=width,
                depth_mm=length,
                bottom_offset_from_board_top_mm=0.0,
                height_mm=float(envelope["top_mm"]),
            ),
        )

    return tuple(
        BoardComponentSpec(
            identifier=str(part["identifier"]),
            center_x_mm=float(part["center_x_mm"]),
            center_y_mm=float(part["center_y_mm"]),
            width_mm=float(part["width_mm"]),
            depth_mm=float(part["depth_mm"]),
            bottom_offset_from_board_top_mm=float(
                part["bottom_offset_from_board_top_mm"]
            ),
            height_mm=float(part["height_mm"]),
            access_edge=cast(BoardEdge | None, part.get("access_edge")),
            lid_vent=bool(part.get("lid_vent", False)),
        )
        for part in data.get("components") or ()
    )


def board_from_data(
    data: Mapping[str, Any], origin: BoardOrigin, *, catalog: bool = False
) -> BoardFileSpec:
    """Build a board from checked contents; refuses a file with errors.

    ``catalog`` marks a board read from the catalog's data directory, which is
    verified if it says which trials verified it."""

    report = check_board_data(data)

    if not report.valid:
        raise ValueError(
            f"{origin.path} is not a valid board file:\n- " + "\n- ".join(report.errors)
        )

    board = data["board"]
    width, length = float(board["width_mm"]), float(board["length_mm"])
    connector = data["cable_connector"]
    holes = data.get("mounting_holes")
    standoff = data.get("standoff") or {}
    positions: tuple[tuple[float, float], ...] | None = None
    spacing: tuple[float, float] | None = None

    if holes is not None and holes.get("positions_mm") is not None:
        positions = tuple((float(x), float(y)) for x, y in holes["positions_mm"])
    elif holes is not None:
        spacing = (float(holes["spacing_mm"][0]), float(holes["spacing_mm"][1]))

    power = data.get("power")
    figure = None

    if power is not None:
        figure = PowerFigure(
            identifier=str(data["identifier"]),
            typical_w=float(power["typical_w"]),
            peak_w=float(power["peak_w"]) if power.get("peak_w") is not None else None,
            source=PowerSource(
                kind="user",
                title=f"board file {Path(origin.path).name}",
                url="",
                detail=str(power["source"]),
            ),
        )

    return BoardFileSpec(
        identifier=str(data["identifier"]),
        board_width_mm=width,
        board_length_mm=length,
        board_thickness_mm=float(board["thickness_mm"]),
        usb_connector=RectangularConnectorSpec(
            identifier=str(connector["identifier"]),
            width_mm=float(connector["width_mm"]),
            height_mm=float(connector["height_mm"]),
            depth_mm=float(connector["depth_mm"]),
            board_edge=cast(BoardEdge, connector["edge"]),
            center_offset_mm=float(connector.get("center_offset_mm", 0.0)),
            bottom_offset_from_board_top_mm=float(
                connector.get("bottom_offset_from_board_top_mm", 0.0)
            ),
        ),
        components=_components(data, width, length),
        wall_openings=tuple(
            WallOpeningSpec(
                identifier=str(o["identifier"]),
                edge=cast(BoardEdge, o["edge"]),
                center_offset_mm=float(o["center_offset_mm"]),
                bottom_offset_from_board_top_mm=float(
                    o["bottom_offset_from_board_top_mm"]
                ),
                width_mm=float(o["width_mm"]),
                height_mm=float(o["height_mm"]),
            )
            for o in data.get("wall_openings") or ()
        ),
        mounting_hole_diameter_mm=(
            float(holes["diameter_mm"]) if holes is not None else None
        ),
        mounting_hole_positions_mm=positions,
        mounting_hole_spacing_x_mm=spacing[0] if spacing else None,
        mounting_hole_spacing_y_mm=spacing[1] if spacing else None,
        recommended_standoff_height_mm=float(standoff.get("height_mm", 3.0)),
        recommended_clearance_mm=float(standoff.get("clearance_mm", 0.5)),
        name=str(data.get("name", data["identifier"])),
        source=str(data.get("source", "")),
        notes=str(data.get("notes", "")),
        power_figure=figure,
        origin=origin,
        warnings=report.warnings,
        verified=catalog and bool(data.get("verified_by")),
        verified_by=str(data.get("verified_by") or ""),
        catalog=catalog,
    )


def read_board_file(path: Path) -> tuple[Any, BoardOrigin]:
    """A board file's contents and its origin (path and hash)."""

    raw = path.read_bytes()
    origin = BoardOrigin(path=str(path), sha256=hashlib.sha256(raw).hexdigest())

    try:
        return json.loads(raw.decode("utf-8")), origin
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def load_board(path: Path) -> BoardFileSpec:
    """Load and check a board file, refusing one that cannot be right."""

    data, origin = read_board_file(path)

    return board_from_data(data, origin)


def catalog_filename(identifier: str) -> str:
    """The file a catalogued board lives in: its identifier, lower case, with
    dashes for underscores."""

    return identifier.lower().replace("_", "-") + ".json"


def load_catalog_boards(directory: Path) -> tuple[BoardFileSpec, ...]:
    """The boards in a data directory, one file each, or none if it is absent.

    A file that is invalid, unreviewed, or not named for its board is an error
    that names it: the catalog is data a pull request adds, and a bad file must
    not slip in unseen."""

    if not directory.is_dir():
        return ()

    boards = []

    for path in sorted(directory.glob("*.json")):
        data, origin = read_board_file(path)
        origin = BoardOrigin(
            path=f"hardware/data/boards/{path.name}", sha256=origin.sha256
        )
        board = board_from_data(data, origin, catalog=True)

        if path.name != catalog_filename(board.identifier):
            raise ValueError(
                f"{path.name} holds {board.identifier}, so it must be called "
                f"{catalog_filename(board.identifier)}"
            )

        boards.append(board)

    return tuple(boards)


def board_template() -> dict[str, Any]:
    """A valid example board to copy and edit: every number is an example."""

    return {
        "schema_version": BOARD_SCHEMA_VERSION,
        "identifier": "EXAMPLE_BOARD",
        "name": "Example board: replace every number",
        "units": "mm",
        "outline": "rectangle",
        "source": "EXAMPLE ONLY: say where your numbers came from",
        "notes": (
            "Seen from above with the board's centre at the origin: +X is to the "
            "right and +Y is up the page, so the edge at +Y is positive_y. Width "
            "runs along X and length along Y. Heights are above the PCB's top "
            "face; the cable connector sits inside the outline against its edge."
        ),
        "board": {"width_mm": 30.0, "length_mm": 45.0, "thickness_mm": 1.6},
        "mounting_holes": {
            "diameter_mm": 2.7,
            "positions_mm": [
                [-12.0, -19.0],
                [12.0, -19.0],
                [-12.0, 19.0],
                [12.0, 19.0],
            ],
        },
        "standoff": {"height_mm": 3.0, "clearance_mm": 0.3},
        "cable_connector": {
            "identifier": "USB_C",
            "edge": "negative_y",
            "width_mm": 9.0,
            "height_mm": 3.3,
            "depth_mm": 7.5,
            "center_offset_mm": 0.0,
            "bottom_offset_from_board_top_mm": 0.0,
        },
        "envelope": {"top_mm": 6.0},
        "wall_openings": [],
        "power": {
            "typical_w": 0.5,
            "peak_w": 1.0,
            "source": "EXAMPLE ONLY: a datasheet or a meter reading",
        },
    }


def check_board_file(path: Path) -> tuple[BoardCheck, BoardOrigin]:
    """Check a board file without building anything from it."""

    data, origin = read_board_file(path)

    return check_board_data(data), origin
