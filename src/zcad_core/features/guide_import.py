"""Write a guide file from the round through-holes of a master part.

A **master** is a part that has the holes you want: a mating plate, a cover, a
gasket. The **target** is the part the guide is built around and drilled; it
may be the master itself, to re-drill or enlarge its own holes. Each hole of
the master becomes a bore at the same place, so a pattern is copied from one
part to another without measuring it.

Both parts are in the guide's frame: centred on their own bounding box in X and
Y, with the top at ``z == 0``, so a pattern copies across when the two parts
share a centre. When they do not, ``offset`` moves every hole.

The drill's chuck and depth cannot be guessed, so the file is written with
``needs_review`` naming them, and the loader refuses it until they are set.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.guide_file import (
    DEFAULT_PLATE_MM,
    DEFAULT_WALL_MM,
    GUIDE_SCHEMA_VERSION,
    MINIMUM_TOP_SHARE,
    load_part_file,
)
from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_import import (
    MINIMUM_HOLE_MM,
    load_solids,
    through_holes,
)

# A guess at the nest's depth: the part's top this far down.
DEFAULT_NEST_DEPTH_MM = 8.0
# The drill's depth is taken to stop this far short of the target's underside.
DEPTH_MARGIN_MM = 2.0
# Holes within this of one another count as one size.
SIZE_TOLERANCE_MM = 0.1
# A chuck is taken to be this many bit diameters across, until the user says.
CHUCK_FACTOR = 3.0
MINIMUM_CHUCK_MM = 10.0


@dataclass(frozen=True)
class ImportedGuide:
    """A guide file's data from a master's holes, and what the reader noted."""

    data: dict[str, Any]
    report: dict[str, Any]


def _master_solid(solids: list[cq.Shape], index: int | None) -> tuple[cq.Shape, int]:
    """The master's solid: the one named, the only one, or the largest."""

    if index is not None:
        if not 1 <= index <= len(solids):
            raise ValueError(
                f"The master solid index must be 1 to {len(solids)}, not {index}"
            )

        return solids[index - 1], index

    if len(solids) == 1:
        return solids[0], 1

    best = max(range(len(solids)), key=lambda i: solids[i].Volume())

    return solids[best], best + 1


def _commonest_size(diameters: list[float]) -> float:
    """The diameter most holes share, holes within a tolerance counting as one
    size; a tie goes to the smaller."""

    groups: list[list[float]] = []

    for diameter in sorted(diameters):
        if groups and diameter - groups[-1][-1] <= SIZE_TOLERANCE_MM:
            groups[-1].append(diameter)
        else:
            groups.append([diameter])

    best = max(groups, key=lambda group: (len(group), -group[0]))

    return round(best[0], 2)


def import_guide(
    master: Path,
    *,
    target: Path | None = None,
    identifier: str | None = None,
    master_solid_index: int | None = None,
    target_solid_index: int | None = None,
    offset_mm: tuple[float, float] = (0.0, 0.0),
    minimum_hole_mm: float = MINIMUM_HOLE_MM,
) -> ImportedGuide:
    """A guide file's data with a bore for each round through-hole of the
    master, around the target part (the master itself when none is given).

    Raises ``ValueError`` if the master has no such holes."""

    solids = load_solids(master)

    if not solids:
        raise ValueError(f"{master.name} holds no solids")

    source, used = _master_solid(solids, master_solid_index)
    box = source.BoundingBox()
    centre = ((box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2)
    holes = through_holes(source, minimum_hole_mm)

    if not holes:
        raise ValueError(
            f"{master.name} has no round through-hole of {minimum_hole_mm:g} mm or "
            "more about the vertical axis; the model must have +Z up, and a hole "
            "must run the part's whole height"
        )

    part_path = target or master
    part = load_part_file(part_path, None, target_solid_index if target else used)
    master_sha = hashlib.sha256(master.read_bytes()).hexdigest()
    drill_size = _commonest_size([hole.diameter_mm for hole in holes])
    depth = round(max(0.5, min(box.zlen, part.height_mm - DEPTH_MARGIN_MM)), 1)
    bores: list[dict[str, Any]] = []
    outside: list[str] = []

    for number, hole in enumerate(holes, start=1):
        name = f"H{number:02d}"
        x = round(hole.x_mm - centre[0] + offset_mm[0], 3)
        y = round(hole.y_mm - centre[1] + offset_mm[1], 3)
        entry: dict[str, Any] = {"identifier": name, "x_mm": x, "y_mm": y}

        if abs(hole.diameter_mm - drill_size) > SIZE_TOLERANCE_MM:
            entry["diameter_mm"] = round(hole.diameter_mm, 2)

        bores.append(entry)
        reach = board_outline.depth_inside(part.silhouette.points, (x, y))

        if reach < hole.diameter_mm / 2:
            outside.append(name)

    flat = part.silhouette.top_share >= MINIMUM_TOP_SHARE
    review = [
        (
            "drill.chuck_diameter_mm and drill.depth_mm: set them for your drill "
            "and how deep the holes go"
        )
    ]
    nest: dict[str, Any] = {
        "depth_mm": round(min(DEFAULT_NEST_DEPTH_MM, part.height_mm), 1),
        "wall_mm": DEFAULT_WALL_MM,
        "bearing": "top",
    }

    if not flat:
        nest.update(bearing="ledge", gap_mm=1.0)
        review.append(
            "nest: the part has no flat top, so it needs a ledge nest; set "
            "nest.depth_mm at a shoulder of the part, where it grows wider"
        )

    if outside:
        review.append(
            f"bores {', '.join(outside)} fall outside the target part: move them "
            "with an offset, or delete them"
        )

    data: dict[str, Any] = {
        "schema_version": GUIDE_SCHEMA_VERSION,
        "identifier": identifier or part_path.stem.upper().replace(" ", "_")[:60],
        "name": f"Guide from the holes of {master.name}",
        "units": "mm",
        "source": (
            f"Holes read from {master.name} (SHA-256 {master_sha}) by guide import; "
            "not checked against the real part"
        ),
        "notes": (
            "Each hole of the master is a bore at the same place in the part's own "
            "frame (centred on its bounding box, top at z = 0). Check the holes "
            "against the real part, set the drill, then remove needs_review."
        ),
        "part": {
            "step": str(part_path),
            "sha256": part.sha256,
        },
        "nest": nest,
        "plate": {},
        "drill": {
            "diameter_mm": drill_size,
            "chuck_diameter_mm": round(
                max(MINIMUM_CHUCK_MM, CHUCK_FACTOR * drill_size), 1
            ),
            "depth_mm": depth,
        },
        "bores": bores,
        "needs_review": review,
    }

    if target is not None and target_solid_index is not None:
        data["part"]["solid_index"] = target_solid_index
    elif target is None and len(solids) > 1:
        # The guide is built around the solid the holes were read from.
        data["part"]["solid_index"] = used

    sizes: dict[str, int] = {}

    for hole in holes:
        key = f"{hole.diameter_mm:.2f}"
        sizes[key] = sizes.get(key, 0) + 1

    report: dict[str, Any] = {
        "master": {"path": str(master), "sha256": master_sha, "solids": len(solids)},
        "master_solid_index": used,
        "target": str(part_path),
        "holes": len(holes),
        "hole_diameters_mm": sizes,
        "drill_diameter_mm": drill_size,
        "offset_mm": list(offset_mm),
        "outside_target": outside,
        "bearing": nest["bearing"],
        "plate_default_mm": DEFAULT_PLATE_MM,
    }

    return ImportedGuide(data=data, report=report)
