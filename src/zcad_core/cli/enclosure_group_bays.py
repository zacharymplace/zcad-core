"""Reading the bays of a group enclosure from the command line: their openings, dividers,
board options, and a summary of each for the report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zcad_core.features.enclosure_group import (
    BAY_KINDS,
    OPENING_WALLS,
    Bay,
    BayOpening,
    GroupEnclosure,
    OpeningWall,
)
from zcad_core.features.enclosure_group_dividers import Divider
from zcad_core.hardware import load_board

_BAY_OPTIONS = {"standoff": "standoff_height_mm", "headroom": "headroom_mm"}


_OPENING_SYNTAX = "front=<width>x<height>[@<offset>[/<bottom>]]"


def _opening(wall: OpeningWall, value: str) -> BayOpening:
    """An opening from ``20x10``, ``20x10@-5``, or ``20x10@-5/3``: width and
    height, the offset from the shelf's middle, and the height above the
    floor, all in millimetres."""

    size, _, placement = value.partition("@")
    width, _, height = size.partition("x")
    offset, _, bottom = placement.partition("/")

    try:
        return BayOpening(
            wall=wall,
            width_mm=float(width),
            height_mm=float(height),
            offset_mm=float(offset) if offset else 0.0,
            bottom_mm=float(bottom) if bottom else 0.0,
        )
    except ValueError:
        raise ValueError(
            f"an opening must be {wall}=<width>x<height>[@<offset>[/<bottom>]] "
            f"in millimetres; got '{wall}={value}'"
        ) from None


_DIVIDER_TOKENS = "solid, vents, notch, ties, h<height>"


def _divider(value: str) -> Divider:
    """A divider from tokens joined by ``+``: ``solid`` for a plain full-height
    wall, ``vents``, ``notch``, ``ties``, and ``h12`` for a low one 12 mm tall,
    as in ``vents+notch+ties`` or ``h12``."""

    flags = {"solid": False, "vents": False, "notch": False, "ties": False}
    height: float | None = None

    for token in (part.strip() for part in value.split("+")):
        if token in flags:
            flags[token] = True
        elif token.startswith("h") and token[1:]:
            try:
                height = float(token[1:])
            except ValueError:
                raise ValueError(
                    f"a divider is {_DIVIDER_TOKENS}, joined by +; got '{token}'"
                ) from None
        else:
            raise ValueError(
                f"a divider is {_DIVIDER_TOKENS}, joined by +; got '{token}'"
            )

    return Divider(
        height_mm=height,
        vents=flags["vents"],
        notch=flags["notch"],
        tie_slots=flags["ties"],
    )


_BOARD_OPTIONS = (
    "file=<board file>, rotate=<0|90|180|270>, align=<front|center|back>, "
    "screw=<M2.5>; for a fan bay, fan=<identifier>, direction=<in|out>"
)


def _board_option(name: str, value: str, settings: dict[str, Any]) -> bool:
    """Take a board bay's option into ``settings``; ``False`` if it is not one."""

    if name == "file":
        settings["board"] = load_board(Path(value))
    elif name == "rotate":
        try:
            settings["rotate"] = int(value)
        except ValueError:
            raise ValueError(
                f"rotate must be 0, 90, 180 or 270; got '{value}'"
            ) from None
    elif name in ("align", "screw"):
        settings[name] = value
    elif name == "fan":
        settings["fan"] = value
    elif name == "direction":
        settings["fan_direction"] = value
    else:
        return False

    return True


def _bay(text: str) -> Bay:
    """One bay from ``kind``, with any of ``:standoff=10``, ``:headroom=30``,
    ``:front=20x10``, ``:back=20x10@-5/3``, and ``:divider=vents+notch``; a board
    bay is ``board:file=PATH`` with ``:rotate=``, ``:align=`` and ``:screw=``."""

    kind, *options = (part.strip() for part in text.split(":"))
    kinds = [known for known in BAY_KINDS if known == kind]

    if not kinds:
        raise ValueError(f"bay kind must be one of {BAY_KINDS}; got '{kind}'")

    heights: dict[str, Any] = {}
    board: dict[str, Any] = {}
    openings: list[BayOpening] = []
    divider: Divider | None = None

    for option in options:
        name, _, value = option.partition("=")
        walls = [known for known in OPENING_WALLS if known == name]

        if walls and value:
            openings.append(_opening(walls[0], value))
            continue

        if name == "divider" and value:
            divider = _divider(value)
            continue

        if value and _board_option(name, value, board):
            continue

        if name not in _BAY_OPTIONS or not value:
            raise ValueError(
                "bay option must be standoff=<mm>, headroom=<mm>, "
                f"{_OPENING_SYNTAX}, divider=<{_DIVIDER_TOKENS}>, or, for a board "
                f"bay, {_BOARD_OPTIONS}; got '{option}'"
            )

        try:
            heights[_BAY_OPTIONS[name]] = float(value)
        except ValueError:
            raise ValueError(f"bay option '{option}' needs a number") from None

    return Bay(
        kind=kinds[0],
        openings=tuple(openings),
        divider=divider,
        **heights,
        **board,
    )


def _bays(text: str) -> tuple[Bay, ...]:
    return tuple(_bay(part) for part in text.split(",") if part.strip())


def _bay_summary(group: GroupEnclosure) -> list[dict[str, object]]:
    return [
        {
            "bay": layout.index,
            "kind": layout.kind,
            "standoff_mm": layout.standoff_height_mm,
            "board_top_z_mm": layout.board_top_z_mm,
            "room_above_board_mm": round(group.room_above_board_mm(layout), 2),
            "openings": [
                {
                    "wall": opening.wall,
                    "width_mm": opening.width_mm,
                    "height_mm": opening.height_mm,
                    "offset_mm": opening.offset_mm,
                    "bottom_mm": opening.bottom_mm,
                }
                for opening in layout.openings
            ],
            "divider": (
                None
                if layout.divider is None
                else {
                    "full_height": layout.divider.full_height,
                    "height_mm": layout.divider.height_mm,
                    "vents": layout.divider.vents,
                    "notch": layout.divider.notch,
                    "tie_slots": layout.divider.tie_slots,
                    "left_face_x_mm": layout.divider_start_mm + group.design.wall_mm,
                }
            ),
        }
        for layout in group.bays
    ]
