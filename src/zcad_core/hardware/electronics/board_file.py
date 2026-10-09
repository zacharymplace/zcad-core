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

This module reads a file, checks it and builds the board. What it uses is in
layers, each importing only from those above it: ``board_file_model`` (the
types and limits, which are data), ``board_file_findings`` (what a check
collects), ``board_file_shape`` (the checks of the board's size, outline, holes
and standoffs) and ``board_file_parts`` (the checks of its connector, parts,
openings and power). The types stay importable from here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_components import BoardComponentSpec
from zcad_core.hardware.electronics.board_file_findings import _Findings
from zcad_core.hardware.electronics.board_file_model import (
    _IDENTIFIER,
    _TOP_LEVEL,
    BOARD_SCHEMA_VERSION,
    CRADLE_ENVELOPE_INSET_MM,
    ENVELOPE_IDENTIFIER,
    HOLE_DIAMETER_RANGE_MM,
    MAXIMUM_ENVELOPE_INSET_MM,
    BoardCheck,
    BoardFileSpec,
    BoardOrigin,
)
from zcad_core.hardware.electronics.board_file_parts import (
    _check_components,
    _check_connector,
    _check_power,
    _check_wall_openings,
)
from zcad_core.hardware.electronics.board_file_shape import (
    _check_board,
    _check_holes,
    _check_standoff,
    _outline,
)
from zcad_core.hardware.electronics.board_outline import Point
from zcad_core.hardware.electronics.board_test_points import (
    check_test_points,
    parse_test_points,
)
from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
    WallOpeningSpec,
)
from zcad_core.hardware.thermal import PowerFigure, PowerSource

# Kept importable from here, where they were defined before the split.
__all__ = [
    "BOARD_SCHEMA_VERSION",
    "ENVELOPE_IDENTIFIER",
    "HOLE_DIAMETER_RANGE_MM",
    "BoardCheck",
    "BoardFileSpec",
    "BoardOrigin",
    "board_from_data",
    "board_template",
    "catalog_filename",
    "check_board_data",
    "check_board_file",
    "load_board",
    "load_catalog_boards",
    "read_board_file",
]


def check_board_data(data: Any) -> BoardCheck:
    """Check a board file's contents, reporting every problem at once."""

    return _check(data)[0]


def _check(data: Any) -> tuple[BoardCheck, tuple[Point, ...] | None]:
    """The check, and the outline polygon it found (``None``: a rectangle)."""

    findings = _Findings()

    if not isinstance(data, Mapping):
        return BoardCheck(("A board file must hold a JSON object",), ()), None

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
    outline = _outline(data, size, findings)
    _check_holes(data, size, findings, outline)
    _check_standoff(data, findings)
    _check_connector(data, size, findings, outline)
    names = _check_components(data, size, findings)

    if (
        size is not None
        and isinstance(data.get("envelope"), Mapping)
        and _envelope_inset(outline, size[0], size[1], data) is None
    ):
        findings.error(
            "The envelope cannot stand clear of this outline where a cradle "
            "follows it (a notch or deep cut-out): list the parts as components "
            "instead"
        )

    _check_wall_openings(data, size, findings)
    _check_power(data, findings)
    check_test_points(data, size, outline, findings.error)
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

    return BoardCheck(tuple(findings.errors), tuple(findings.warnings)), outline


def _envelope_inset(
    outline: tuple[Point, ...] | None,
    width: float,
    length: float,
    data: Mapping[str, Any],
) -> float | None:
    """How far in from the bounding rectangle the envelope stands, or ``None``
    if it cannot.

    A board with no holes sits in a cradle whose clips and wall stand at its
    edges, so the envelope keeps clear of them: by a millimetre for a rectangle,
    and for another outline by as much as keeps the envelope's rectangle inside
    it, up to ``MAXIMUM_ENVELOPE_INSET_MM``."""

    if data.get("mounting_holes") is not None:
        return 0.0

    if outline is None:
        return CRADLE_ENVELOPE_INSET_MM

    inset = CRADLE_ENVELOPE_INSET_MM

    while inset <= MAXIMUM_ENVELOPE_INSET_MM:
        if _rectangle_inside(outline, width - 2 * inset, length - 2 * inset):
            return inset

        inset += 0.5

    return None


def _rectangle_inside(
    outline: tuple[Point, ...], width: float, length: float, margin: float = 0.5
) -> bool:
    """Whether a rectangle about the origin lies inside the outline, with room."""

    if width <= 0 or length <= 0:
        return False

    half_w, half_l = width / 2, length / 2
    steps = 2 + int(max(width, length))
    samples = []

    for index in range(steps + 1):
        t = index / steps
        x, y = -half_w + width * t, -half_l + length * t
        samples += [(x, -half_l), (x, half_l), (-half_w, y), (half_w, y)]

    return all(board_outline.depth_inside(outline, s) >= margin for s in samples)


def _components(
    data: Mapping[str, Any],
    width: float,
    length: float,
    outline: tuple[Point, ...] | None = None,
) -> tuple[BoardComponentSpec, ...]:
    envelope = data.get("envelope")

    if envelope is not None:
        inset = _envelope_inset(outline, width, length, data) or 0.0

        return (
            BoardComponentSpec(
                identifier=ENVELOPE_IDENTIFIER,
                center_x_mm=0.0,
                center_y_mm=0.0,
                width_mm=width - 2 * inset,
                depth_mm=length - 2 * inset,
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


def _optional(section: Mapping[str, Any], name: str, default: float) -> float:
    """An optional number, the default when absent or ``null``, as the check reads it."""

    value = section.get(name)

    return default if value is None else float(value)


def board_from_data(
    data: Mapping[str, Any], origin: BoardOrigin, *, catalog: bool = False
) -> BoardFileSpec:
    """Build a board from checked contents; refuses a file with errors.

    ``catalog`` marks a board read from the catalog's data directory, which is
    verified if it says which trials verified it."""

    report, outline = _check(data)

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
            center_offset_mm=_optional(connector, "center_offset_mm", 0.0),
            bottom_offset_from_board_top_mm=_optional(
                connector, "bottom_offset_from_board_top_mm", 0.0
            ),
        ),
        components=_components(data, width, length, outline),
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
        recommended_standoff_height_mm=_optional(standoff, "height_mm", 3.0),
        recommended_clearance_mm=_optional(standoff, "clearance_mm", 0.5),
        name=str(data.get("name", data["identifier"])),
        source=str(data.get("source", "")),
        notes=str(data.get("notes", "")),
        power_figure=figure,
        origin=origin,
        warnings=report.warnings,
        outline_points_mm=outline,
        verified=catalog and bool(data.get("verified_by")),
        verified_by=str(data.get("verified_by") or ""),
        catalog=catalog,
        test_points=parse_test_points(data),
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
        "test_points": [
            {
                "identifier": "TP1",
                "x_mm": -8.0,
                "y_mm": 12.5,
                "pad_diameter_mm": 3.0,
                "side": "top",
                "net": "3V3",
            },
            {
                "identifier": "TP2",
                "x_mm": 8.0,
                "y_mm": 12.5,
                "pad_diameter_mm": 3.0,
                "side": "top",
                "net": "GND",
            },
        ],
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
