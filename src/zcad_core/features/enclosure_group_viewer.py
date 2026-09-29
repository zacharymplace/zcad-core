"""Data and page for the 3D viewer of Pi 5 group enclosures.

:func:`viewer_data` tessellates each configuration's base, lid, and Pi
envelopes into compact binary meshes, and :func:`viewer_page` returns the page
that draws them. The page reads ``enclosures.json`` from beside itself, so the
two are written into one folder and served together.
"""

from __future__ import annotations

import base64
import sys
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any

import cadquery as cq

from zcad_core.features.enclosure_group import (
    Bay,
    BayLike,
    BayOpening,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.features.enclosure_group_dividers import Divider

DATA_FILE = "enclosures.json"
PAGE_FILE = "index.html"
_TEMPLATE = "data/enclosure-group-viewer.html"
_TOLERANCE_MM = 0.3
_ANGULAR_TOLERANCE_RAD = 0.4
# Vertex indices are stored as 16-bit; a bigger mesh would wrap silently.
_MAX_VERTICES = 65535
_STANDALONE_HEAD = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "</head>\n<body>\n"
)


@dataclass(frozen=True)
class ViewerConfig:
    """One enclosure the viewer shows: a key, a name, and what to look at."""

    key: str
    name: str
    blurb: str
    bays: tuple[BayLike, ...]


DEFAULT_CONFIGS: tuple[ViewerConfig, ...] = (
    ViewerConfig(
        "pair",
        "Default pair",
        "Two Pi 5 bays, each with a service gap on its right.",
        ("pi5", "pi5"),
    ),
    ViewerConfig(
        "divided",
        "Divided pair",
        "A divider between the Pis, with vents, a header notch, and zip-tie slots.",
        (
            "pi5",
            Bay("pi5", divider=Divider(vents=True, notch=True, tie_slots=True)),
        ),
    ),
    ViewerConfig(
        "low",
        "Low divider",
        "A 12 mm divider between the Pis, open at the top, for separating cables.",
        ("pi5", Bay("pi5", divider=Divider(height_mm=12.0))),
    ),
    ViewerConfig(
        "raised",
        "Raised bay",
        "The first Pi stands 12 mm up, for a board underneath. The second has "
        "30 mm of headroom for a HAT.",
        (Bay("pi5", standoff_height_mm=12.0), Bay("pi5", headroom_mm=30.0)),
    ),
    ViewerConfig(
        "shelf",
        "Pair and open shelf",
        "A third, open bay with a back opening for a cable and a wider front opening.",
        (
            "pi5",
            "pi5",
            Bay(
                "open",
                openings=(
                    BayOpening("back", 20.0, 10.0, offset_mm=-5.0, bottom_mm=3.0),
                    BayOpening("front", 12.0, 8.0),
                ),
            ),
        ),
    ),
)


def viewer_data(
    configs: Sequence[ViewerConfig] = DEFAULT_CONFIGS,
) -> list[dict[str, Any]]:
    """Each configuration built, checked, and tessellated for the page.

    Raises ``ValueError`` if a configuration fails to build or fails one of its
    fit checks, naming it: the viewer would otherwise show a design the builder
    itself rejects.
    """

    if not configs:
        raise ValueError("The viewer needs at least one configuration")

    keys = [config.key for config in configs]

    if len(set(keys)) != len(keys):
        raise ValueError(f"Viewer configuration keys must be unique; got {keys}")

    return [_entry(config) for config in configs]


def _entry(config: ViewerConfig) -> dict[str, Any]:
    try:
        group = build_group_enclosure(config.bays)
    except ValueError as error:
        raise ValueError(f"Viewer configuration '{config.key}': {error}") from error

    if not group.passed:
        failed = sorted(name for name, ok in group.checks.items() if not ok)
        raise ValueError(
            f"Viewer configuration '{config.key}' fails its checks: {failed}"
        )

    return {
        "key": config.key,
        "name": config.name,
        "blurb": config.blurb,
        "size": [round(value, 2) for value in group.outer_size_mm],
        "cavity_top": round(group.cavity_top_z_mm, 2),
        "wall": group.design.wall_mm,
        "bays": _bays(group),
        "base": _mesh(group.base.val()),
        "lid": _mesh(group.lid.val()),
        "pis": [_mesh(shape) for shape in group.hardware.values()],
    }


def _bays(group: GroupEnclosure) -> list[dict[str, Any]]:
    return [
        {
            "kind": bay.kind,
            "gap": [round(bay.gap_start_mm, 2), round(bay.gap_end_mm, 2)],
            "slot": [round(bay.slot_start_mm, 2), round(bay.slot_end_mm, 2)],
            "standoff": bay.standoff_height_mm,
            "room": round(group.room_above_board_mm(bay), 1),
            "divider": bay.divider is not None,
        }
        for bay in group.bays
    ]


def _mesh(shape: object) -> dict[str, str]:
    """A shape as base64 float32 vertices and uint16 triangle indices."""

    if not isinstance(shape, cq.Shape):
        raise TypeError("Expected a shape to tessellate")

    vertices, triangles = shape.tessellate(_TOLERANCE_MM, _ANGULAR_TOLERANCE_RAD)

    if len(vertices) > _MAX_VERTICES:
        raise ValueError(
            f"A mesh of {len(vertices)} vertices is too big for 16-bit indices"
        )

    positions = array("f")
    indices = array("H")

    for point in vertices:
        positions.extend((point.x, point.y, point.z))

    for triangle in triangles:
        indices.extend(triangle)

    if sys.byteorder == "big":
        positions.byteswap()
        indices.byteswap()

    return {
        "v": base64.b64encode(positions.tobytes()).decode("ascii"),
        "i": base64.b64encode(indices.tobytes()).decode("ascii"),
    }


def viewer_page(*, standalone: bool = False) -> str:
    """The viewer page.

    By default it is the fragment the Artifact tool wraps at publish time. A
    ``standalone`` page carries its own document skeleton, for opening from a
    local web server.
    """

    page = (
        resources.files("zcad_core.features")
        .joinpath(_TEMPLATE)
        .read_text(encoding="utf-8")
    )

    if standalone:
        return f"{_STANDALONE_HEAD}{page}</body>\n</html>\n"

    return page
