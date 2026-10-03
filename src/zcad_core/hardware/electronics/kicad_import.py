"""Read a board file's outline, thickness and mounting holes from a KiCad PCB.

This is the first part of ``zcad-validation board import --kicad``. From a
``.kicad_pcb`` (KiCad 6 or later) it reads:

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
  tie going to the smaller; other sizes and slots are listed with positions.

The frame is the board file's: KiCad's Y points down and the file's points up,
so Y is flipped, and the outline's bounding box is centred on the origin. A
board file also needs a cable connector and the parts' heights, which this part
does not read, so the file is written with ``needs_review`` for them (heights
may be given as one default, with where it came from).

KiCad's footprint angle is taken as counter-clockwise on screen and a
bottom-side footprint as mirrored in X before it is turned. Neither is checked
against a real board yet, so a position that depends on one is written with
``needs_review`` and listed in the report.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from zcad_core.hardware.electronics import board_outline, kicad_sexp
from zcad_core.hardware.electronics.board_file import (
    BOARD_SCHEMA_VERSION,
    HOLE_DIAMETER_RANGE_MM,
)
from zcad_core.hardware.electronics.board_outline import Point
from zcad_core.hardware.electronics.kicad_sexp import Node

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
class Placement:
    """Where a footprint sits: position, angle (degrees) and side."""

    x_mm: float = 0.0
    y_mm: float = 0.0
    angle: float = 0.0
    bottom: bool = False

    @property
    def unsure(self) -> bool:
        """Whether a point's place depends on a convention not yet checked."""

        return self.angle % 360 != 0 or self.bottom

    def apply(self, point: Point) -> Point:
        x, y = point

        if self.bottom:
            x = -x

        turn = math.radians(self.angle)
        # Counter-clockwise on screen; the file's Y points down.
        return (
            self.x_mm + x * math.cos(turn) + y * math.sin(turn),
            self.y_mm - x * math.sin(turn) + y * math.cos(turn),
        )


@dataclass(frozen=True)
class ImportedKicadBoard:
    """A board file's data from a KiCad PCB, and what the reader noted."""

    data: dict[str, Any]
    report: dict[str, Any]


def _identifier(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("_.-").upper()

    return name or "IMPORTED_BOARD"


def _atom(root: Node, token: str) -> str | None:
    found = kicad_sexp.child(root, token)

    return str(found[1]) if found is not None and len(found) > 1 else None


def _read(path: Path) -> tuple[Node, str]:
    raw = path.read_bytes()
    root = kicad_sexp.parse(raw.decode("utf-8"))

    if kicad_sexp.name(root) != "kicad_pcb":
        raise ValueError(f"{path.name} is not a KiCad PCB (no kicad_pcb form)")

    advice = "open it in KiCad 6 or later and save it, then import that"
    version = _atom(root, "version")

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

    found = []

    for xy in kicad_sexp.children(pts, "xy"):
        x, y = kicad_sexp.numbers(xy, 2)
        found.append((x, y))

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


def _placement(footprint: Node) -> Placement:
    layer = _atom(footprint, "layer") or "F.Cu"
    at = kicad_sexp.child(footprint, "at")

    if at is None:
        raise ValueError(f"footprint {_reference(footprint)} has no position")

    x, y = kicad_sexp.numbers(at, 2)
    angle = kicad_sexp.number(at[3]) if len(at) > 3 else 0.0

    return Placement(x, y, angle, layer.startswith("B."))


def _reference(footprint: Node) -> str:
    for text in kicad_sexp.children(footprint, "fp_text"):
        if len(text) > 2 and text[1] == "reference":
            return str(text[2])

    for prop in kicad_sexp.children(footprint, "property"):
        if len(prop) > 2 and prop[1] == "Reference":
            return str(prop[2])

    return str(footprint[1]) if len(footprint) > 1 else "?"


def _edge_pieces(root: Node, unverified: list[str]) -> list[Piece]:
    pieces = []

    for token in EDGE_ITEMS:
        for form in kicad_sexp.children(root, f"gr_{token}"):
            if _on_edge(form) and (piece := _piece(form, token, Placement())):
                pieces.append(piece)

    for footprint in kicad_sexp.children(root, "footprint"):
        place = _placement(footprint)
        listed = False

        for token in EDGE_ITEMS:
            for form in kicad_sexp.children(footprint, f"fp_{token}"):
                if not _on_edge(form) or not (piece := _piece(form, token, place)):
                    continue

                pieces.append(piece)

                if place.unsure and not listed:
                    unverified.append(
                        f"{_reference(footprint)}: Edge.Cuts item placed through "
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
        place = _placement(footprint)
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
                    f"{_reference(footprint)}: a drill at ({local[0]:g}, "
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
    value = _atom(general, "thickness") if general is not None else None

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


@dataclass(frozen=True)
class Frame:
    """KiCad's frame to the board file's: Y flipped, the outline's centre at
    the origin."""

    centre: Point

    def __call__(self, point: Point) -> Point:
        return (point[0] - self.centre[0], -(point[1] - self.centre[1]))


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


def _review(
    thickness: float | None, envelope: dict[str, float] | None, unverified: list[str]
) -> list[str]:
    review = []

    if thickness is None:
        review.append(
            "thickness: the file gives none; measure the board and set "
            "board.thickness_mm"
        )

    if envelope is None:
        review.append(
            "heights: the parts' heights are not in the file; give "
            "--default-height with --default-height-source, or set envelope or "
            "components"
        )

    review.append(
        "cable_connector: the KiCad import does not read parts yet; set the "
        "part the cable plugs into from the board"
    )

    if unverified:
        review.append(
            f"footprint_transforms: {len(unverified)} position(s) depend on how "
            "KiCad turns and mirrors a footprint, which is not yet checked "
            "against a real board; check them against the board"
        )

    return review


def import_kicad(
    path: Path,
    *,
    identifier: str | None = None,
    default_height_mm: float | None = None,
    default_height_source: str | None = None,
) -> ImportedKicadBoard:
    """Read a board file's outline, thickness and mounting holes from a KiCad
    PCB. The result carries ``needs_review`` for what the file cannot give."""

    envelope, height_source = _height(default_height_mm, default_height_source)
    root, sha = _read(path)
    unverified: list[str] = []
    outer, inner = _outer(_loops(_edge_pieces(root, unverified)))
    outline, kind, width, length, frame, notes = _outline(outer)
    holes, slots = _pad_holes(root, unverified)
    edge_holes, cutouts = _inner(inner, frame)
    size, positions, others = _mounting([*holes, *edge_holes], frame)
    thickness = _thickness(root)
    version, generator = _atom(root, "version"), _atom(root, "generator")
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
            "right and +Y up the page seen from above. Check the outline and "
            "holes against the board, settle needs_review, then remove it."
        ),
        "board": {
            "width_mm": width,
            "length_mm": length,
            "thickness_mm": (
                thickness if thickness is not None else DEFAULT_THICKNESS_MM
            ),
        },
        "needs_review": _review(thickness, envelope, unverified),
        "cable_connector": {
            "identifier": "CABLE_CONNECTOR",
            "edge": "negative_y",
            "width_mm": 1.0,
            "height_mm": 1.0,
            "depth_mm": 1.0,
            "center_offset_mm": 0.0,
            "bottom_offset_from_board_top_mm": 0.0,
        },
        "wall_openings": [],
    }

    if size is not None:
        data["mounting_holes"] = {
            "diameter_mm": size,
            "positions_mm": [[round(x, 3), round(y, 3)] for x, y in positions],
        }

    if envelope is not None:
        data["envelope"] = envelope

    report: dict[str, Any] = {
        "file": {
            "path": str(path),
            "sha256": sha,
            "kicad_file_version": version,
            "generator": generator,
            "generator_version": _atom(root, "generator_version"),
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
        "unverified_transforms": unverified,
        "notes": notes,
    }

    return ImportedKicadBoard(data=data, report=report)
