"""The checks of what is on a board: its cable connector, its parts, the envelope that stands
for them, the openings a wall needs, and the power it draws.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from zcad_core.hardware.electronics import board_outline
from zcad_core.hardware.electronics.board_file_findings import (
    _edge_length,
    _Findings,
    _number,
    _section,
)
from zcad_core.hardware.electronics.board_file_model import (
    _IDENTIFIER,
    EDGES,
    MAXIMUM_OVERHANG_MM,
    OUTLINE_TOLERANCE_MM,
    OVERHANG_MM,
)
from zcad_core.hardware.electronics.board_outline import Point


def _check_connector(
    data: Mapping[str, Any],
    size: tuple[float, float, float] | None,
    findings: _Findings,
    outline: tuple[Point, ...] | None = None,
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
    across = board_length if edge.endswith("_y") else board_width

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

    if outline is not None:
        _check_connector_on_outline(
            outline,
            edge,
            width,
            depth,
            offset or 0.0,
            (board_width, board_length),
            findings,
        )


def _check_connector_on_outline(
    outline: tuple[Point, ...],
    edge: str,
    width: float,
    depth: float,
    offset: float,
    size: tuple[float, float],
    findings: _Findings,
) -> None:
    """The connector's footprint, against its edge of the bounding rectangle,
    must lie on the board: a rounded corner or a notch can leave it hanging."""

    half_w, half_l = size[0] / 2, size[1] / 2

    if edge == "negative_y":
        x0, x1, y0, y1 = (
            offset - width / 2,
            offset + width / 2,
            -half_l,
            -half_l + depth,
        )
    elif edge == "positive_y":
        x0, x1, y0, y1 = offset - width / 2, offset + width / 2, half_l - depth, half_l
    elif edge == "negative_x":
        x0, x1, y0, y1 = (
            -half_w,
            -half_w + depth,
            offset - width / 2,
            offset + width / 2,
        )
    else:
        x0, x1, y0, y1 = half_w - depth, half_w, offset - width / 2, offset + width / 2

    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))

    if any(
        board_outline.depth_inside(outline, c) < -OUTLINE_TOLERANCE_MM for c in corners
    ):
        findings.error(
            f"The cable connector hangs off the board's outline at its {edge} "
            "edge: a corner of it is outside the shape, as at a rounded corner "
            "or a notch"
        )


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
