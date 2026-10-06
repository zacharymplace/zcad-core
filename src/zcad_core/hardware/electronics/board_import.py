"""Read a board from its vendor STEP model.

One extraction serves the catalog (``scripts/extract-board-components.py``) and
``zcad-validation board import``, so the two cannot drift apart. From the
model's solids it:

- finds the PCB: the solid with the largest footprint whose thickness, along
  the model's Z axis, is 0.4 to 3.2 mm;
- takes its outline and thickness from that solid's bounding box, and its
  circular through-holes from its cylindrical faces;
- keeps every other part rising more than 0.5 mm above the board or reaching
  that far below it, splits a part through the board into a box above and a
  box below, merges parts of a similar height lying within 2 mm of each other
  (never into a box over a mounting hole none of them covers, nor one reaching
  onto a standoff none of them reaches, since a standoff or screw stands
  there), and marks a part overhanging an edge as needing
  access through it, like a barrel jack.

The frame is the model's, centred on the PCB: +X to the right and +Y up the
page seen from above, with the model's +Z up. The cable connector cannot be
guessed, so an import lists the parts that overhang an edge and writes the file
unreviewed, which the loader refuses until a connector is named.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface  # type: ignore[import-untyped]

from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_file import BOARD_SCHEMA_VERSION
from zcad_core.hardware.electronics.board_outline import Point

# x0 x1 y0 y1 z0 z1, millimetres from the PCB's centre and its top face.
Box = tuple[float, float, float, float, float, float]

MINIMUM_HEIGHT_MM = 0.5
MERGE_GAP_MM = 2.0
OVERHANG_MM = 0.3
# Parts are merged only with parts in the same height tier (mm above board).
HEIGHT_TIERS_MM = (1.5, 4.0)
PCB_THICKNESS_MM = (0.4, 3.2)
# A mounting hole is at least this wide; narrower ones are vias and pins.
MINIMUM_HOLE_MM = 1.6
# How far a standoff reaches beyond its hole's edge: its 1.5 mm wall, up to
# 0.2 mm of hole clearance, and 0.3 mm to spare. A merged box must not come
# this close to a hole unless one of its parts already does.
STANDOFF_REACH_MM = 2.0
# Below this share of its bounding box's volume, the PCB is not a plain rectangle.
RECTANGULAR_SHARE = 0.9
# A top outline filling this much of its bounding rectangle is written as one.
PLAIN_RECTANGLE_SHARE = 0.999
# An outline's points within this of the loop they lie on are dropped.
SIMPLIFY_MM = 0.02
EDGES = ("negative_x", "positive_x", "negative_y", "positive_y")


def turn(box: Box, turns: int) -> Box:
    """Turn a box counter-clockwise, seen from above, by quarter turns."""

    x0, x1, y0, y1, z0, z1 = box

    for _ in range(turns % 4):
        x0, x1, y0, y1 = -y1, -y0, x0, x1

    return x0, x1, y0, y1, z0, z1


def _tier(box: Box) -> int:
    return sum(box[5] > limit for limit in HEIGHT_TIERS_MM)


def _touching(a: Box, b: Box) -> bool:
    return (
        a[0] - MERGE_GAP_MM <= b[1]
        and b[0] - MERGE_GAP_MM <= a[1]
        and a[2] - MERGE_GAP_MM <= b[3]
        and b[2] - MERGE_GAP_MM <= a[3]
    )


def _covers(box: Box, point: tuple[float, float]) -> bool:
    return box[0] <= point[0] <= box[1] and box[2] <= point[1] <= box[3]


def _reaches(box: Box, point: tuple[float, float], reach_mm: float) -> bool:
    dx = max(box[0] - point[0], 0.0, point[0] - box[1])
    dy = max(box[2] - point[1], 0.0, point[1] - box[3])

    return math.hypot(dx, dy) < reach_mm


def _blocked(
    a: Box, b: Box, union: Box, hole: tuple[float, float], reach: float
) -> bool:
    """Whether merging ``a`` and ``b`` would put a box over the hole, or onto
    its standoff, where neither part was."""

    if _covers(union, hole) and not _covers(a, hole) and not _covers(b, hole):
        return True

    return (
        _reaches(union, hole, reach)
        and not _reaches(a, hole, reach)
        and not _reaches(b, hole, reach)
    )


def merge_boxes(
    boxes: Sequence[Box],
    same_tier: bool,
    holes: Sequence[tuple[float, float]],
    *,
    hole_diameter_mm: float,
) -> list[Box]:
    """Merge touching boxes, keeping parts either side of a hole apart and
    off a standoff that none of them reaches."""

    reach = hole_diameter_mm / 2 + STANDOFF_REACH_MM
    merged = list(boxes)
    changed = True

    while changed:
        changed = False

        for i, a in enumerate(merged):
            for j in range(i + 1, len(merged)):
                b = merged[j]

                if not _touching(a, b) or (same_tier and _tier(a) != _tier(b)):
                    continue

                union = (
                    min(a[0], b[0]),
                    max(a[1], b[1]),
                    min(a[2], b[2]),
                    max(a[3], b[3]),
                    min(a[4], b[4]),
                    max(a[5], b[5]),
                )

                if not any(_blocked(a, b, union, hole, reach) for hole in holes):
                    merged[i] = union
                    del merged[j]
                    changed = True
                    break

            if changed:
                break

    return sorted(merged)


def access_edge(box: Box, width_mm: float, length_mm: float) -> str | None:
    """The edge a box overhangs by more than 0.3 mm, if any."""

    half_w, half_l = width_mm / 2, length_mm / 2
    overhangs = {
        "negative_x": -half_w - box[0],
        "positive_x": box[1] - half_w,
        "negative_y": -half_l - box[2],
        "positive_y": box[3] - half_l,
    }
    edge, overhang = max(overhangs.items(), key=lambda item: item[1])

    return edge if overhang > OVERHANG_MM else None


def part_boxes(
    solids: Sequence[cq.Shape],
    pcb_index: int,
    thickness_mm: float,
    quarter_turns: int = 0,
) -> tuple[list[Box], list[Box]]:
    """Every part but the PCB as a box above the board and a box below it.

    ``pcb_index`` counts from 1. Heights are above the PCB's top face; a part
    through the board is split in two. ``thickness_mm`` re-bases the boxes
    below the board, so a catalogued board's spec thickness is used for it.
    """

    pcb = solids[pcb_index - 1].BoundingBox()
    centre_x, centre_y = (pcb.xmin + pcb.xmax) / 2, (pcb.ymin + pcb.ymax) / 2
    above: list[Box] = []
    below: list[Box] = []

    for index, solid in enumerate(solids, start=1):
        if index == pcb_index:
            continue

        b = solid.BoundingBox()
        x0, x1, y0, y1, _, _ = turn(
            (
                b.xmin - centre_x,
                b.xmax - centre_x,
                b.ymin - centre_y,
                b.ymax - centre_y,
                0,
                0,
            ),
            quarter_turns,
        )
        top = b.zmax - pcb.zmax
        bottom = b.zmin - pcb.zmin

        if top > MINIMUM_HEIGHT_MM:
            above.append((x0, x1, y0, y1, max(b.zmin - pcb.zmax, 0.0), top))

        if bottom < -MINIMUM_HEIGHT_MM:
            below.append(
                (
                    x0,
                    x1,
                    y0,
                    y1,
                    bottom - thickness_mm,
                    min(b.zmax - pcb.zmin, 0) - thickness_mm,
                )
            )

    return above, below


def component_records(
    boxes: Sequence[Box], width_mm: float, length_mm: float
) -> list[dict[str, Any]]:
    """Boxes as the ``components`` a board file and the catalog both carry."""

    return [
        {
            "identifier": f"{'top' if box[4] >= 0 else 'bottom'}-{number:02d}",
            "center_x_mm": round((box[0] + box[1]) / 2, 3),
            "center_y_mm": round((box[2] + box[3]) / 2, 3),
            "width_mm": round(box[1] - box[0], 3),
            "depth_mm": round(box[3] - box[2], 3),
            "bottom_offset_from_board_top_mm": round(box[4], 3),
            "height_mm": round(box[5] - box[4], 3),
            "access_edge": access_edge(box, width_mm, length_mm),
        }
        for number, box in enumerate(boxes, start=1)
    ]


def load_solids(path: Path) -> list[cq.Shape]:
    return [
        solid
        for solid in cq.importers.importStep(str(path)).solids().vals()
        if isinstance(solid, cq.Shape)
    ]


def find_pcb(solids: Sequence[cq.Shape]) -> int:
    """The 1-based index of the solid most like a PCB, or a refusal saying why
    none is."""

    low, high = PCB_THICKNESS_MM
    best: tuple[float, int] | None = None

    for index, solid in enumerate(solids, start=1):
        b = solid.BoundingBox()

        if not low <= b.zlen <= high:
            continue

        area = b.xlen * b.ylen

        if b.zlen < min(b.xlen, b.ylen) and (best is None or area > best[0]):
            best = (area, index)

    if best is None:
        raise ValueError(
            f"No solid is {low:g} to {high:g} mm thick along Z, so none can be "
            "the PCB. The model must have +Z up; name the PCB with "
            "--pcb-solid-index if it is modelled another way"
        )

    return best[1]


@dataclass(frozen=True)
class Hole:
    x_mm: float
    y_mm: float
    diameter_mm: float


def through_holes(
    solid: cq.Shape, minimum_diameter_mm: float = MINIMUM_HOLE_MM
) -> list[Hole]:
    """The circular holes through a PCB solid: cylindrical faces about the
    vertical axis that span its thickness, whose axis lies in the void. Holes
    narrower than ``minimum_diameter_mm`` (vias and pins, on a board) are left
    out."""

    b = solid.BoundingBox()
    found: dict[tuple[float, float, float], Hole] = {}

    for face in solid.Faces():
        if face.geomType() != "CYLINDER":
            continue

        faces = face.BoundingBox()

        if faces.zlen < 0.9 * b.zlen:
            continue

        cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
        axis = cylinder.Axis()

        if abs(axis.Direction().Z()) < 0.999:
            continue

        x, y, radius = axis.Location().X(), axis.Location().Y(), cylinder.Radius()
        inside = (
            b.xmin + radius <= x <= b.xmax - radius
            and b.ymin + radius <= y <= b.ymax - radius
        )

        if (
            2 * radius < minimum_diameter_mm
            or not inside
            or cast(cq.Solid, solid).isInside(
                cq.Vector(x, y, (b.zmin + b.zmax) / 2), 1e-3
            )
        ):
            continue

        key = (round(x, 2), round(y, 2), round(2 * radius, 2))
        found[key] = Hole(x, y, 2 * radius)

    return sorted(found.values(), key=lambda hole: (hole.y_mm, hole.x_mm))


def _edge_points(edge: cq.Edge) -> list[Point]:
    """An edge's points from its start to its end: both ends of a line, and a
    curve sampled about every half millimetre."""

    start, end = edge.startPoint(), edge.endPoint()

    if edge.geomType() == "LINE":
        return [(start.x, start.y), (end.x, end.y)]

    count = min(60, max(4, math.ceil(edge.Length() / 0.5)))
    points = [edge.positionAt(i / count) for i in range(count + 1)]

    # A curve's own direction need not be the edge's: walk it from the start.
    if start.sub(points[0]).Length > start.sub(points[-1]).Length:
        points.reverse()

    points[0], points[-1] = start, end

    return [(p.x, p.y) for p in points]


def pcb_outline(solid: cq.Shape) -> tuple[Point, ...] | None:
    """The outline of a PCB's top face about the centre of its bounding box, as
    a counter-clockwise polygon, or ``None`` if it cannot be read: the face's
    outer loop, with curves sampled."""

    box = solid.BoundingBox()
    tops = [
        face
        for face in solid.Faces()
        if face.geomType() == "PLANE"
        and face.BoundingBox().zlen < 1e-3
        and abs(face.BoundingBox().zmax - box.zmax) < 1e-3
    ]

    if not tops:
        return None

    face = max(tops, key=lambda f: f.Area())
    pieces = [_edge_points(edge) for edge in face.outerWire().Edges()]
    chain = pieces.pop(0)

    while pieces:
        tail = chain[-1]

        for position, piece in enumerate(pieces):
            if math.dist(piece[0], tail) < 1e-3:
                chain += piece[1:]
            elif math.dist(piece[-1], tail) < 1e-3:
                chain += piece[::-1][1:]
            else:
                continue

            del pieces[position]
            break
        else:
            return None

    if math.dist(chain[0], chain[-1]) < 1e-3:
        chain.pop()

    if not 3 <= len(chain) <= board_outline.MAXIMUM_POINTS:
        return None

    centre = ((box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2)
    points = list(
        board_outline.simplified(
            [(x - centre[0], y - centre[1]) for x, y in chain], SIMPLIFY_MM
        )
    )

    if not board_outline.is_simple(points):
        return None

    return board_outline.counter_clockwise(points)


def _hole_groups(holes: Sequence[Hole]) -> dict[float, list[Hole]]:
    """Holes grouped by diameter, those within 0.1 mm counting as one size;
    each group is keyed by its smallest diameter."""

    groups: dict[float, list[Hole]] = {}
    size: float | None = None
    last = 0.0

    for hole in sorted(holes, key=lambda hole: hole.diameter_mm):
        if size is None or hole.diameter_mm - last > 0.1:
            size = round(hole.diameter_mm, 2)
            groups[size] = []

        groups[size].append(hole)
        last = hole.diameter_mm

    return groups


@dataclass(frozen=True)
class ImportedBoard:
    """A board read from a model: the file's data, and what the reader noted."""

    data: dict[str, Any]
    report: dict[str, Any]


def _identifier(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("_.-").upper()

    return name or "IMPORTED_BOARD"


def _candidates(
    boxes: Sequence[Box], width_mm: float, length_mm: float
) -> list[dict[str, Any]]:
    """The parts that overhang an edge, largest first: a connector is one."""

    found = []

    for box, record in zip(
        boxes, component_records(boxes, width_mm, length_mm), strict=True
    ):
        if record["access_edge"] is None:
            continue

        found.append(
            {
                "identifier": record["identifier"],
                "edge": record["access_edge"],
                "size_mm": [
                    record["width_mm"],
                    record["depth_mm"],
                    record["height_mm"],
                ],
                "volume": (box[1] - box[0]) * (box[3] - box[2]) * (box[5] - box[4]),
            }
        )

    found.sort(key=lambda item: -item["volume"])

    for item in found:
        del item["volume"]

    return found


def connector_record(
    box: Box, edge: str, width_mm: float, length_mm: float, name: str
) -> dict[str, Any]:
    """A part's box as the cable connector: clipped to the outline, against its
    edge."""

    half_w, half_l = width_mm / 2, length_mm / 2
    along = (box[0], box[1]) if edge.endswith("_y") else (box[2], box[3])
    face = {
        "negative_x": (box[1], -half_w, True),
        "positive_x": (box[0], half_w, False),
        "negative_y": (box[3], -half_l, True),
        "positive_y": (box[2], half_l, False),
    }[edge]
    inner, outer, negative = face
    depth = (inner - outer) if negative else (outer - inner)

    return {
        "identifier": name,
        "edge": edge,
        "width_mm": round(along[1] - along[0], 3),
        "height_mm": round(box[5] - box[4], 3),
        "depth_mm": round(depth, 3),
        "center_offset_mm": round((along[0] + along[1]) / 2, 3),
        "bottom_offset_from_board_top_mm": round(box[4], 3),
    }


def import_step(
    path: Path,
    *,
    identifier: str | None = None,
    pcb_solid_index: int | None = None,
    cable_connector: str | None = None,
) -> ImportedBoard:
    """Read a board file's data from a vendor STEP model.

    The result carries ``needs_review`` for the cable connector unless
    ``cable_connector`` names one of the parts listed by an earlier import
    (``top-03``), which is then removed from the components and written as the
    connector.
    """

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    solids = load_solids(path)

    if not solids:
        raise ValueError(f"{path} holds no solids")

    index = pcb_solid_index if pcb_solid_index is not None else find_pcb(solids)

    if not 1 <= index <= len(solids):
        raise ValueError(f"--pcb-solid-index must be 1 to {len(solids)}")

    pcb = solids[index - 1]
    box = pcb.BoundingBox()
    width, length, thickness = (
        round(box.xlen, 3),
        round(box.ylen, 3),
        round(box.zlen, 3),
    )
    centre_x, centre_y = (box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2
    holes = through_holes(pcb)
    groups = _hole_groups(holes)
    sizes = {size: len(group) for size, group in groups.items()}
    mounting = (
        max(groups, key=lambda size: (len(groups[size]), -size)) if groups else None
    )
    mounting_holes = groups[mounting] if mounting is not None else []
    positions = [
        (hole.x_mm - centre_x, hole.y_mm - centre_y) for hole in mounting_holes
    ]
    above, below = part_boxes(solids, index, thickness)
    diameter = mounting if mounting is not None else 0.0
    boxes = merge_boxes(
        above, True, positions, hole_diameter_mm=diameter
    ) + merge_boxes(below, False, positions, hole_diameter_mm=diameter)
    candidates = _candidates(boxes, width, length)
    records = component_records(boxes, width, length)
    notes: list[str] = []
    data: dict[str, Any] = {
        "schema_version": BOARD_SCHEMA_VERSION,
        "identifier": identifier or _identifier(path),
        "name": f"Imported from {path.name}",
        "units": "mm",
        "outline": "rectangle",
        "source": (
            f"STEP model {path.name}, SHA-256 {sha}, read by board import; "
            "not checked against the real board"
        ),
        "notes": (
            "Read from the model's own frame, centred on the PCB, with the "
            "model's +Z up. Check the holes, the parts and the connector "
            "against the board, then remove needs_review."
        ),
        "board": {"width_mm": width, "length_mm": length, "thickness_mm": thickness},
    }

    if mounting is not None:
        data["mounting_holes"] = {
            "diameter_mm": mounting,
            "positions_mm": [[round(x, 3), round(y, 3)] for x, y in positions],
        }

    if cable_connector is None:
        data["needs_review"] = [
            (
                "cable_connector: name the part the cable plugs into with "
                "--cable-connector, from the report's candidates"
            )
        ]
        data["cable_connector"] = {
            "identifier": "CABLE_CONNECTOR",
            "edge": candidates[0]["edge"] if candidates else "negative_y",
            "width_mm": 1.0,
            "height_mm": 1.0,
            "depth_mm": 1.0,
            "center_offset_mm": 0.0,
            "bottom_offset_from_board_top_mm": 0.0,
        }
    else:
        chosen = [r for r in records if r["identifier"] == cable_connector]

        if not chosen or chosen[0]["access_edge"] is None:
            raise ValueError(
                f"{cable_connector} is not one of the parts that overhang an "
                f"edge: {', '.join(c['identifier'] for c in candidates) or 'none'}"
            )

        position = records.index(chosen[0])
        data["cable_connector"] = connector_record(
            boxes[position], chosen[0]["access_edge"], width, length, "CABLE_CONNECTOR"
        )
        del records[position]

    data["components"] = records
    data["wall_openings"] = []

    others = {size: count for size, count in sizes.items() if size != mounting}
    outline = pcb_outline(pcb)
    polygon_area = abs(board_outline.signed_area(outline)) if outline else 0.0
    shape_share = polygon_area / (width * length) if outline else 1.0

    if outline is not None and shape_share < PLAIN_RECTANGLE_SHARE:
        data["outline"] = {
            "type": "polygon",
            "points_mm": [[round(x, 3), round(y, 3)] for x, y in outline],
        }
        notes.append(
            f"The PCB is not a plain rectangle: its outline is written as a "
            f"polygon of {len(outline)} points ({shape_share:.1%} of its "
            "bounding rectangle). Check it against the board"
        )

    volume_share = pcb.Volume() / (box.xlen * box.ylen * box.zlen)

    if volume_share < RECTANGULAR_SHARE and data["outline"] == "rectangle":
        notes.append(
            f"The PCB fills {volume_share:.0%} of its bounding box but its top "
            "outline could not be read, so it is treated as a rectangle"
        )

    report: dict[str, Any] = {
        "model": {"path": str(path), "sha256": sha, "solids": len(solids)},
        "pcb_solid_index": index,
        "pcb_chosen_by": "named" if pcb_solid_index is not None else "found",
        "size_mm": [width, length, thickness],
        "mounting_holes": {"diameter_mm": mounting, "count": len(mounting_holes)},
        "other_hole_diameters_mm": {str(size): count for size, count in others.items()},
        "components": len(records),
        "cable_connector_candidates": candidates,
        "notes": notes,
    }

    return ImportedBoard(data=data, report=report)
