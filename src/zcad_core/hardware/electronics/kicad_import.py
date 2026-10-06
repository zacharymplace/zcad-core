"""Read a board file from a KiCad PCB.

This is ``zcad-validation board import --kicad``. From a ``.kicad_pcb`` (KiCad 6
or later) it reads:

- the outline: the ``Edge.Cuts`` lines, arcs, circles, rectangles, polygons and
  curves, in the board and in footprints, joined end to end into closed loops
  (ends meeting within 0.01 mm) and sampled to a 0.02 mm chord error. One outer
  loop is the board and more than one is a panel, which is refused; an open
  loop is refused with the ends and the gap. A loop inside the board that is a
  circle of mounting-hole size is a hole; any other is listed and not modelled,
  because a board file has an outline and holes but not slots or windows;
- the thickness, from ``(general (thickness T))``, which the file may not give;
- the mounting holes: round non-plated drills, and plated drills of a footprint
  named ``MountingHole*``. The commonest diameter is the mounting-hole size, a
  tie going to the smaller; other sizes and slots are listed with positions;
- the test points (see ``kicad_test_points``), written to ``test_points``;
- the parts: every footprint but a mounting hole, fiducial, test point, logo or
  board-only one, as the bounding box of its courtyard (or, with none, of its
  pads, with a warning), above the board for the front side and below it for
  the back. The file has no heights, so they come from a heights file (see
  ``kicad_heights``), then from one default with its source; a part with
  neither is left out and ``needs_review`` names it. Boxes are merged as the
  STEP import merges them, and the parts past an edge or within 1 mm of one
  are listed as cable connector candidates, of which the user names one.

The frame is the board file's: KiCad's Y points down and the file's points up,
so Y is flipped, and the outline's bounding box is centred on the origin. A
file without parts is written with an envelope of the default height, if one
is given, and ``needs_review`` for its cable connector.

KiCad's footprint angle is taken as counter-clockwise on screen and a
bottom-side footprint as mirrored in X before it is turned. Neither is checked
against a real board yet, so a position that depends on one is written with
``needs_review`` and listed in the report.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from zcad_core.hardware.electronics import board_outline, kicad_sexp
from zcad_core.hardware.electronics.board_file import (
    BOARD_SCHEMA_VERSION,
    HOLE_DIAMETER_RANGE_MM,
)
from zcad_core.hardware.electronics.board_import import (
    Box,
    component_records,
    connector_record,
    merge_boxes,
)
from zcad_core.hardware.electronics.board_outline import Point
from zcad_core.hardware.electronics.kicad_footprints import (
    Frame,
    Placement,
    atom,
    footprint_placement,
    footprint_reference,
)
from zcad_core.hardware.electronics.kicad_heights import Height, Heights, read_heights
from zcad_core.hardware.electronics.kicad_sexp import Node
from zcad_core.hardware.electronics.kicad_test_points import (
    is_test_point,
    read_test_points,
)

# KiCad 6's file version; older files (and ``module``) are refused.
MINIMUM_VERSION = 20211014
# Outline ends within this of each other are one point.
JOIN_MM = 0.01
# A curve is sampled so no chord strays further than this from it.
CHORD_MM = 0.02
# Points of an outline within this of the loop they lie on are dropped.
SIMPLIFY_MM = 0.02
# A rounded rectangle is taken for the outline if it fits to within this.
ROUNDED_FIT_MM = 0.03
# A hole narrower than this is a via or a tooling pin, not a mounting hole.
MINIMUM_MOUNTING_MM = 1.6
# A mounting hole's walls: a hole's diameters within this count as one size.
SIZE_GROUP_MM = 0.1
DEFAULT_THICKNESS_MM = 1.6
EDGE_LAYER = "Edge.Cuts"
# How a height from --default-height is marked, against a heights file's key.
DEFAULT_HEIGHT = "--default-height"


@dataclass(frozen=True)
class Piece:
    """One ``Edge.Cuts`` item as a polyline in KiCad's frame."""

    points: tuple[Point, ...]
    kind: str
    radius: float | None = None
    centre: Point | None = None


@dataclass(frozen=True)
class Loop:
    """A closed loop of pieces: its points, with the first not repeated."""

    points: tuple[Point, ...]
    pieces: tuple[Piece, ...]

    @property
    def circle(self) -> Piece | None:
        return (
            self.pieces[0]
            if len(self.pieces) == 1 and self.pieces[0].kind == "circle"
            else None
        )


@dataclass(frozen=True)
class Hole:
    """A drill in KiCad's frame."""

    x_mm: float
    y_mm: float
    diameter_mm: float


@dataclass(frozen=True)
class ImportedKicadBoard:
    """A board file's data from a KiCad PCB, and what the reader noted."""

    data: dict[str, Any]
    report: dict[str, Any]


def _identifier(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("_.-").upper()

    return name or "IMPORTED_BOARD"


def _read(path: Path) -> tuple[Node, str]:
    raw = path.read_bytes()
    root = kicad_sexp.parse(raw.decode("utf-8"))

    if kicad_sexp.name(root) != "kicad_pcb":
        raise ValueError(f"{path.name} is not a KiCad PCB (no kicad_pcb form)")

    advice = "open it in KiCad 6 or later and save it, then import that"
    version = atom(root, "version")

    if kicad_sexp.child(root, "module") is not None:
        raise ValueError(f"{path.name} uses KiCad 5's module form: {advice}")

    if version is None or not version.isdigit() or int(version) < MINIMUM_VERSION:
        raise ValueError(
            f"{path.name} is file version {version}, older than KiCad 6's "
            f"{MINIMUM_VERSION}: {advice}"
        )

    return root, hashlib.sha256(raw).hexdigest()


def _points(form: Node) -> list[Point]:
    pts = kicad_sexp.child(form, "pts")

    if pts is None:
        raise ValueError(f"({kicad_sexp.name(form)}) has no pts")

    found: list[Point] = []

    # KiCad 7 and later may write an arc among a polygon's points; it is sampled
    # in order, and anything else is refused rather than dropped, since a point
    # left out cuts across the outline.
    for item in pts[1:]:
        token = kicad_sexp.name(item) if isinstance(item, list) else ""

        if token == "xy":
            x, y = kicad_sexp.numbers(item, 2)
            found.append((x, y))
        elif token == "arc":
            arc = _arc(_pair(item, "start"), _pair(item, "mid"), _pair(item, "end"))
            points = list(arc.points)

            if found and math.dist(found[-1], points[0]) < 1e-9:
                points = points[1:]

            found.extend(points)
        else:
            raise ValueError(
                f"({kicad_sexp.name(form)}) has a ({token or item}) among its "
                "points, which the importer does not read"
            )

    return found


def _pair(form: Node, token: str) -> Point:
    found = kicad_sexp.child(form, token)

    if found is None:
        raise ValueError(f"({kicad_sexp.name(form)}) has no {token}")

    x, y = kicad_sexp.numbers(found, 2)

    return (x, y)


def _arc(start: Point, mid: Point, end: Point) -> Piece:
    """An arc through three points, sampled to the chord error."""

    ax, ay = start
    bx, by = mid
    cx, cy = end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))

    if abs(d) < 1e-9:
        return Piece((start, end), "line")

    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    radius = math.hypot(ax - ux, ay - uy)
    first = math.atan2(ay - uy, ax - ux)
    middle = (math.atan2(by - uy, bx - ux) - first) % (2 * math.pi)
    last = (math.atan2(cy - uy, cx - ux) - first) % (2 * math.pi)
    sweep = last if middle <= last else last - 2 * math.pi
    step = 2 * math.acos(max(-1.0, 1 - CHORD_MM / radius))
    count = max(2, math.ceil(abs(sweep) / step))
    points = [
        (
            ux + radius * math.cos(first + sweep * i / count),
            uy + radius * math.sin(first + sweep * i / count),
        )
        for i in range(1, count)
    ]

    return Piece((start, *points, end), "arc", radius)


def _circle(centre: Point, edge: Point) -> Piece:
    radius = math.dist(centre, edge)
    step = 2 * math.acos(max(-1.0, 1 - CHORD_MM / radius)) if radius > CHORD_MM else 1
    count = max(8, math.ceil(2 * math.pi / step))
    points = [
        (
            centre[0] + radius * math.cos(2 * math.pi * i / count),
            centre[1] + radius * math.sin(2 * math.pi * i / count),
        )
        for i in range(count)
    ]

    return Piece((*points, points[0]), "circle", radius, centre)


def _bezier(control: Sequence[Point], depth: int = 0) -> list[Point]:
    """A cubic Bezier flattened by subdivision; the start point is included."""

    p0, p1, p2, p3 = control
    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    length = math.hypot(dx, dy)

    def off(p: Point) -> float:
        px, py = p[0] - p0[0], p[1] - p0[1]

        return math.hypot(px, py) if length == 0 else abs(px * dy - py * dx) / length

    if max(off(p1), off(p2)) <= CHORD_MM or depth >= 16:
        return [p0]

    def mid(a: Point, b: Point) -> Point:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    p01, p12, p23 = mid(p0, p1), mid(p1, p2), mid(p2, p3)
    p012, p123 = mid(p01, p12), mid(p12, p23)
    middle = mid(p012, p123)

    return _bezier((p0, p01, p012, middle), depth + 1) + _bezier(
        (middle, p123, p23, p3), depth + 1
    )


def _piece(form: Node, token: str, place: Placement) -> Piece | None:
    """An ``Edge.Cuts`` item (``token`` without its gr_/fp_ prefix), placed."""

    if token == "line":
        local = [_pair(form, "start"), _pair(form, "end")]
    elif token == "arc":
        local = [_pair(form, "start"), _pair(form, "mid"), _pair(form, "end")]
    elif token == "circle":
        local = [_pair(form, "center"), _pair(form, "end")]
    elif token == "rect":
        (x0, y0), (x1, y1) = _pair(form, "start"), _pair(form, "end")
        local = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    elif token == "poly":
        local = _points(form)
    elif token == "curve":
        local = _points(form)

        if len(local) != 4:
            raise ValueError("(curve) needs four points")
    else:
        return None

    where = [place.apply(point) for point in local]

    if token == "line":
        return Piece((where[0], where[1]), "line")

    if token == "arc":
        return _arc(where[0], where[1], where[2])

    if token == "circle":
        return _circle(where[0], where[1])

    if token == "curve":
        return Piece((*_bezier(where), where[3]), "curve")

    return Piece((*where, where[0]), token)


EDGE_ITEMS = ("line", "arc", "circle", "rect", "poly", "curve")


def _on_edge(form: Node) -> bool:
    layer = kicad_sexp.child(form, "layer")

    return layer is not None and len(layer) > 1 and layer[1] == EDGE_LAYER


def _edge_pieces(root: Node, unverified: list[str]) -> list[Piece]:
    pieces = []

    for token in EDGE_ITEMS:
        for form in kicad_sexp.children(root, f"gr_{token}"):
            if _on_edge(form) and (piece := _piece(form, token, Placement())):
                pieces.append(piece)

    for footprint in kicad_sexp.children(root, "footprint"):
        place = footprint_placement(footprint)
        listed = False

        for token in EDGE_ITEMS:
            for form in kicad_sexp.children(footprint, f"fp_{token}"):
                if not _on_edge(form) or not (piece := _piece(form, token, place)):
                    continue

                pieces.append(piece)

                if place.unsure and not listed:
                    unverified.append(
                        f"{footprint_reference(footprint)}: Edge.Cuts item placed through "
                        f"angle {place.angle:g}"
                        + (" on the bottom side" if place.bottom else "")
                    )
                    listed = True

    return pieces


def _same(a: Point, b: Point) -> bool:
    return math.dist(a, b) <= JOIN_MM


def _chain(start: Piece, remaining: list[Piece]) -> list[Piece]:
    """Pieces joined end to end from ``start`` until the chain closes or
    nothing meets its ends."""

    chain = [start]

    while not _same(chain[0].points[0], chain[-1].points[-1]):
        head, tail = chain[0].points[0], chain[-1].points[-1]

        for index, piece in enumerate(remaining):
            backwards = replace(piece, points=piece.points[::-1])

            if _same(piece.points[0], tail):
                chain.append(piece)
            elif _same(piece.points[-1], tail):
                chain.append(backwards)
            elif _same(piece.points[-1], head):
                chain.insert(0, piece)
            elif _same(piece.points[0], head):
                chain.insert(0, backwards)
            else:
                continue

            del remaining[index]
            break
        else:
            break

    return chain


def _loops(pieces: Sequence[Piece]) -> list[Loop]:
    """Join pieces into closed loops, or refuse with the nearest open ends."""

    remaining = list(pieces)
    loops: list[Loop] = []
    open_ends: list[Point] = []

    while remaining:
        chain = _chain(remaining.pop(0), remaining)
        points: list[Point] = []

        for piece in chain:
            points.extend(piece.points[1:] if points else piece.points)

        if _same(points[0], points[-1]):
            loops.append(Loop(tuple(points[:-1]), tuple(chain)))
        else:
            open_ends.extend((points[0], points[-1]))

    if open_ends:
        gap, first, second = min(
            (math.dist(a, b), a, b)
            for i, a in enumerate(open_ends)
            for b in open_ends[i + 1 :]
        )

        raise ValueError(
            f"{EDGE_LAYER} is not a closed outline: the ends at "
            f"({first[0]:.3f}, {first[1]:.3f}) and ({second[0]:.3f}, "
            f"{second[1]:.3f}) in KiCad's coordinates are {gap:.3f} mm apart"
        )

    return loops


def _outer(loops: Sequence[Loop]) -> tuple[Loop, list[Loop]]:
    """The board's loop and the loops inside it."""

    if not loops:
        raise ValueError(f"The file has nothing on {EDGE_LAYER}: no board outline")

    outers = [
        loop
        for loop in loops
        if not any(
            other is not loop and board_outline.contains(other.points, loop.points[0])
            for other in loops
        )
    ]

    if len(outers) > 1:
        raise ValueError(
            f"{EDGE_LAYER} has {len(outers)} separate outlines: a panel of "
            "boards. Import one board; delete or move the others"
        )

    return outers[0], [loop for loop in loops if loop is not outers[0]]


def _plain(polygon: Sequence[Point], width: float, length: float) -> bool:
    return (
        len(polygon) == 4
        and abs(board_outline.signed_area(polygon)) >= 0.999 * width * length
    )


def _rounded(
    loop: Loop, polygon: Sequence[Point], width: float, length: float
) -> float | None:
    """The radius if the loop is a rectangle with four equal round corners."""

    radii = [piece.radius or 0.0 for piece in loop.pieces if piece.kind == "arc"]

    if len(radii) != 4 or max(radii) - min(radii) > JOIN_MM:
        return None

    radius = radii[0]

    if not 0.1 <= radius <= min(width, length) / 2:
        return None

    corners = board_outline.rounded_rectangle_points(width, length, radius)
    fits = all(
        board_outline.distance_to_boundary(corners, p) <= ROUNDED_FIT_MM
        for p in polygon
    ) and all(
        board_outline.distance_to_boundary(polygon, p) <= ROUNDED_FIT_MM
        for p in corners
    )

    return round(radius, 3) if fits else None


def _hole_size(form: Node) -> float | str | None:
    """A drill's diameter, ``"slot"`` for an oval one, or ``None`` for none."""

    drill = kicad_sexp.child(form, "drill")

    if drill is None or len(drill) < 2:
        return None

    if drill[1] == "oval":
        return "slot"

    return kicad_sexp.number(drill[1])


def _pad_holes(
    root: Node, unverified: list[str]
) -> tuple[list[Hole], list[tuple[float, float, float | None]]]:
    """Round mounting-hole drills of footprints, and the slots found."""

    holes: list[Hole] = []
    slots: list[tuple[float, float, float | None]] = []

    for footprint in kicad_sexp.children(root, "footprint"):
        place = footprint_placement(footprint)
        library_name = str(footprint[1]).split(":")[-1] if len(footprint) > 1 else ""

        for pad in kicad_sexp.children(footprint, "pad"):
            kind = pad[2] if len(pad) > 2 else ""
            size = _hole_size(pad)
            mounting = kind == "np_thru_hole" or (
                kind == "thru_hole" and library_name.startswith("MountingHole")
            )

            if size is None or not mounting:
                continue

            at = kicad_sexp.child(pad, "at")
            local = kicad_sexp.numbers(at, 2) if at is not None else (0.0, 0.0)
            x, y = place.apply((local[0], local[1]))

            if place.unsure and max(abs(local[0]), abs(local[1])) > 1e-9:
                unverified.append(
                    f"{footprint_reference(footprint)}: a drill at ({local[0]:g}, "
                    f"{local[1]:g}) in a footprint at angle {place.angle:g}"
                    + (" on the bottom side" if place.bottom else "")
                )

            if size == "slot":
                slots.append((x, y, None))
            elif isinstance(size, float):
                holes.append(Hole(x, y, size))

    return holes, slots


def _groups(holes: Sequence[Hole]) -> dict[float, list[Hole]]:
    """Holes grouped by diameter, those within 0.1 mm counting as one size;
    each group is keyed by its smallest diameter."""

    groups: dict[float, list[Hole]] = {}
    size: float | None = None
    last = 0.0

    for hole in sorted(holes, key=lambda hole: hole.diameter_mm):
        if size is None or hole.diameter_mm - last > SIZE_GROUP_MM:
            size = round(hole.diameter_mm, 2)
            groups[size] = []

        groups[size].append(hole)
        last = hole.diameter_mm

    return groups


def _thickness(root: Node) -> float | None:
    general = kicad_sexp.child(root, "general")
    value = atom(general, "thickness") if general is not None else None

    return kicad_sexp.number(value) if value is not None else None


def _height(
    default_height_mm: float | None, source: str | None
) -> tuple[dict[str, float] | None, str | None]:
    if default_height_mm is None and source is None:
        return None, None

    if default_height_mm is None or not source or not source.strip():
        raise ValueError(
            "--default-height and --default-height-source go together: a height "
            "with no source is a guess"
        )

    return {"top_mm": default_height_mm}, source.strip()


def _outline(
    outer: Loop,
) -> tuple[Any, str, float, float, Frame, list[str]]:
    """The outline as the board file writes it, the kind, the size and the
    frame."""

    simple = board_outline.simplified(outer.points, SIMPLIFY_MM)
    x0, x1, y0, y1 = board_outline.bounding_box(simple)
    width, length = round(x1 - x0, 3), round(y1 - y0, 3)
    frame = Frame(((x0 + x1) / 2, (y0 + y1) / 2))
    polygon = board_outline.counter_clockwise([frame(p) for p in simple])
    radius = _rounded(outer, polygon, width, length)

    if _plain(polygon, width, length):
        return "rectangle", "rectangle", width, length, frame, []

    if radius is not None:
        outline = {"type": "rounded_rectangle", "radius_mm": radius}

        return outline, "rounded_rectangle", width, length, frame, []

    if len(polygon) > board_outline.MAXIMUM_POINTS:
        raise ValueError(
            f"The outline needs {len(polygon)} points; a board file takes at "
            f"most {board_outline.MAXIMUM_POINTS}"
        )

    outline = {
        "type": "polygon",
        "points_mm": [[round(x, 3), round(y, 3)] for x, y in polygon],
    }
    note = f"The outline is written as a polygon of {len(polygon)} points"

    return outline, "polygon", width, length, frame, [note]


def _inner(inner: Sequence[Loop], frame: Frame) -> tuple[list[Hole], list[Any]]:
    """Round cut-outs of mounting-hole size as holes; the rest as cut-outs the
    board file cannot say."""

    holes: list[Hole] = []
    cutouts: list[Any] = []

    for loop in inner:
        circle = loop.circle
        bx0, bx1, by0, by1 = board_outline.bounding_box(loop.points)
        middle = ((bx0 + bx1) / 2, (by0 + by1) / 2)

        if circle is not None and circle.radius and circle.centre:
            low, high = HOLE_DIAMETER_RANGE_MM

            if low <= 2 * circle.radius <= high:
                holes.append(Hole(*circle.centre, 2 * circle.radius))
                continue

        x, y = frame(middle)
        cutouts.append(
            {
                "kind": "circle" if circle is not None else "cutout",
                "centre_mm": [round(x, 3), round(y, 3)],
                "size_mm": [round(bx1 - bx0, 3), round(by1 - by0, 3)],
            }
        )

    return holes, cutouts


def _mounting(
    holes: Sequence[Hole], frame: Frame
) -> tuple[float | None, list[Point], list[dict[str, Any]]]:
    """The mounting-hole size, its positions, and the other sizes listed."""

    low, high = (
        max(MINIMUM_MOUNTING_MM, HOLE_DIAMETER_RANGE_MM[0]),
        HOLE_DIAMETER_RANGE_MM[1],
    )
    groups = _groups([h for h in holes if low <= h.diameter_mm <= high])
    size = max(groups, key=lambda s: (len(groups[s]), -s)) if groups else None
    positions = [frame((h.x_mm, h.y_mm)) for h in (groups[size] if size else [])]
    others = [
        {
            "diameter_mm": found,
            "positions_mm": [
                [round(v, 3) for v in frame((h.x_mm, h.y_mm))] for h in group
            ],
        }
        for found, group in _groups(holes).items()
        if found != size
    ]

    return size, positions, others


COURTYARD_LAYERS = ("F.CrtYd", "B.CrtYd")
COURTYARD_ITEMS = ("line", "arc", "circle", "rect", "poly")
# A part past an edge, or within this of one, is a cable connector candidate.
AT_EDGE_MM = 1.0
# Footprints of these library names are not parts, with what each is.
NOT_PARTS = (
    ("MountingHole", "a mounting hole"),
    ("Fiducial", "a fiducial"),
)


@dataclass(frozen=True)
class Part:
    """A footprint read as a part: its plan (x0, x1, y0, y1) in the board
    file's frame, its side, and what the plan was taken from."""

    reference: str
    library: str
    bottom: bool
    plan: tuple[float, float, float, float]
    plan_from: str


def _not_a_part(
    footprint: Node, reference: str, library: str, test_points: Sequence[str]
) -> str | None:
    """Why a footprint is not a part, or ``None`` if it is one."""

    nickname, _, name = library.rpartition(":")

    for prefix, what in NOT_PARTS:
        if name.startswith(prefix):
            return what

    if is_test_point(reference, library, test_points):
        return "a test point"

    if nickname == "Symbol" or "logo" in name.lower():
        return "a logo"

    attributes = kicad_sexp.child(footprint, "attr")

    if attributes is not None and "board_only" in attributes[1:]:
        return "board only: not placed as a part"

    return None


def _courtyard(footprint: Node, place: Placement) -> list[Point]:
    points: list[Point] = []

    for token in COURTYARD_ITEMS:
        for form in kicad_sexp.children(footprint, f"fp_{token}"):
            layer = kicad_sexp.child(form, "layer")

            if layer is None or len(layer) < 2 or layer[1] not in COURTYARD_LAYERS:
                continue

            if piece := _piece(form, token, place):
                points.extend(piece.points)

    return points


def _pad_extent(footprint: Node, place: Placement) -> list[Point]:
    """Each pad as the square round its circumscribing circle, so the extent
    does not depend on which way the pad is turned."""

    points: list[Point] = []

    for pad in kicad_sexp.children(footprint, "pad"):
        at, size = kicad_sexp.child(pad, "at"), kicad_sexp.child(pad, "size")

        if at is None or size is None:
            continue

        local_x, local_y = kicad_sexp.numbers(at, 2)
        x, y = place.apply((local_x, local_y))
        reach = math.hypot(*kicad_sexp.numbers(size, 2)) / 2
        points.extend(((x - reach, y - reach), (x + reach, y + reach)))

    return points


def _parts(
    root: Node, frame: Frame, unverified: list[str], test_points: Sequence[str]
) -> tuple[list[Part], list[dict[str, str]]]:
    """The footprints that are parts, and those that are not, with why."""

    parts: list[Part] = []
    excluded: list[dict[str, str]] = []

    for footprint in kicad_sexp.children(root, "footprint"):
        reference = footprint_reference(footprint)
        library = str(footprint[1]) if len(footprint) > 1 else ""
        why = _not_a_part(footprint, reference, library, test_points)

        if why is not None:
            excluded.append({"reference": reference, "why": why})
            continue

        place = footprint_placement(footprint)
        points, plan_from = _courtyard(footprint, place), "courtyard"

        if not points:
            points, plan_from = _pad_extent(footprint, place), "pads"

        if not points:
            excluded.append({"reference": reference, "why": "no courtyard and no pads"})
            continue

        if place.unsure:
            unverified.append(
                f"{reference}: its {plan_from} placed through angle {place.angle:g}"
                + (" on the bottom side" if place.bottom else "")
            )

        plan = board_outline.bounding_box([frame(p) for p in points])
        parts.append(Part(reference, library, place.bottom, plan, plan_from))

    return parts, excluded


def _box(part: Part, height_mm: float, thickness_mm: float) -> Box:
    """A part's box, above the board's top face or below its bottom face."""

    x0, x1, y0, y1 = part.plan

    if part.bottom:
        return (x0, x1, y0, y1, -(thickness_mm + height_mm), -thickness_mm)

    return (x0, x1, y0, y1, 0.0, height_mm)


def _edge_reach(part: Part, width: float, length: float) -> tuple[str, float]:
    """The edge a part comes closest to, and how far past it the part
    reaches: negative when it stops short."""

    x0, x1, y0, y1 = part.plan
    reach = {
        "negative_x": -width / 2 - x0,
        "positive_x": x1 - width / 2,
        "negative_y": -length / 2 - y0,
        "positive_y": y1 - length / 2,
    }

    return max(reach.items(), key=lambda item: item[1])


def _candidates(
    parts: Sequence[Part],
    heights: Mapping[int, Height],
    width: float,
    length: float,
) -> list[dict[str, Any]]:
    """The parts past an edge or within 1 mm of one, largest plan first."""

    found: list[tuple[float, dict[str, Any]]] = []

    for index, part in enumerate(parts):
        edge, reach = _edge_reach(part, width, length)

        if reach <= -AT_EDGE_MM:
            continue

        x0, x1, y0, y1 = part.plan
        height = heights.get(index)
        found.append(
            (
                (x1 - x0) * (y1 - y0),
                {
                    "identifier": part.reference,
                    "edge": edge,
                    "past_edge_mm": round(reach, 3),
                    "side": "bottom" if part.bottom else "top",
                    "size_mm": [
                        round(x1 - x0, 3),
                        round(y1 - y0, 3),
                        None if height is None else height.mm,
                    ],
                },
            )
        )

    found.sort(key=lambda item: (-item[0], item[1]["identifier"]))

    return [candidate for _, candidate in found]


def _natural(reference: str) -> tuple[tuple[int, str], ...]:
    """A reference's sort key, so R2 comes before R10."""

    return tuple(
        (int(piece), "") if piece.isdigit() else (-1, piece)
        for piece in re.split(r"(\d+)", reference)
    )


def _box_name(references: Sequence[str], used: set[str]) -> str:
    ordered = sorted(references, key=_natural)
    name = (
        "_".join(ordered)
        if len(ordered) <= 3
        else f"{ordered[0]}_and_{len(ordered) - 1}_more"
    )
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_.-") or "PART"
    unique, count = name, 1

    while unique in used:
        count += 1
        unique = f"{name}-{count}"

    used.add(unique)

    return unique


def _volume(box: Box) -> float:
    return (box[1] - box[0]) * (box[3] - box[2]) * (box[5] - box[4])


def _within(inner: Box, outer: Box) -> bool:
    return all(outer[i] - 1e-9 <= inner[i] for i in (0, 2, 4)) and all(
        inner[i] <= outer[i] + 1e-9 for i in (1, 3, 5)
    )


def _merged_records(
    boxes: Sequence[tuple[str, Box]],
    mounting: tuple[float | None, Sequence[Point]],
    width: float,
    length: float,
) -> list[dict[str, Any]]:
    """Boxes merged as the STEP import merges them, each named by its parts:
    a part belongs to the smallest merged box that holds it."""

    hole_size, holes = mounting
    records: list[dict[str, Any]] = []
    used: set[str] = set()

    for above in (True, False):
        side = [(name, box) for name, box in boxes if (box[4] >= 0) == above]
        merged = merge_boxes(
            [box for _, box in side], above, holes, hole_diameter_mm=hole_size or 0.0
        )
        members: dict[int, list[str]] = {index: [] for index in range(len(merged))}

        for name, part in side:
            holders = [i for i, box in enumerate(merged) if _within(part, box)]
            members[min(holders, key=lambda i: _volume(merged[i]))].append(name)

        for index, box in enumerate(merged):
            record = component_records([box], width, length)[0]
            record["identifier"] = _box_name(members[index], used)
            records.append(record)

    return records


@dataclass(frozen=True)
class PartsRead:
    """What the parts give the board file and the report."""

    components: list[dict[str, Any]]
    connector: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    review: list[str]
    source: str
    report: dict[str, Any]
    notes: list[str]


def _heights_of(
    parts: Sequence[Part], heights: Heights | None, default: Height | None
) -> tuple[dict[int, Height], set[str]]:
    """Each part's height by its index, and the heights file's keys used."""

    found: dict[int, Height] = {}
    used: set[str] = set()

    for index, part in enumerate(parts):
        height = heights.find(part.reference, part.library) if heights else None

        if height is not None:
            used.add(height.given_by)
        else:
            height = default

        if height is not None:
            found[index] = height

    return found, used


def _named_connector(
    name: str,
    parts: Sequence[Part],
    heights: Mapping[int, Height],
    candidates: Sequence[dict[str, Any]],
    size: tuple[float, float, float],
) -> tuple[int, dict[str, Any]]:
    """The named part as the cable connector, and its index among the parts."""

    width, length, thickness = size
    named = [candidate["identifier"] for candidate in candidates]
    index = next(
        (i for i, part in enumerate(parts) if part.reference == name and name in named),
        None,
    )

    if index is None:
        raise ValueError(
            f"{name} is not one of the parts at an edge: {', '.join(named) or 'none'}"
        )

    if index not in heights:
        raise ValueError(
            f"{name} has no height: give it in --heights, or give --default-height"
        )

    box = _box(parts[index], heights[index].mm, thickness)
    edge, _ = _edge_reach(parts[index], width, length)

    return index, connector_record(box, edge, width, length, name)


def _heights_source(
    heights: Mapping[int, Height], count: int, file: Heights | None
) -> str:
    """What the board file's ``source`` says of the parts' heights."""

    default = [h for h in heights.values() if h.given_by == DEFAULT_HEIGHT]
    said = []

    if file is not None:
        said.append(
            f"{len(heights) - len(default)} from {file.name} (SHA-256 {file.sha256})"
        )

    if default:
        said.append(
            f"{len(default)} one default of {default[0].mm:g} mm, source: "
            f"{default[0].source}"
        )

    if count > len(heights):
        said.append(f"{count - len(heights)} none")

    return f"; part heights: {', '.join(said)}"


def _parts_report(
    parts: Sequence[Part],
    heights: Mapping[int, Height],
    excluded: list[dict[str, str]],
    boxes: int,
    unused: list[str],
) -> dict[str, Any]:
    return {
        "read": len(parts),
        "boxes": boxes,
        "plans_from_pads": [p.reference for p in parts if p.plan_from == "pads"],
        "excluded": excluded,
        "heights": [
            {
                "reference": part.reference,
                "height_mm": heights[i].mm,
                "source": heights[i].source,
                "given_by": heights[i].given_by,
            }
            for i, part in enumerate(parts)
            if i in heights
        ],
        "without_height": [
            p.reference for i, p in enumerate(parts) if i not in heights
        ],
        "heights_file_unused": unused,
    }


def read_parts(
    root: Node,
    frame: Frame,
    size: tuple[float, float, float],
    mounting: tuple[float | None, Sequence[Point]],
    *,
    heights_file: Heights | None,
    default: Height | None,
    cable_connector: str | None,
    test_points: Sequence[str],
    unverified: list[str],
) -> PartsRead | None:
    """The footprints as the board file's components and cable connector, or
    ``None`` when no footprint is a part."""

    width, length, thickness = size
    parts, excluded = _parts(root, frame, unverified, test_points)

    if not parts:
        if cable_connector is not None:
            raise ValueError(f"The file has no parts, so none is {cable_connector}")

        return None

    heights, used = _heights_of(parts, heights_file, default)
    candidates = _candidates(parts, heights, width, length)
    connector, review, skip = None, [], -1

    if cable_connector is not None:
        skip, connector = _named_connector(
            cable_connector, parts, heights, candidates, size
        )
    else:
        review.append(
            "cable_connector: name the part the cable plugs into with "
            "--cable-connector, from the report's candidates"
        )

    missing = [p.reference for i, p in enumerate(parts) if i not in heights]

    if missing:
        review.append(
            f"heights: {len(missing)} part(s) have no height ({', '.join(missing)}): "
            "give them in --heights, or --default-height with "
            "--default-height-source; they are left out of components until then"
        )

    boxes = [
        (part.reference, _box(part, heights[i].mm, thickness))
        for i, part in enumerate(parts)
        if i in heights and i != skip
    ]
    components = _merged_records(boxes, mounting, width, length)
    notes = [
        f"{part.reference} has no courtyard: its box is its pads' extent, smaller "
        "than a part's courtyard would be"
        for part in parts
        if part.plan_from == "pads"
    ]
    notes.append(
        "The parts' boxes are conservative: a courtyard is bigger than its part, "
        "a box covers a part's whole plan at its full height, and a merged box "
        "takes its tallest part's height"
    )
    unused = heights_file.unused(used) if heights_file else []

    return PartsRead(
        components=components,
        connector=connector,
        candidates=candidates,
        review=review,
        source=_heights_source(heights, len(parts), heights_file),
        report=_parts_report(parts, heights, excluded, len(components), unused),
        notes=notes,
    )


def _review(
    thickness: float | None,
    envelope: dict[str, float] | None,
    parts: PartsRead | None,
    unverified: list[str],
) -> list[str]:
    review = []

    if thickness is None:
        review.append(
            "thickness: the file gives none; measure the board and set "
            "board.thickness_mm"
        )

    if parts is not None:
        review.extend(parts.review)
    else:
        if envelope is None:
            review.append(
                "heights: the file has no parts and no heights; give "
                "--default-height with --default-height-source, or set envelope "
                "or components"
            )

        review.append(
            "cable_connector: the file has no parts to name; set the part the "
            "cable plugs into from the board"
        )

    if unverified:
        review.append(
            f"footprint_transforms: {len(unverified)} position(s) depend on how "
            "KiCad turns and mirrors a footprint, which is not yet checked "
            "against a real board; check them against the board"
        )

    return review


def _cable_connector(parts: PartsRead | None) -> dict[str, Any]:
    """The named connector, or a placeholder at the likeliest edge that
    ``needs_review`` holds back until one is named."""

    if parts is not None and parts.connector is not None:
        return parts.connector

    candidates = parts.candidates if parts is not None else []

    return {
        "identifier": "CABLE_CONNECTOR",
        "edge": candidates[0]["edge"] if candidates else "negative_y",
        "width_mm": 1.0,
        "height_mm": 1.0,
        "depth_mm": 1.0,
        "center_offset_mm": 0.0,
        "bottom_offset_from_board_top_mm": 0.0,
    }


def import_kicad(
    path: Path,
    *,
    identifier: str | None = None,
    default_height_mm: float | None = None,
    default_height_source: str | None = None,
    heights_file: Path | None = None,
    cable_connector: str | None = None,
    test_points: Sequence[str] = (),
) -> ImportedKicadBoard:
    """Read a board file from a KiCad PCB: its outline, thickness, mounting
    holes, its footprints as parts, and its test points. The result carries
    ``needs_review`` for what the file cannot give."""

    envelope, height_source = _height(default_height_mm, default_height_source)
    default = (
        Height(envelope["top_mm"], height_source, DEFAULT_HEIGHT)
        if envelope is not None and height_source is not None
        else None
    )
    heights_given = read_heights(heights_file) if heights_file is not None else None
    root, sha = _read(path)
    unverified: list[str] = []
    outer, inner = _outer(_loops(_edge_pieces(root, unverified)))
    outline, kind, width, length, frame, notes = _outline(outer)
    holes, slots = _pad_holes(root, unverified)
    edge_holes, cutouts = _inner(inner, frame)
    size, positions, others = _mounting([*holes, *edge_holes], frame)
    thickness = _thickness(root)
    version, generator = atom(root, "version"), atom(root, "generator")
    parts = read_parts(
        root,
        frame,
        (width, length, thickness if thickness is not None else DEFAULT_THICKNESS_MM),
        (size, positions),
        heights_file=heights_given,
        default=default,
        cable_connector=cable_connector,
        test_points=test_points,
        unverified=unverified,
    )
    probed = read_test_points(root, frame, test_points, unverified)
    notes.extend(probed.notes)

    if parts is not None:
        envelope = None
        heights = parts.source
        notes.extend(parts.notes)
    elif heights_given is not None:
        raise ValueError(
            f"The file has no parts, so {heights_given.name} has nothing to size"
        )
    else:
        heights = (
            f"; part heights: one default of {default_height_mm:g} mm, source: "
            f"{height_source}"
            if envelope is not None
            else ""
        )
    data: dict[str, Any] = {
        "schema_version": BOARD_SCHEMA_VERSION,
        "identifier": identifier or _identifier(path),
        "name": f"Imported from {path.name}",
        "units": "mm",
        "outline": outline,
        "source": (
            f"KiCad file {path.name}, SHA-256 {sha}, KiCad file version {version}, "
            f"generator {generator}, read by board import; not checked against "
            f"the real board{heights}"
        ),
        "notes": (
            "Read from the KiCad file's Edge.Cuts with Y flipped (KiCad's Y points "
            "down) and the outline's bounding box centred on the origin, so +X is "
            "right and +Y up the page seen from above. Parts are boxes from their "
            "footprints' courtyards. Check the outline, holes and parts against "
            "the board, settle needs_review, then remove it."
        ),
        "board": {
            "width_mm": width,
            "length_mm": length,
            "thickness_mm": (
                thickness if thickness is not None else DEFAULT_THICKNESS_MM
            ),
        },
        "needs_review": _review(thickness, envelope, parts, unverified),
        "cable_connector": _cable_connector(parts),
        "wall_openings": [],
    }

    if size is not None:
        data["mounting_holes"] = {
            "diameter_mm": size,
            "positions_mm": [[round(x, 3), round(y, 3)] for x, y in positions],
        }

    if envelope is not None:
        data["envelope"] = envelope

    if parts is not None:
        data["components"] = parts.components

    if probed.points:
        data["test_points"] = probed.points

    if not data["needs_review"]:
        del data["needs_review"]

    report: dict[str, Any] = {
        "file": {
            "path": str(path),
            "sha256": sha,
            "kicad_file_version": version,
            "generator": generator,
            "generator_version": atom(root, "generator_version"),
        },
        "outline": {"kind": kind, "size_mm": [width, length]},
        "thickness": {
            "mm": data["board"]["thickness_mm"],
            "from": "file" if thickness is not None else "placeholder: not in file",
        },
        "mounting_holes": {"diameter_mm": size, "count": len(positions)},
        "other_holes": others,
        "slots_not_modelled": [
            [round(v, 3) for v in frame((x, y))] for x, y, _ in slots
        ],
        "cutouts_not_modelled": cutouts,
        "parts": parts.report if parts is not None else None,
        "cable_connector_candidates": parts.candidates if parts is not None else [],
        "test_points": {
            "top": sum(1 for point in probed.points if point["side"] == "top"),
            "bottom": sum(1 for point in probed.points if point["side"] == "bottom"),
            "not_read": probed.not_read,
        },
        "unverified_transforms": unverified,
        "notes": notes,
    }

    return ImportedKicadBoard(data=data, report=report)
