"""Electronics layers: a plate and spacers that stack over a board.

A **layer file** names a board file by hash and says how a layer goes over it: the fastener,
the air to leave over its tallest part, the plate's thickness. ``layer build`` makes:

- a **spacer**, a tube round the fastener, tall enough to clear the board's tallest part with
  the air the file asks for. Print as many as the board has holes; and
- a **plate** the shape of the board's outline, bolted over the spacers through the board's
  mounting holes, with an opening cut over each part the board file says is reached from an
  edge (open to that edge) and over each part that draws air from above (a window).

The engine places the plate and the spacers. It does not connect anything: a header that joins
two boards, its alignment and what it carries are the user's.

``check-layers`` says whether two layers stack: their holes must be the same pattern, since one
bolt passes through both, and the fastener must pass them. The air over a part, the margin round an
opening and the spacer's wall are the engine's own design choices.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.board_solids import board_assembly
from zcad_core.features.guide_bores import printer_numbers
from zcad_core.features.guide_common import IDENTIFIER, Findings, number, section
from zcad_core.features.pcb_fixture_plan import mounting_holes, outline_points
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.hardware import get_fastener, list_fasteners, load_board
from zcad_core.hardware.electronics.board_file import (
    ENVELOPE_IDENTIFIER,
    BoardFileSpec,
)

LAYER_SCHEMA_VERSION = "1.0.0"
LAYER_KIND = "layer"
LAYER_RECORD_KIND = "layer-build"
DEFAULT_CLEARANCE_MM = 1.0
DEFAULT_PLATE_MM = 2.0
DEFAULT_WALL_MM = 1.2
# Room round an opening over a part.
OPENING_MARGIN_MM = 1.0
# A spacer stands this far from a part, in the plane of the board.
SPACER_MARGIN_MM = 0.3
# How far the hole patterns of two layers may differ and still count as one.
HOLE_TOLERANCE_MM = 0.1
_TOLERANCE_MM3 = 1e-3
_SHA256_LENGTH = 64
_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "file_kind",
        "identifier",
        "name",
        "units",
        "source",
        "notes",
        "board",
        "fastener",
        "clearance_mm",
        "spacer_mm",
        "plate_mm",
        "wall_mm",
        "needs_review",
    }
)
NOT_CLAIMED = (
    "The engine places a plate and spacers: it makes no electrical connection, and "
    "states nothing about a header's alignment or what it carries."
)
_EDGE_AXIS = {
    "negative_x": (0, -1),
    "positive_x": (0, 1),
    "negative_y": (1, -1),
    "positive_y": (1, 1),
}


@dataclass(frozen=True)
class LayerSpec:
    """A layer as its file describes it."""

    identifier: str
    name: str
    board_path: Path
    board_sha256: str
    fastener: str
    clearance_mm: float
    spacer_mm: float | None
    plate_mm: float
    wall_mm: float
    source: str
    file_path: Path
    file_sha256: str


@dataclass(frozen=True)
class LayerCheck:
    """What a check found: errors make a layer unusable; warnings do not."""

    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    summary: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class Layer:
    """The built plate and spacer, what was checked, and what the build noted."""

    spec: LayerSpec
    parts: dict[str, cq.Workplane]
    checks: dict[str, bool]
    summary: dict[str, Any]
    notes: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def layer_template(board_file: Path | None = None) -> dict[str, Any]:
    """An example layer file to edit, naming ``board_file`` by its real hash if given."""

    digest = (
        hashlib.sha256(board_file.read_bytes()).hexdigest()
        if board_file is not None and board_file.is_file()
        else "0" * _SHA256_LENGTH
    )

    return {
        "schema_version": LAYER_SCHEMA_VERSION,
        "file_kind": LAYER_KIND,
        "identifier": "EXAMPLE_LAYER",
        "name": "Example layer: replace every value",
        "units": "mm",
        "source": "EXAMPLE ONLY: say what this layer is for",
        "board": {
            "file": str(board_file) if board_file is not None else "board.json",
            "sha256": digest,
        },
        "fastener": "M2.5",
        "clearance_mm": DEFAULT_CLEARANCE_MM,
        "plate_mm": DEFAULT_PLATE_MM,
        "wall_mm": DEFAULT_WALL_MM,
    }


def check_layer_data(data: Any) -> LayerCheck:
    """Check a layer file's contents without reading what it names."""

    findings = Findings()

    if not isinstance(data, Mapping):
        return LayerCheck(("A layer file must hold a JSON object",), ())

    if data.get("schema_version") != LAYER_SCHEMA_VERSION:
        findings.errors.append(
            f"schema_version must be {LAYER_SCHEMA_VERSION!r}, not "
            f"{data.get('schema_version')!r}"
        )

    if data.get("file_kind") != LAYER_KIND:
        findings.errors.append(
            f"file_kind must be {LAYER_KIND!r}: this is not a layer file"
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

    _check_board_entry(data, findings)

    if data.get("fastener") not in list_fasteners():
        findings.errors.append(
            f"fastener must name a catalogued fastener: {list(list_fasteners())}"
        )

    for name, low, high, required in (
        ("clearance_mm", 0.1, 20.0, False),
        ("spacer_mm", 0.5, 100.0, False),
        ("plate_mm", 0.4, 20.0, False),
        ("wall_mm", 0.4, 10.0, False),
    ):
        number(data, name, "", findings, low=low, high=high, required=required)

    if not str(data.get("source", "")).strip():
        findings.warnings.append("No source is stated: say what this layer is for")

    return LayerCheck(tuple(findings.errors), tuple(findings.warnings))


def _check_board_entry(data: Mapping[str, Any], findings: Findings) -> None:
    entry = section(data, "board", findings)

    if entry is None:
        return

    if not isinstance(entry.get("file"), str) or not str(entry["file"]).strip():
        findings.errors.append("board.file must name the board file")

    digest = entry.get("sha256")

    if not isinstance(digest, str) or len(digest) != _SHA256_LENGTH:
        findings.errors.append(
            "board.sha256 must be the file's SHA-256 as 64 lower-case hex digits"
        )


def read_layer_file(path: Path) -> tuple[Any, str]:
    """A layer file's contents and its SHA-256."""

    raw = path.read_bytes()

    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error


def layer_from_data(data: Mapping[str, Any], path: Path, sha256: str) -> LayerSpec:
    """A layer from checked contents; refuses a file with errors."""

    report = check_layer_data(data)

    if not report.valid:
        raise ValueError(
            f"{path} is not a valid layer file:\n- " + "\n- ".join(report.errors)
        )

    board_path = Path(data["board"]["file"])
    spacer = data.get("spacer_mm")

    return LayerSpec(
        identifier=str(data["identifier"]),
        name=str(data.get("name", data["identifier"])),
        board_path=(
            board_path
            if board_path.is_absolute()
            else (path.parent / board_path).resolve()
        ),
        board_sha256=str(data["board"]["sha256"]),
        fastener=str(data["fastener"]),
        clearance_mm=float(data.get("clearance_mm", DEFAULT_CLEARANCE_MM)),
        spacer_mm=None if spacer is None else float(spacer),
        plate_mm=float(data.get("plate_mm", DEFAULT_PLATE_MM)),
        wall_mm=float(data.get("wall_mm", DEFAULT_WALL_MM)),
        source=str(data.get("source", "")),
        file_path=path,
        file_sha256=sha256,
    )


def load_layer(path: Path) -> LayerSpec:
    """A layer from a file, refused if it has errors."""

    data, digest = read_layer_file(path)

    return layer_from_data(data, path, digest)


def load_layer_board(spec: LayerSpec) -> BoardFileSpec:
    """The board a layer names, refused if it has changed since the layer file named it."""

    if not spec.board_path.is_file():
        raise ValueError(f"{spec.board_path} is missing")

    digest = hashlib.sha256(spec.board_path.read_bytes()).hexdigest()

    if digest != spec.board_sha256:
        raise ValueError(
            f"{spec.board_path} has changed since the layer file named it: its hash is "
            f"{digest}, not {spec.board_sha256}"
        )

    return load_board(spec.board_path)


@dataclass(frozen=True)
class LayerPlan:
    """The sizes of a layer, worked out from its board."""

    holes: tuple[tuple[float, float], ...]
    hole_diameter_mm: float
    bore_mm: float
    outer_mm: float
    tallest_mm: float
    tallest_part: str
    minimum_spacer_mm: float
    spacer_mm: float


@dataclass(frozen=True)
class _Part:
    """A part as the plate sees it: a footprint, a height, and how it is reached."""

    identifier: str
    center_x_mm: float
    center_y_mm: float
    width_mm: float
    depth_mm: float
    bottom_offset_from_board_top_mm: float
    height_mm: float
    access_edge: str | None
    lid_vent: bool


def _connector(board: BoardFileSpec) -> _Part:
    """The cable connector as a part against its edge, open to that edge."""

    usb = board.usb_connector
    edge = str(usb.board_edge)
    along_x = edge.endswith("y")
    half = (board.board_length_mm if along_x else board.board_width_mm) / 2
    across = (half - usb.depth_mm / 2) * (1 if edge.startswith("positive") else -1)

    return _Part(
        identifier=usb.identifier,
        center_x_mm=usb.center_offset_mm if along_x else across,
        center_y_mm=across if along_x else usb.center_offset_mm,
        width_mm=usb.width_mm if along_x else usb.depth_mm,
        depth_mm=usb.depth_mm if along_x else usb.width_mm,
        bottom_offset_from_board_top_mm=usb.bottom_offset_from_board_top_mm,
        height_mm=usb.height_mm,
        access_edge=edge,
        lid_vent=False,
    )


def _real_parts(board: BoardFileSpec) -> list[Any]:
    """The board's parts and its cable connector, without the envelope."""

    parts = [c for c in board.components if c.identifier != ENVELOPE_IDENTIFIER]

    return [*parts, _connector(board)]


def _tallest(board: BoardFileSpec) -> tuple[float, str]:
    """The highest top above the board's top face, and which part it is."""

    parts: list[Any] = [*board.components, _connector(board)]
    tops = [
        (c.bottom_offset_from_board_top_mm + c.height_mm, c.identifier) for c in parts
    ]

    return max(tops, default=(0.0, "the board"), key=lambda top: top[0])


def _part_gap(hole: tuple[float, float], radius: float, part: Any) -> float:
    """How far a circle at ``hole`` is from a part's footprint, in the board's plane."""

    dx = max(abs(hole[0] - part.center_x_mm) - part.width_mm / 2, 0.0)
    dy = max(abs(hole[1] - part.center_y_mm) - part.depth_mm / 2, 0.0)

    return math.hypot(dx, dy) - radius


def plan_layer(
    spec: LayerSpec, board: BoardFileSpec, errors: list[str]
) -> LayerPlan | None:
    """The layer's sizes, with every reason it cannot be built added to ``errors``."""

    holes = tuple(mounting_holes(board))
    fastener = get_fastener(spec.fastener)

    if not holes or board.mounting_hole_diameter_mm is None:
        errors.append(
            f"{board.identifier} has no mounting holes for a layer to bolt through"
        )

        return None

    if fastener.nominal_diameter_mm > board.mounting_hole_diameter_mm:
        errors.append(
            f"{spec.fastener} is {fastener.nominal_diameter_mm:g} mm across and the "
            f"board's holes are {board.mounting_hole_diameter_mm:g} mm: it will not pass"
        )

    bore = fastener.clearance_hole_mm
    outer = bore + 2 * spec.wall_mm
    tallest, part = _tallest(board)
    minimum = max(tallest, 0.0) + spec.clearance_mm
    height = (
        spec.spacer_mm if spec.spacer_mm is not None else math.ceil(minimum * 2) / 2
    )

    if height < minimum - 1e-9:
        errors.append(
            f"spacer_mm is {height:g}, under the {minimum:g} mm needed to clear the "
            f"{part}, {tallest:g} mm tall, with {spec.clearance_mm:g} mm over it"
        )

    for hole in holes:
        for item in _real_parts(board):
            if item.bottom_offset_from_board_top_mm + item.height_mm <= 0:
                continue

            if _part_gap(hole, outer / 2 + SPACER_MARGIN_MM, item) < 0:
                errors.append(
                    f"a spacer at ({hole[0]:g}, {hole[1]:g}) would stand on {item.identifier}: "
                    f"it is {max(_part_gap(hole, outer / 2, item), 0):.1f} mm from it and "
                    f"needs {SPACER_MARGIN_MM:g} mm; use a thinner wall or a smaller fastener"
                )

    return LayerPlan(
        holes=holes,
        hole_diameter_mm=float(board.mounting_hole_diameter_mm),
        bore_mm=bore,
        outer_mm=outer,
        tallest_mm=tallest,
        tallest_part=part,
        minimum_spacer_mm=round(minimum, 3),
        spacer_mm=height,
    )


def _openings(board: BoardFileSpec) -> list[tuple[float, float, float, float, str]]:
    """The rectangles ``(x0, x1, y0, y1, why)`` the plate is cut away over: an edge part's
    footprint open to its edge, and a vented part's footprint."""

    reach = max(board.board_width_mm, board.board_length_mm)
    boxes = []

    for part in _real_parts(board):
        x0 = part.center_x_mm - part.width_mm / 2 - OPENING_MARGIN_MM
        x1 = part.center_x_mm + part.width_mm / 2 + OPENING_MARGIN_MM
        y0 = part.center_y_mm - part.depth_mm / 2 - OPENING_MARGIN_MM
        y1 = part.center_y_mm + part.depth_mm / 2 + OPENING_MARGIN_MM

        if part.access_edge is not None:
            axis, sign = _EDGE_AXIS[str(part.access_edge)]
            low, high = (x0, x1) if axis == 0 else (y0, y1)
            low, high = (low, reach) if sign > 0 else (-reach, high)
            x0, x1, y0, y1 = (low, high, y0, y1) if axis == 0 else (x0, x1, low, high)
            boxes.append((x0, x1, y0, y1, f"{part.identifier}, open to its edge"))
        elif part.lid_vent:
            boxes.append(
                (x0, x1, y0, y1, f"{part.identifier}, which draws air from above")
            )

    return boxes


def _opening_errors(
    plan: LayerPlan,
    boxes: list[tuple[float, float, float, float, str]],
    least_wall: float,
) -> list[str]:
    errors = []

    for x0, x1, y0, y1, why in boxes:
        for hx, hy in plan.holes:
            dx = max(x0 - hx, 0.0, hx - x1)
            dy = max(y0 - hy, 0.0, hy - y1)
            gap = math.hypot(dx, dy) - plan.bore_mm / 2

            if gap < least_wall:
                errors.append(
                    f"the opening over {why} comes within {max(gap, 0):.1f} mm of the "
                    f"hole at ({hx:g}, {hy:g}), under the printer's {least_wall:g} mm minimum wall"
                )

    return errors


def layer_summary(
    spec: LayerSpec, board: BoardFileSpec, plan: LayerPlan
) -> dict[str, Any]:
    return {
        "board": board.identifier,
        "board_sha256": spec.board_sha256,
        "fastener": spec.fastener,
        "holes": [list(h) for h in plan.holes],
        "tallest_part": plan.tallest_part,
        "tallest_mm": round(plan.tallest_mm, 3),
        "clearance_mm": spec.clearance_mm,
        "minimum_spacer_mm": plan.minimum_spacer_mm,
        "spacer_mm": plan.spacer_mm,
        "spacer_bore_mm": round(plan.bore_mm, 3),
        "spacer_outer_mm": round(plan.outer_mm, 3),
        "spacers_to_print": len(plan.holes),
        "plate_mm": spec.plate_mm,
        "stack_height_mm": round(plan.spacer_mm + spec.plate_mm, 3),
        "openings": [why for *_, why in _openings(board)],
    }


def check_layer_file(
    path: Path, printer: Mapping[str, Any] | None = None
) -> LayerCheck:
    """Check a layer file, the board it names, and the layer against the printer."""

    data, digest = read_layer_file(path)
    report = check_layer_data(data)

    if not report.valid:
        return report

    spec = layer_from_data(data, path, digest)

    try:
        board = load_layer_board(spec)
    except ValueError as error:
        return LayerCheck((*report.errors, str(error)), report.warnings)

    errors: list[str] = []
    plan = plan_layer(spec, board, errors)

    if printer is not None:
        _, least_wall, least_floor = printer_numbers(printer)

        if spec.wall_mm < least_wall:
            errors.append(
                f"wall_mm is {spec.wall_mm:g}, under the printer's {least_wall:g} mm minimum wall"
            )

        if spec.plate_mm < least_floor:
            errors.append(
                f"plate_mm is {spec.plate_mm:g}, under the printer's {least_floor:g} mm minimum floor"
            )

        if plan is not None:
            errors += _opening_errors(plan, _openings(board), least_wall)

    summary = layer_summary(spec, board, plan) if plan is not None else None

    return LayerCheck(tuple(errors), report.warnings, summary)


def _spacer(plan: LayerPlan) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .circle(plan.outer_mm / 2)
        .circle(plan.bore_mm / 2)
        .extrude(plan.spacer_mm)
    )


def _plate(spec: LayerSpec, board: BoardFileSpec, plan: LayerPlan) -> cq.Workplane:
    """The plate in the board's frame: the outline over the spacers' tops."""

    z0 = plan.spacer_mm
    plate = outline_prism(outline_points(board), z0, z0 + spec.plate_mm)
    cutters = [
        cq.Workplane("XY")
        .workplane(offset=z0 - 1.0)
        .pushPoints(list(plan.holes))
        .circle(plan.bore_mm / 2)
        .extrude(spec.plate_mm + 2.0)
    ]

    for x0, x1, y0, y1, _ in _openings(board):
        cutters.append(
            cq.Workplane("XY")
            .box(x1 - x0, y1 - y0, spec.plate_mm + 2.0, centered=False)
            .translate((x0, y0, z0 - 1.0))
        )

    for cutter in cutters:
        plate = plate.cut(cutter)

    return plate


def _count(model: cq.Workplane) -> int:
    return len(workplane_shape(model).Solids())


def build_layer(spec: LayerSpec, printer: Mapping[str, Any]) -> Layer:
    """The plate and spacer a layer file describes, refused if it cannot be built."""

    board = load_layer_board(spec)
    errors: list[str] = []
    plan = plan_layer(spec, board, errors)

    if plan is None or errors:
        raise ValueError("The layer cannot be built:\n- " + "\n- ".join(errors))

    _, least_wall, _ = printer_numbers(printer)
    errors = _opening_errors(plan, _openings(board), least_wall)

    if errors:
        raise ValueError("The layer cannot be built:\n- " + "\n- ".join(errors))

    plate = _plate(spec, board, plan)
    spacer = _spacer(plan)
    in_place = cq.Workplane("XY").add(
        cq.Compound.makeCompound(
            [workplane_shape(spacer.translate((x, y, 0.0))) for x, y in plan.holes]
        )
    )
    parts_of_board = board_assembly(board, with_envelope=False)
    checks = {
        "plate.one_solid": _count(plate) == 1,
        "spacer.one_solid": _count(spacer) == 1,
        "spacers_clear_of_the_board": intersection_volume(
            parts_of_board, workplane_shape(in_place)
        )
        <= _TOLERANCE_MM3,
        "plate_clear_of_the_board": intersection_volume(
            parts_of_board, workplane_shape(plate)
        )
        <= _TOLERANCE_MM3,
    }

    return Layer(
        spec=spec,
        parts={
            "plate": plate.translate((0.0, 0.0, -plan.spacer_mm)),
            "spacer": spacer,
        },
        checks=checks,
        summary=layer_summary(spec, board, plan),
        notes=(NOT_CLAIMED,),
    )


@dataclass(frozen=True)
class LayersReport:
    """Whether two layers stack, and every reason they do not."""

    stacks: bool
    errors: tuple[str, ...]
    summary: dict[str, Any]


def _sorted_holes(holes: list[list[float]]) -> list[tuple[float, float]]:
    return sorted((float(x), float(y)) for x, y in holes)


def _summary_of(
    path: Path, printer: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """What a layer says of itself, from its file or from its build record; a record is
    not trusted if the board it names has changed since the build."""

    if path.suffix == ".json" and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None

        if isinstance(data, dict) and data.get("record_kind") == LAYER_RECORD_KIND:
            return _summary_of_record(path, data)

    report = check_layer_file(path, printer)

    return report.summary, [f"{path.name}: {e}" for e in report.errors]


def _summary_of_record(
    path: Path, record: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    board = Path(record["board"]["path"])

    if not board.is_file():
        return None, [f"{path.name}: the board {board} is missing"]

    digest = hashlib.sha256(board.read_bytes()).hexdigest()

    if digest != record["board"]["sha256"]:
        message = (
            f"{path.name}: the board {board} has changed since the build: its hash is "
            f"{digest[:12]}, not {record['board']['sha256'][:12]}"
        )

        return None, [message]

    return record["summary"], []


def check_layers(
    upper_file: Path, lower_file: Path, printer: Mapping[str, Any]
) -> LayersReport:
    """Whether the upper layer's board stacks over the lower layer: the same hole
    pattern, since one bolt passes through both, and a fastener that passes them."""

    upper, upper_errors = _summary_of(upper_file, printer)
    lower, lower_errors = _summary_of(lower_file, printer)
    errors = [*upper_errors, *lower_errors]

    if errors or upper is None or lower is None:
        return LayersReport(False, tuple(errors), {})

    summary: dict[str, Any] = {
        "upper": upper["board"],
        "lower": lower["board"],
        "stack_height_mm": round(lower["stack_height_mm"], 3),
        "not_claimed": NOT_CLAIMED,
    }
    up, down = _sorted_holes(upper["holes"]), _sorted_holes(lower["holes"])

    if len(up) != len(down):
        errors.append(
            f"They have {len(up)} and {len(down)} mounting holes: one bolt passes "
            "through both, so the patterns must be the same"
        )
    else:
        worst = max(
            math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(up, down, strict=True)
        )
        summary["hole_offset_mm"] = round(worst, 3)

        if worst > HOLE_TOLERANCE_MM:
            errors.append(
                f"The hole patterns differ by {worst:.2f} mm at their worst, over "
                f"{HOLE_TOLERANCE_MM:g} mm: a bolt would not pass both boards"
            )

    if upper["fastener"] != lower["fastener"]:
        errors.append(
            f"They use different fasteners: {upper['fastener']} and {lower['fastener']}"
        )

    return LayersReport(not errors, tuple(errors), summary)


def require_layer_fits_bed(layer: Layer, printer: Mapping[str, Any]) -> None:
    """Refuse a part that will not lie on the printer's bed."""

    volume = printer.get("build_volume_mm")

    if not volume:
        return

    for name, model in layer.parts.items():
        box = workplane_shape(model).BoundingBox()
        fits = box.xlen <= volume["x"] and box.ylen <= volume["y"]
        turned = box.xlen <= volume["y"] and box.ylen <= volume["x"]

        if not (fits or turned) or box.zlen > volume["z"]:
            raise ValueError(
                f"The {name} is {box.xlen:.0f} x {box.ylen:.0f} x {box.zlen:.0f} mm; "
                f"the printer's bed is {volume['x']:.0f} x {volume['y']:.0f} x "
                f"{volume['z']:.0f} mm"
            )
